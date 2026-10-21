from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit, strategy_identity
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Instrument, Market, Strategy, Venue, Trial
from tradingbot.research import c11_total_return as c11
from tradingbot.strategy.c11_expiration import ExpirationWeek


def source(exit_price='110'):
    days = ['2026-02-13', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-23', '2026-02-24']
    rows = []
    for day in days:
        price = D(exit_price if day >= '2026-02-20' else '100')
        factor = D('.5' if day < '2026-02-18' else '.51')
        rows.append({'date': day, 'opens_at': day+'T14:30:00+00:00', 'closes_at': day+'T21:00:00+00:00',
            'conservative_cash_release': str(date.fromisoformat(day)+timedelta(days=2))+'T14:30:00+00:00',
            'quote': {'open': str(price), 'close': str(price), 'raw_open': str(price/factor),
                      'raw_close': str(price/factor), 'factor': str(factor)}})
    return {'sha256': 'synthetic-'+uuid.uuid4().hex, 'prices': rows}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        transaction = conn.begin()
        with Session(conn, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def setup(db, data):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    strategy = Strategy(key='test-c11-'+suffix, name='Synthetic C11', status='backtest', allocation_usd=D(140))
    market = Market(venue_id=venue.id, external_id='test-c11-'+suffix, market_type='equity')
    db.add_all([strategy, market]); db.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id='test-c11-'+suffix,
                      instrument_type='equity', symbol='SPY', currency='USD', contract_multiplier=D(1))
    db.add(inst); db.flush()
    params = {'instrument_id': inst.id, 'slot_usd': '140', 'windows': c11.windows(data['prices'], 'expiry-close')}
    bot = ExpirationWeek(params)
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date()-timedelta(days=1)), source_hash='synthetic', source_url='synthetic')
    runtime = c11.C11Backtester(db, strategy=bot, strategy_id=strategy.id, source=data, fx=fx)
    return runtime, bot


def training_split():
    return HoldoutSplit('test-c11-'+uuid.uuid4().hex, datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


def test_calendar_holidays_and_control_session_count():
    start, end = date(2025, 4, 1), date(2025, 5, 1)
    days = [start+timedelta(days=i) for i in range((end-start).days)]
    rows = [{'date': str(d)} for d in days if d.weekday() < 5 and str(d) != '2025-04-18']
    actual, = c11.windows(rows, 'expiry-close')
    assert (actual['decision'], actual['entry'], actual['exit']) == ('2025-04-11', '2025-04-14', '2025-04-17')
    next_open, = c11.windows(rows, 'next-open')
    assert next_open['exit'] == '2025-04-21'
    # +7 shifts decision onto Good Friday, so never roll it to another date.
    assert c11.windows(rows, 'expiry-close', 7) == []
    prior, = c11.windows(rows, 'expiry-close', -7)
    assert prior['entry'] == '2025-04-07' and prior['exit'] == '2025-04-10'


def test_adjustment_change_does_not_create_separate_dividend_cash(db, monkeypatch):
    data, split = source(), training_split()
    runtime, bot = setup(db, data)
    monkeypatch.setattr(c11, 'split_for', lambda _: split)
    result = runtime.run(c11.events(data, bot.params, 10, False, []), split=split)
    metrics, trips, fills = c11.finish_metrics(db, result, runtime, expected_trips=1)
    assert len(fills) == 2 and metrics['fees_usd'] == D('.04') and metrics['net_usd'] > 0
    assert all(f.metadata_['research']['separate_dividend_credit'] is False for f in fills)
    assert len(runtime.cash[0]) == 2
    assert D(fills[0].metadata_['research']['fee']['raw_share_equivalent']) == fills[0].size*D('.5')
    assert D(fills[1].metadata_['research']['fee']['raw_share_equivalent']) == fills[1].size*D('.51')
    assert runtime.risk.stale_data_check(bot.params['instrument_id'], fills[1].fill_ts+timedelta(seconds=31))[0] is False


def test_gap_retains_unchanged_kill_and_daily_halt(db, monkeypatch):
    data, split = source('30'), training_split()
    runtime, bot = setup(db, data)
    monkeypatch.setattr(c11, 'split_for', lambda _: split)
    result = runtime.run(c11.events(data, bot.params, 10, False, []), split=split)
    assert runtime.killed and runtime.daily_halted is False  # final session resets only the daily halt
    assert {x['kind'] for x in runtime.halt_events} == {'per_strategy_kill', 'global_daily_halt'}
    assert result.fills == 1 and result.orders_rejected == 2  # scheduled and terminal exits vetoed


def test_intraday_partition_filters_close_and_incomplete_roundtrip(monkeypatch):
    data = source()
    split = HoldoutSplit('test-c11-cutoff', datetime(2026, 2, 20, tzinfo=UTC), datetime(2026, 2, 21, 6, tzinfo=UTC))
    assert split.holdout_start == datetime(2026, 2, 20, 21, tzinfo=UTC)
    monkeypatch.setattr(c11, 'split_for', lambda _: split)
    params = {'instrument_id': 1, 'windows': c11.windows(data['prices'], 'expiry-close')}
    events = list(c11.events(data, params, 10, False, []))
    assert len(events) == 1 and events[0].meta['phase'] == 'open'
    assert events[0].meta['terminal_open'] and not events[0].meta['window_complete_in_partition']


def test_holdout_is_claimed_before_feed_iteration(db, monkeypatch):
    from tradingbot.backtest import engine
    data, split = source(), training_split()
    runtime, bot = setup(db, data)
    observed = []
    def refuse(*args, **kwargs):
        assert observed == []
        raise ValueError('test claim refused')
    monkeypatch.setattr(engine, 'claim_final', refuse)
    with pytest.raises(ValueError, match='claim refused'):
        runtime.run(c11.events(data, bot.params, 10, True, observed), split=split, final_holdout=True)
    assert not observed


def test_total_return_fee_book_preserves_underlying_notional_and_share_fee():
    from tradingbot.research.equity_fees import EquityFeeBook
    runtime = SimpleNamespace(factor=D('.25'))
    book, raw = c11.TotalReturnFees(runtime), EquityFeeBook()
    day = date(2026, 1, 2)
    assert book.charge(day=day, side='sell', price=D(20), size=D(8))[0] == raw.charge(
        day=day, side='sell', price=D(80), size=D(2))[0]
