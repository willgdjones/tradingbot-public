from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Incident, Instrument, Market, Strategy, Trial, Venue
from tradingbot.research import c20_january_small_cap as c20
from tradingbot.strategy.c20_january_small_cap import JanuarySmallCap, SYMBOLS
from tradingbot.strategy.interface import MarketEvent


HOLIDAYS = {date(2020, 11, 26), date(2020, 12, 25), date(2021, 1, 1),
            date(2021, 1, 18), date(2021, 2, 15)}


def source(*, qualify=True, january_up=True):
    """Weekday sessions Nov 2020 - Mar 2021: Nov flat, a weak (or strong)
    December, and a rising (or falling) January."""
    days, day = [], date(2020, 11, 2)
    while day <= date(2021, 3, 1):
        if day.weekday() < 5 and day not in HOLIDAYS:
            days.append(day)
        day += timedelta(days=1)
    jan = [d for d in days if d.year == 2021 and d.month == 1]
    rows = []
    for day in days:
        if day <= date(2020, 11, 30):
            iwm = D(100)
        elif day.year == 2020 and day.month == 12:
            iwm = D(90) if qualify else D(110)
        else:
            step = jan.index(day) if day in jan else len(jan) - 1
            iwm = D(90) + (D(step) if january_up else D(-step))
        quotes = {}
        for symbol, price in (('IWM', iwm), ('SPY', D(100))):
            quotes[symbol] = {'open': str(price), 'close': str(price), 'factor': '1',
                              'raw_open': str(price), 'raw_close': str(price)}
        opened = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NEW_YORK)
        rows.append({'date': str(day), 'opens_at': opened.isoformat(),
            'closes_at': opened.replace(hour=16).isoformat(),
            'conservative_cash_release': (opened + timedelta(days=2)).isoformat(), 'quotes': quotes})
    return {'sha256': 'synthetic-' + uuid.uuid4().hex, 'prices': rows}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        tx = conn.begin()
        with Session(conn, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def fx():
    return SimpleNamespace(at=lambda ts: (D('.75'), ts.date() - timedelta(days=1)),
                           source_hash='synthetic', source_url='synthetic')


def setup(db, data, variant='5'):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    strategy = Strategy(key='test-c20-' + suffix, name='Synthetic C20', status='backtest', allocation_usd=D(140))
    db.add(strategy); db.flush()
    ids = {}
    for symbol in SYMBOLS:
        market = Market(venue_id=venue.id, external_id='test-c20-' + suffix + symbol, market_type='equity')
        db.add(market); db.flush()
        inst = Instrument(venue_id=venue.id, market_id=market.id, external_id='test-c20-' + suffix + symbol,
            instrument_type='equity', symbol=symbol, currency='USD', contract_multiplier=D(1))
        db.add(inst); db.flush(); ids[symbol] = inst.id
    bot = JanuarySmallCap(c20.strategy_params(data, ids, variant))
    runtime = c20.C20Backtester(db, strategy=bot, strategy_id=strategy.id, source=data, fx=fx())
    return runtime, bot


def split():
    return HoldoutSplit('test-c20-' + uuid.uuid4().hex, datetime(2020, 1, 1, tzinfo=UTC), datetime(2023, 1, 1, tzinfo=UTC))


# --- Pure reactor over an explicit tiny calendar ----------------------------
class Context:
    def __init__(self):
        self.books, self.quantities = {}, {}
        self.cash = self.equity = D(140)
    def snapshot(self, iid): return self.books.get(iid)
    def position(self, iid): return self.quantities.get(iid, D(0))
    def available_cash(self, iid): return self.cash
    def marked_equity(self): return self.equity


def pure(variant='5'):
    jan = ['2021-01-04', '2021-01-05', '2021-01-06', '2021-01-07', '2021-01-08',
           '2021-01-11', '2021-01-12', '2021-01-13', '2021-01-14', '2021-01-15',
           '2021-01-18', '2021-01-19']
    calendar = ['2020-11-30', '2020-12-31'] + jan + ['2021-01-29']
    params = {'symbols': list(SYMBOLS), 'instrument_ids': dict(zip(SYMBOLS, range(1, 3))),
        'variant': variant, 'slot_usd': '140', 'target_weight': '.95', 'cash_reserve_weight': '.05',
        'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001', 'blackouts': [],
        'month_ends': ['2020-11-30', '2020-12-31', '2021-01-29'],
        'december_month_ends': ['2020-12-31'],
        'next_session': {a: b for a, b in zip(calendar, calendar[1:])}}
    bot = JanuarySmallCap(params); ctx = Context(); bot.on_start(ctx)
    return bot, ctx


def batch(bot, ctx, day, phase, prices, **meta):
    stamp = datetime.fromisoformat(day + ('T16:00:00' if phase == 'close' else 'T09:30:00')).replace(tzinfo=NEW_YORK)
    output = []
    for index, s in enumerate(SYMBOLS):
        price = D(prices[s]); iid = bot.ids[s]
        event = MarketEvent.quote(iid, stamp, mid=price, ask=price, bid=price,
            meta={'phase': phase, 'batch_last': index == len(SYMBOLS) - 1,
                  'next_open_in_partition': True, **meta})
        ctx.books[iid] = event.as_snapshot(); output.extend(bot.on_event(ctx, event))
    return output


def test_december_qualifier_enters_only_on_weak_small_cap():
    bot, ctx = pure()
    batch(bot, ctx, '2020-11-30', 'close', {'IWM': '100', 'SPY': '100'})
    assert not bot.decisions  # November month-end is not a decision day
    batch(bot, ctx, '2020-12-31', 'close', {'IWM': '90', 'SPY': '100'})
    decision = bot.decisions[-1]
    assert decision['qualifies'] and decision['entry_open'] == '2021-01-04' and decision['exit_open'] == '2021-01-11'
    assert bot.targets['IWM'] == D('133') and bot.targets['SPY'] == 0 and bot.reserve == D('7')
    assert bot.exit_open == '2021-01-11' and bot.pending == {'IWM'}


def test_positive_but_not_below_spy_does_not_qualify():
    bot, ctx = pure()
    batch(bot, ctx, '2020-11-30', 'close', {'IWM': '100', 'SPY': '100'})
    batch(bot, ctx, '2020-12-31', 'close', {'IWM': '110', 'SPY': '100'})  # IWM up
    assert bot.decisions[-1]['qualifies'] is False and bot.exit_open is None and not bot.pending


def test_negative_but_above_spy_does_not_qualify():
    bot, ctx = pure()
    batch(bot, ctx, '2020-11-30', 'close', {'IWM': '100', 'SPY': '100'})
    batch(bot, ctx, '2020-12-31', 'close', {'IWM': '99', 'SPY': '90'})  # both down, IWM above SPY
    assert bot.decisions[-1]['qualifies'] is False and bot.exit_open is None


@pytest.mark.parametrize('variant,exit_open', [('5', '2021-01-11'), ('10', '2021-01-18')])
def test_horizon_exit_open_is_s_plus_h(variant, exit_open):
    bot, ctx = pure(variant)
    batch(bot, ctx, '2020-11-30', 'close', {'IWM': '100', 'SPY': '100'})
    batch(bot, ctx, '2020-12-31', 'close', {'IWM': '90', 'SPY': '100'})
    assert bot.exit_open == exit_open


def test_entry_buys_iwm_then_fixed_exit_sells_and_spy_never_trades():
    bot, ctx = pure()
    batch(bot, ctx, '2020-11-30', 'close', {'IWM': '100', 'SPY': '100'})
    batch(bot, ctx, '2020-12-31', 'close', {'IWM': '90', 'SPY': '100'})
    batch(bot, ctx, '2021-01-04', 'observe_open', {'IWM': '90', 'SPY': '100'})
    batch(bot, ctx, '2021-01-04', 'reduce', {'IWM': '90', 'SPY': '100'})
    buys = batch(bot, ctx, '2021-01-04', 'buy', {'IWM': '90', 'SPY': '100'})
    assert len(buys) == 1 and buys[0].instrument_id == bot.ids['IWM'] and buys[0].side == 'buy'
    held = buys[0].size
    ctx.quantities[bot.ids['IWM']] = held
    # Hold through the horizon; the sell is scheduled at the close before S+H.
    for day in ('2021-01-04', '2021-01-05', '2021-01-06', '2021-01-07'):
        assert batch(bot, ctx, day, 'close', {'IWM': '95', 'SPY': '100'}) == []
        assert bot.exit_open == '2021-01-11'
    batch(bot, ctx, '2021-01-08', 'close', {'IWM': '95', 'SPY': '100'})
    assert bot.exit_open is None and bot.targets['IWM'] == 0 and bot.pending == {'IWM'}
    batch(bot, ctx, '2021-01-11', 'observe_open', {'IWM': '95', 'SPY': '100'})
    sells = batch(bot, ctx, '2021-01-11', 'reduce', {'IWM': '95', 'SPY': '100'})
    assert len(sells) == 1 and sells[0].instrument_id == bot.ids['IWM'] and sells[0].side == 'sell' and sells[0].size == held
    assert batch(bot, ctx, '2021-01-11', 'buy', {'IWM': '95', 'SPY': '100'}) == []


def test_incomplete_and_duplicate_close_batch_refused():
    bot, _ = pure(); ctx = Context()
    iid = bot.ids['SPY']
    event = MarketEvent.quote(iid, datetime(2020, 12, 31, 16, tzinfo=NEW_YORK), mid=D(100),
                              meta={'phase': 'close', 'batch_last': True})
    with pytest.raises(ValueError, match='incomplete'):
        bot.on_event(ctx, event)
    with pytest.raises(ValueError, match='duplicate'):
        bot.on_event(ctx, event)


# --- Shared ledger / backtester end to end ----------------------------------
def test_shared_ledger_terminal_flat_and_raw_equivalent_fees(db, monkeypatch):
    data, partition = source(), split()
    runtime, bot = setup(db, data)
    monkeypatch.setattr(c20, 'split_for', lambda _: partition)
    observed = []
    result = runtime.run(c20.events(data, bot.params, 10, False, observed), split=partition)
    metrics, trips, fills = c20.finish_metrics(db, result, runtime, expected_trips=1)
    assert result.orders_rejected == 0 and not any(q for q, _ in runtime.positions.values())
    assert {f.instrument_id for f in fills} == {bot.ids['IWM']}  # SPY reference never trades
    entry, exit_ = sorted(fills, key=lambda f: f.fill_ts)
    assert entry.side == 'buy' and exit_.side == 'sell'
    assert entry.fill_ts.astimezone(NEW_YORK).date() == date(2021, 1, 4)
    assert exit_.fill_ts.astimezone(NEW_YORK).date() == date(2021, 1, 11)
    assert all(f.metadata_['research']['source'] == 'c20_total_return_equivalent' for f in fills)
    assert all(not f.metadata_['research']['separate_dividend_credit'] for f in fills)
    detail = c20.diagnostics(bot, observed, trips, fills, runtime)
    assert detail['qualified_years'] == 1 and detail['entered_years'] == 1
    assert detail['luck']['p_value'] is None and detail['luck']['exit_month_clusters'] == 1
    assert D(detail['benchmarks']['SPY_buy_hold']['total_return']) == 0


def test_non_qualifying_year_runs_flat_with_no_trades(db, monkeypatch):
    data, partition = source(qualify=False), split()
    runtime, bot = setup(db, data)
    monkeypatch.setattr(c20, 'split_for', lambda _: partition)
    result = runtime.run(c20.events(data, bot.params, 10, False, []), split=partition)
    assert result.fills == 0 and result.orders_rejected == 0
    assert not any(q for q, _ in runtime.positions.values())
    assert [d for d in bot.decisions if d['kind'] == 'december_qualifier'][0]['qualifies'] is False


def test_repeat_final_preflight_records_incident(db, monkeypatch):
    data = source()
    key = f'c20-jsc-{data["sha256"][:12]}-5-10-final'
    strategy = Strategy(key=key, name='Synthetic old final', status='backtest', allocation_usd=140)
    db.add(strategy); db.flush()
    monkeypatch.setattr(c20, 'require_committed', lambda: 'synthetic')
    with pytest.raises(ValueError, match='already attempted'):
        c20.run_variant(db, data, '5', 10, final=True, expected_version='synthetic')
    incident = db.scalar(select(Incident).where(Incident.details['requested_strategy_id'].as_integer() == strategy.id))
    assert incident.details['kind'] == 'holdout_reuse'
