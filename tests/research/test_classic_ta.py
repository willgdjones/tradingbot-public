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
from tradingbot.research import classic_ta as ta
from tradingbot.strategy.classic_ta import ClassicTA, RULES, Signal


def bar(close, open_=None, width='1'):
    c, o, w = D(close), D(open_ if open_ is not None else close), D(width)
    return {'open': o, 'close': c, 'high': max(o, c)+w, 'low': min(o, c)-w}


def signals(rule, bars):
    s = Signal(rule)
    return [s.update(b) for b in bars]


@pytest.mark.parametrize('rule', RULES)
def test_prefix_causality_and_position_bounds(rule):
    bars = [bar(str(100+i%13), str(101+i%11)) for i in range(130)]
    all_signals = signals(rule, bars)
    assert all_signals[:90] == signals(rule, bars[:90])
    assert set(all_signals) <= set(range(4 if rule == 'heikin_ashi' else 2))
    assert all_signals[0] == 0


def test_rsi_first_change_seed_warmup_and_flat_neutral():
    falling = [bar(str(100-i)) for i in range(15)]
    assert signals('rsi', falling) == [0]*14+[1]
    assert signals('rsi', [bar(str(100+i)) for i in range(20)]) == [0]*20
    assert signals('rsi', [bar('100')]*20) == [0]*20
    # Large gain pushes SMMA RSI out of oversold; long/flat must exit now.
    assert signals('rsi', falling+[bar('120')])[-1] == 0


def test_awesome_uses_simple_median_5_34_with_full_warmup():
    path = signals('awesome', [bar(str(100+i)) for i in range(40)])
    assert path[:33] == [0]*33
    assert path[33:] == [1]*7


def test_heikin_ashi_preserves_contrarian_direction_and_three_tranche_cap():
    bearish = [bar(str(200-i*i), str(202-i*i), '0') for i in range(10)]
    result = signals('heikin_ashi', bearish)
    assert result[:4] == [0, 1, 2, 3]
    assert max(result) == 3
    assert signals('heikin_ashi', bearish+[bar('240', '238', '0')]*3)[-1] == 0


def test_sar_initialization_and_reversal_extreme():
    s = Signal('sar')
    assert s.update(bar('10', width='1')) == 0
    assert s.update(bar('12', width='1')) == 1  # real SAR=prior high=11
    assert s.sar == 11 and s.ep == 13 and s.af == D('.02')
    assert s.update(bar('8', width='1')) == 0  # reversal real SAR=old EP=13
    assert s.trend == -1 and s.ep == 7 and s.af == D('.02')


def test_bollinger_is_not_generic_lower_band_buy():
    bars = [bar('100')]*80+[bar('75')]
    assert signals('bollinger', bars) == [0]*81


@pytest.mark.parametrize('rule', ('macd', 'shooting_star', 'dual_thrust'))
def test_unadmitted_defaults_refused(rule):
    with pytest.raises(ValueError, match='no admitted'):
        Signal(rule)


def test_bad_ohlc_refused():
    with pytest.raises(ValueError, match='OHLC'):
        Signal('rsi').update({'open': 10, 'close': 10, 'high': 9, 'low': 8})


