"""Runner tests for C-ROX (tradingbot-rox): month-end gating and a short
DB-backed end-to-end run with the HMM kernel monkeypatched for speed.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Instrument, Market, Strategy, Venue
from tradingbot.research import rox_hmm_regime as rox
import tradingbot.strategy.rox_hmm_regime as strat
from tradingbot.strategy.rox_hmm_regime import HmmRegimeStrategy, RegimeInference


def weekdays_in(year, month, start_day=1):
    out, day = [], date(year, month, start_day)
    while day.month == month:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def synthetic_source():
    """Rising January then falling February daily closes; factor 1 (raw == adj).
    One continuous, strictly ascending business-day stream across two months."""
    jan, feb = weekdays_in(2026, 1, 2), weekdays_in(2026, 2, 1)
    rows = []
    for d in jan + feb:
        price = D(100 + jan.index(d)) if d.month == 1 else D(100 + len(jan) - feb.index(d) - 1)
        iso = d.isoformat()
        rows.append({'date': iso, 'opens_at': iso + 'T14:30:00+00:00', 'closes_at': iso + 'T21:00:00+00:00',
            'conservative_cash_release': (d + timedelta(days=2)).isoformat() + 'T14:30:00+00:00',
            'quote': {'open': str(price), 'close': str(price), 'raw_open': str(price),
                      'raw_close': str(price), 'factor': '1'}})
    return {'sha256': 'synthetic-' + uuid.uuid4().hex, 'prices': rows}


def fake_infer(returns, params):
    recent = np.asarray(returns[-10:], dtype=float) if len(returns) else np.array([0.0])
    long_ok = bool(recent.mean() > 0)
    return RegimeInference(n_states=2, current_state=0 if long_ok else 1,
                           risk_off_state=1, state_means=(0.001, -0.001), long_ok=long_ok)


def test_month_ends_picks_last_session_of_each_month():
    data = synthetic_source()
    ends = rox.month_ends(data['prices'])
    assert ends == ['2026-01-30', '2026-02-27']
    assert all(any(r['date'] == e for r in data['prices']) for e in ends)


def test_events_tag_month_end_entry_and_terminal():
    data = synthetic_source()
    params = {'instrument_id': 1, 'month_ends': rox.month_ends(data['prices'])}
    split = HoldoutSplit('rox-test', datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
    orig = rox.split_for
    rox.split_for = lambda _: split
    try:
        evs = list(rox.events(data, params, 10, False, []))
    finally:
        rox.split_for = orig
    opens = [e for e in evs if e.meta['phase'] == 'open']
    assert sum(e.meta.get('terminal_open', False) for e in opens) == 1  # exactly one terminal open
    jan_end = [e for e in evs if e.meta['phase'] == 'close'
               and e.time.date().isoformat() == '2026-01-30']
    assert jan_end and jan_end[0].meta['next_open_in_partition'] is True
    feb_end = [e for e in evs if e.meta['phase'] == 'close'
               and e.time.date().isoformat() == '2026-02-27']
    assert feb_end and feb_end[0].meta['next_open_in_partition'] is False  # last session: no next open


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        transaction = conn.begin()
        with Session(conn, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def test_end_to_end_short_run(db, monkeypatch):
    monkeypatch.setattr(strat, 'infer_regime', fake_infer)
    data = synthetic_source()
    split = HoldoutSplit('rox-test-' + uuid.uuid4().hex, datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(rox, 'split_for', lambda _: split)
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    strategy = Strategy(key='test-rox-' + suffix, name='Synthetic C-ROX', status='backtest', allocation_usd=D(140))
    market = Market(venue_id=venue.id, external_id='test-rox-' + suffix, market_type='equity')
    db.add_all([strategy, market]); db.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id='test-rox-' + suffix,
                      instrument_type='equity', symbol='SPY', currency='USD', contract_multiplier=D(1))
    db.add(inst); db.flush()
    params = {'instrument_id': inst.id, 'symbol_id': inst.id, 'slot_usd': '140',
              'target_weight': '0.95', 'cash_reserve_weight': '0.05', 'buy_fee_reserve_usd': '0.01',
              'quantity_step': '0.000000001', 'month_ends': rox.month_ends(data['prices']),
              'n_states': 2, 'features': 'ret', 'min_obs': 5, 'vol_window': 20,
              'n_iter': 200, 'tol': 0.0001, 'covariance_type': 'full', 'random_state': 0}
    bot = HmmRegimeStrategy(params)
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date() - timedelta(days=1)),
                         source_hash='synthetic', source_url='synthetic')
    runtime = rox.C11Backtester(db, strategy=bot, strategy_id=strategy.id, source=data, fx=fx)
    result = runtime.run(rox.events(data, params, 10, False, []), split=split)
    metrics, trips, fills = rox.finish_metrics(db, result, runtime, allow_rejections=True, require_flat=False)
    # Rising January -> long at the first February open; terminal open liquidates.
    assert [f.order.side for f in fills] == ['buy', 'sell']
    assert any(d['target_weight'] == '0.95' for d in bot.decisions)
    assert metrics['net_usd'] is not None
    assert not runtime.positions or all(q == 0 for q, _ in runtime.positions.values())
