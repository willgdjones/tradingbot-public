from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Trial
from tradingbot.research.equity_data import Bar, EquityData
from tradingbot.research.turn_of_month import run_variant, validate_windows


def fixture_data(end=date(2026, 2, 27)):
    sessions, raw, adjusted, minute = {}, {}, {}, {}
    day = date(2026, 1, 1)
    # The January/February trade stays wholly in training; later source days
    # are reserved and never supplied to this replay.
    while day <= end:
        if day.weekday() < 5:
            opens = datetime.combine(day, datetime.min.time(), NEW_YORK) + timedelta(hours=9,minutes=30)
            close = opens + timedelta(hours=6,minutes=30)
            sessions[day] = MarketSession(day,day+timedelta(days=3),opens,close)
            bar = Bar('SPY',opens,D(500),D(501),D(499),D(500),D(1000))
            raw['SPY',opens] = adjusted['SPY',opens] = bar
            ts = close - timedelta(minutes=1)
            minute['SPY',ts] = Bar('SPY',ts,D(500),D(501),D(499),D(500),D(100))
        day += timedelta(days=1)
    return EquityData(sessions,{'bars_1Day_raw':raw,'bars_1Day_all':adjusted,'bars_1Min_raw':minute},'fixture-'+uuid.uuid4().hex,1,1,[])


def test_corporate_action_checks_allow_rounding_but_reject_factor_break():
    data = fixture_data()
    pairs=[(date(2026,1,5),date(2026,1,8))]
    assert validate_windows(data,'SPY',pairs,True)['complete_cycles']==1
    key = next(k for k in data.bars['bars_1Day_all'] if k[1].date()==date(2026,1,7))
    old = data.bars['bars_1Day_all'][key]
    data.bars['bars_1Day_all'][key] = Bar(old.symbol,old.time,old.open,old.high,old.low,D(499),old.volume)
    with pytest.raises(ValueError,match='factor changes'):
        validate_windows(data,'SPY',pairs,True)


def test_runner_records_completed_and_failed_variants_without_resetting_a_run():
    with local_engine().connect() as connection:
        transaction=connection.begin()
        with Session(connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            data=fixture_data()
            fx=SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_hash='fixture',source_url='fixture')
            run_id='fixture-'+uuid.uuid4().hex[:12]
            variant=('tom_minute_2bp',2,False,False)
            result=run_variant(session,data,fx,run_id,variant,'fixture-commit',date(2026,1,1),date(2026,2,10))
            assert 'error' not in result, result
            assert result['metrics']['trades']==1 and result['metrics']['ledger_net_usd']<0
            assert session.get(Trial,result['trial_id']).status=='complete'
            assert result['metrics']['holdout']['final_holdout'] is False
            regimes=result['metrics']['exit_date_regimes']
            assert regimes['periods']['from_2025']['trades']==1
            assert regimes['periods']['from_2025']['end_exclusive'] is None
            assert regimes['periods']['before_2023']['first_exit_date'] is None
            assert not {'2016_2022','2023_2026','2025_2026'} & result['metrics'].keys()
            stored=session.get(Trial,result['trial_id']).metrics['exit_date_regimes']
            assert stored['periods']['from_2025']['trades']==1
            with pytest.raises(ValueError,match='already attempted'):
                run_variant(session,data,fx,run_id,variant,'fixture-commit',date(2026,1,1),date(2026,2,10))
            data.bars['bars_1Min_raw'].clear()
            failed=run_variant(session,data,fx,run_id,('tom_minute_5bp',5,False,False),'fixture-commit',date(2026,1,1),date(2026,2,10))
            assert failed['status']=='failed' and 'missing execution bar' in failed['error']
            assert session.get(Trial,failed['trial_id']).status=='failed'
        transaction.rollback()


def test_slot_sized_runner_uses_cash_reserve_and_records_new_frozen_params():
    with local_engine().connect() as connection:
        transaction=connection.begin()
        with Session(connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            data=fixture_data()
            fx=SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_hash='fixture',source_url='fixture')
            result=run_variant(session,data,fx,'slot-'+uuid.uuid4().hex[:12],('tom_minute_2bp',2,False,False),
                               'fixture',date(2026,1,1),date(2026,2,10),entry_notional=D('140'),use_available_cash=True)
            assert 'error' not in result, result
            assert result['metrics']['trades']==1 and result['metrics']['rejected_orders']==0
            assert result['params']['strategy_params']['entry_notional']=='140'
            assert result['params']['strategy_params']['use_available_cash'] is True
            assert result['metrics']['ending_cash_including_unsettled']<D('140')
        transaction.rollback()


def test_slot_sizing_shrinks_after_loss_without_cash_topup():
    from dataclasses import replace
    from tradingbot.research.turn_of_month import cycles_for
    from tradingbot.db.models import Fill
    with local_engine().connect() as connection:
        transaction=connection.begin()
        with Session(connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            data=fixture_data(date(2026,6,30))
            first_exit=cycles_for(data,date(2026,1,1),date(2026,3,10))[0][1]
            for table in data.bars.values():
                for key, bar in list(table.items()):
                    if bar.time.astimezone(NEW_YORK).date() >= first_exit:
                        table[key]=replace(bar,open=D('450'),high=D('451'),low=D('449'),close=D('450'))
            fx=SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_hash='fixture',source_url='fixture')
            result=run_variant(session,data,fx,'loss-'+uuid.uuid4().hex[:12],('tom_minute_2bp',2,False,False),
                               'fixture',date(2026,1,1),date(2026,3,10),entry_notional=D('140'),use_available_cash=True)
            assert 'error' not in result, result
            assert result['metrics']['trades']==2 and result['metrics']['rejected_orders']==0
            buys=list(session.scalars(select(Fill).where(Fill.trial_id==result['trial_id'],Fill.side=='buy').order_by(Fill.fill_ts)))
            assert D('139') < buys[0].price*buys[0].size < D('140')
            assert D('125') < buys[1].price*buys[1].size < D('127')
            assert result['metrics']['ending_cash_including_unsettled'] < D('127')
        transaction.rollback()
