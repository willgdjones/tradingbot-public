from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.loader import local_engine
from tradingbot.research.turn_of_month import cycles_for
from tradingbot.research.turn_of_month_control import RandomWindowControl, run_control
from tradingbot.strategy.interface import MarketEvent
from test_turn_of_month_runner import fixture_data


def exercise(prices, *, missing=None):
    data=fixture_data(date(2026,6,30))
    calendar=[str(d) for d in sorted(data.sessions)]
    pairs=[[str(a),str(b)] for a,b in cycles_for(data,date(2026,1,1),date(2026,3,10))]
    core=RandomWindowControl({'calendar':calendar,'tom_pairs':pairs,'durations':[5,6],
        'seed':20261001,'draws':100,'slippage_bp_per_side':2,'comparison_notional':'139.99','round_trip_fee':'.04'})
    core.on_start(None)
    for day in sorted(data.sessions):
        if day > date(2026,3,10) or str(day)==missing: continue
        event=MarketEvent.quote(1,data.sessions[day].closes_at,last=prices.get(str(day),D('100')))
        assert core.on_event(SimpleNamespace(now=event.time),event)==[]
    core.on_finish(None)
    return core


def test_flat_total_returns_have_no_calendar_premium_and_repeatable_controls():
    first=exercise({}).result
    assert first==exercise({}).result
    assert first['actual_ledger_trades']==0
    for horizon, result in first['durations'].items():
        assert result['matched_cycles']==2
        assert result['tom_mean_gross_return']==0
        assert result['random_mean_gross_return']==0
        assert abs(result['calendar_excess_mean_return'])<1e-12
        assert result['random_at_least_tom_fraction']==1
        assert all(c['eligible_windows']>0 for c in result['candidates_by_month'])


def test_calendar_premium_uses_only_observed_total_return_windows():
    data=fixture_data(date(2026,6,30))
    pairs=cycles_for(data,date(2026,1,1),date(2026,3,10))
    # Jumps occur only at TOM exits, then persist. Midmonth controls are flat.
    prices={str(day):D(100+sum(day>=exit for _,exit in pairs)*10) for day in data.sessions}
    core=exercise(prices)
    for result in core.result['durations'].values():
        assert result['tom_mean_gross_return']>D('.09')
        assert result['random_mean_gross_return']==0
        assert result['calendar_excess_mean_return']>.09
        assert result['random_at_least_tom_fraction']==pytest.approx(1/101)
    # Future source dates never reach the diagnostic's observation state.
    assert max(core.closes)=='2026-03-10'


def test_missing_candidate_month_fails_instead_of_reusing_other_months():
    data=fixture_data(date(2026,6,30))
    a,b=cycles_for(data,date(2026,1,1),date(2026,3,10))[0]
    calendar=[str(d) for d in data.sessions]
    core=RandomWindowControl({'calendar':calendar,'tom_pairs':[[str(a),str(b)]],
        'durations':[5,6],'seed':20261001,'draws':10,'slippage_bp_per_side':2,
        'comparison_notional':'139.99','round_trip_fee':'.04'})
    core.on_start(None)
    for day in (a,b):
        core.on_event(None,MarketEvent.quote(1,data.sessions[day].closes_at,last=D(100)))
    with pytest.raises(ValueError,match='no eligible'):
        core.on_finish(None)


def test_control_is_a_logged_training_diagnostic_without_orders_or_investable_pnl():
    with local_engine().connect() as connection:
        outer=connection.begin()
        with Session(connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            result=run_control(session,fixture_data(date(2026,6,30)),run_id='control-'+uuid.uuid4().hex,commit='fixture')
            assert 'error' not in result,result
            assert result['metrics']['holdout']['final_holdout'] is False
            assert result['metrics']['nonexecution_diagnostic'] is True
            assert result['metrics']['actual_ledger_trades']==0
            from tradingbot.db.models import Trial
            trial=session.get(Trial,result['trial_id'])
            assert trial.status=='complete' and trial.pnl_after_fees is None
        outer.rollback()
