from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit, HoldoutViolation
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Instrument, Market, Strategy, Venue
from tradingbot.research import ibs_mean_reversion as ibs
from tradingbot.strategy.ibs import IBSReversion, Signal


def bar(value, low='100', width='10'):
    """A completed bar whose IBS is exactly `value`."""
    lo, w = D(low), D(width)
    close = lo+w*D(value)
    return {'open': lo+w/2, 'high': lo+w, 'low': lo, 'close': close}


def path(values):
    s = Signal()
    return [s.update(bar(v)) for v in values]


def test_crosses_under_ten_and_over_ninety_exactly():
    # First bar has no prior IBS, so it cannot cross; .10 itself is not under .10.
    assert path(['.05', '.5', '.10', '.09']) == [0, 0, 0, 1]
    # Holding: further lows do nothing; .90 is not over .90; .91 exits.
    assert path(['.5', '.05', '.02', '.90', '.91']) == [0, 1, 1, 1, 0]
    # Exit and immediate re-entry are both crosses of the prior bar.
    assert path(['.5', '.05', '.95', '.05']) == [0, 1, 0, 1]


def test_zero_range_bar_has_no_ibs_and_breaks_the_cross():
    s = Signal()
    flat = {'open': D(100), 'high': D(100), 'low': D(100), 'close': D(100)}
    assert [s.update(bar('.5')), s.update(flat), s.update(bar('.05'))] == [0, 0, 0]
    assert s.update(bar('.5')) == 0 and s.update(bar('.05')) == 1


def test_prefix_causality():
    values = [str(D(i*37 % 100)/100) for i in range(200)]
    full = path(values)
    assert full[:120] == path(values[:120])
    assert set(full) == {0, 1}


def test_bad_ohlc_refused():
    with pytest.raises(ValueError, match='OHLC'):
        Signal().update({'open': 10, 'close': 10, 'high': 9, 'low': 8})


def source():
    start = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)
    stamps = [start+timedelta(days=i) for i in range(100) if (start+timedelta(days=i)).weekday() < 5]
    rows = []
    for i, stamp in enumerate(stamps):
        b = bar(('.05', '.5', '.95', '.5')[i % 4])
        rows.append({'date': str(stamp.date()), 'opens_at': stamp.isoformat(),
            'closes_at': (stamp+timedelta(hours=6, minutes=30)).isoformat(),
            'conservative_cash_release': (stamp+timedelta(days=3)).isoformat(),
            'quote': {**b, 'factor': '1', 'raw_open': b['open'], 'raw_close': b['close']}})
    return {'sha256': 'synthetic-'+uuid.uuid4().hex, 'panels': {'QQQ': {'passed': True, 'prices': rows}}}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        tx = conn.begin()
        with Session(conn, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def test_replay_next_open_costs_flat_comparison_and_single_use_holdout(db, monkeypatch):
    from tradingbot.backtest import holdout
    # Keep the durable admission transaction inside this test's rollback boundary.
    monkeypatch.setattr(holdout, 'engine_for', lambda session: session.get_bind())
    data = source()
    split = HoldoutSplit(data['sha256'], datetime(2026, 2, 2, tzinfo=UTC), datetime(2026, 5, 13, tzinfo=UTC))
    monkeypatch.setattr(ibs, 'split_for', lambda _: split)
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    suffix = uuid.uuid4().hex
    market = Market(venue_id=venue.id, external_id='ibs-test-'+suffix, market_type='equity')
    db.add(market); db.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id='ibs-test-'+suffix,
                      instrument_type='equity', symbol='QQQ', currency='USD', contract_multiplier=D(1))
    db.add(inst); db.flush()
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date()), source_hash='test', source_url='test')
    prices = data['panels']['QQQ']['prices']
    def replay(final):
        row = Strategy(key='ibs-test-'+uuid.uuid4().hex, name='Synthetic IBS',
            status='backtest', allocation_usd=D(140), config={'research_family': 'test-'+suffix})
        db.add(row); db.flush()
        bot = IBSReversion({'instrument_id': inst.id})
        bot.key = 'test-ibs-'+suffix
        runtime = ibs.IBSBacktester(db, strategy=bot, strategy_id=row.id,
                                    source={'sha256': data['sha256'], 'prices': prices}, fx=fx)
        observed = []
        result = runtime.run(ibs.events(data, 'QQQ', inst.id, final, observed), split=split,
                             final_holdout=final, version_params={'synthetic': suffix})
        metrics, trips, fills = ibs.finish_metrics(db, result, runtime, allow_rejections=True, require_flat=False)
        return bot, runtime, observed, metrics, trips, fills
    bot, runtime, observed, metrics, trips, fills = replay(False)
    assert trips and not metrics['open_positions']
    assert runtime.charged > 0 and metrics['rejected_orders'] == 0
    assert all(f.metadata_['research']['execution']['phase'] == 'open' for f in fills)
    for fill in fills:
        reference = D(fill.metadata_['research']['execution']['reference'])
        assert (fill.price > reference) if fill.side == 'buy' else (fill.price < reference)
    assert all('ohlc' not in e.meta for e in observed if e.meta['phase'] == 'open')
    # Every fill is at an open strictly after the close that decided it.
    decided = [datetime.fromisoformat(d['time']) for d in bot.decisions]
    assert all(any(t < f.fill_ts for t in decided) for f in fills)
    assert all(f.metadata_['research']['source'] == 'ibs_total_return_equivalent' for f in fills)
    extra = ibs.comparison(observed, trips, fills, runtime)
    assert 0 < D(extra['equal_exposure_buy_hold']['exposure']) < 1
    assert extra['mean_net_percent_per_trade'] is not None and D(extra['mean_sessions_held']) >= 1
    replay(True)
    with pytest.raises(HoldoutViolation):
        replay(True)


def test_pending_entry_requires_settled_cash_and_terminal_never_buys():
    bot = IBSReversion({'instrument_id': 1})
    ctx = SimpleNamespace(position=lambda _: D(0), available_cash=lambda _: D(0),
                          snapshot=lambda _: SimpleNamespace(bid=D(99), ask=D(101)))
    bot.on_start(ctx)
    bot.units, bot.pending = 1, (D(133), D(7))
    event = SimpleNamespace(instrument_id=1, time=datetime(2026, 2, 2, tzinfo=UTC), meta={'phase': 'open'})
    assert bot.on_event(ctx, event) == []
    assert bot.pending is not None and bot.skips
    ctx.available_cash = lambda _: D(140)
    event.meta['terminal_open'] = True
    assert bot.on_event(ctx, event) == []
    event.meta['terminal_open'] = False
    order, = bot.on_event(ctx, event)
    assert order.side == 'buy' and order.size*order.limit_price <= D('132.99')