def source():
    start = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)
    stamps = [start+timedelta(days=i) for i in range(100) if (start+timedelta(days=i)).weekday() < 5]
    rows = []
    for i, stamp in enumerate(stamps):
        close = D(150-i%19)
        b = bar(str(close))
        rows.append({'date': str(stamp.date()), 'opens_at': stamp.isoformat(),
            'closes_at': (stamp+timedelta(hours=6, minutes=30)).isoformat(),
            'conservative_cash_release': (stamp+timedelta(days=3)).isoformat(),
            'quote': {**b, 'factor': '1', 'raw_open': close, 'raw_close': close}})
    return {'sha256': 'synthetic-'+uuid.uuid4().hex, 'prices': rows,
            'panels': {'SPY': {'passed': True, 'prices': rows}}}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        tx = conn.begin()
        with Session(conn, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def test_shared_replay_next_open_costs_flat_and_single_use_holdout(db, monkeypatch):
    from tradingbot.backtest import holdout
    # Keep the durable admission transaction inside this test's rollback boundary.
    monkeypatch.setattr(holdout, 'engine_for', lambda session: session.get_bind())
    data = source()
    split = HoldoutSplit(data['sha256'], datetime(2026, 2, 2, tzinfo=UTC), datetime(2026, 5, 13, tzinfo=UTC))
    monkeypatch.setattr(ta, 'split_for', lambda _: split)
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    suffix = uuid.uuid4().hex
    market = Market(venue_id=venue.id, external_id='classic-test-'+suffix, market_type='equity')
    db.add(market); db.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id='classic-test-'+suffix,
                      instrument_type='equity', symbol='SPY', currency='USD', contract_multiplier=D(1))
    db.add(inst); db.flush()
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date()), source_hash='test', source_url='test')
    def replay(final):
        row = Strategy(key='classic-test-'+uuid.uuid4().hex, name='Synthetic classic TA',
            status='backtest', allocation_usd=D(140), config={'research_family': 'test-'+suffix})
        db.add(row); db.flush()
        bot = ClassicTA({'rule': 'rsi', 'instrument_id': inst.id})
        bot.key = 'test-classic-'+suffix
        runtime = ta.ClassicBacktester(db, strategy=bot, strategy_id=row.id, source=data, fx=fx)
        observed = []
        result = runtime.run(ta.events(data, 'SPY', inst.id, final, observed), split=split,
                             final_holdout=final, version_params={'synthetic': suffix})
        metrics, trips, fills = ta.finish_metrics(db, result, runtime, allow_rejections=True, require_flat=False)
        return bot, runtime, observed, metrics, trips, fills
    bot, runtime, observed, metrics, trips, fills = replay(False)
    assert trips and not metrics['open_positions']
    assert runtime.charged > 0 and metrics['rejected_orders'] == 0
    assert all(f.metadata_['research']['execution']['phase'] == 'open' for f in fills)
    for fill in fills:
        reference = D(fill.metadata_['research']['execution']['reference'])
        assert (fill.price > reference) if fill.side == 'buy' else (fill.price < reference)
    assert all('ohlc' not in e.meta for e in observed if e.meta['phase'] == 'open')
    assert all(f.fill_ts > datetime.fromisoformat(bot.decisions[0]['time']) for f in fills)
    assert all(f.metadata_['research']['source'] == 'classic_ta_total_return_equivalent' for f in fills)
    replay(True)
    with pytest.raises(HoldoutViolation):
        replay(True)


def test_rule_families_are_distinct_but_symbols_share_family():
    from tradingbot.backtest.holdout import family_identity
    aliases = []
    for rule in RULES:
        bot = ClassicTA({'rule': rule})
        family, names = family_identity(SimpleNamespace(id=1, config={'research_family': 'classic_ta_'+rule}),
                                        {'_frozen': {'key': bot.key}})
        assert family == bot.key
        aliases.append(names[-1])
    assert len(set(aliases)) == len(RULES)


def test_pending_entry_requires_settled_cash_and_terminal_never_buys():
    bot = ClassicTA({'rule': 'rsi', 'instrument_id': 1})
    ctx = SimpleNamespace(position=lambda _: D(0), available_cash=lambda _: D(0),
                          snapshot=lambda _: SimpleNamespace(bid=D(99), ask=D(101)))
    bot.on_start(ctx)
    bot.units, bot.pending = 1, (D(133), D(7))
    event = SimpleNamespace(instrument_id=1, time=datetime(2026, 2, 2, tzinfo=UTC), meta={'phase': 'open'})
    assert bot.on_event(ctx, event) == []
    assert bot.pending is not None
    ctx.available_cash = lambda _: D(140)
    event.meta['terminal_open'] = True
    assert bot.on_event(ctx, event) == []
    event.meta['terminal_open'] = False
    order, = bot.on_event(ctx, event)
    assert order.size*order.limit_price <= D('132.99')
