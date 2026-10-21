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
from tradingbot.research import option_income as income
from tradingbot.strategy.option_income import LENGTH, OptionIncomeHold, Trend


def test_hold_is_always_long_and_trend_waits_for_200_closes():
    assert [Trend('hold').update(c) for c in (1, 2, 3)] == [1, 1, 1]
    t = Trend('trend200')
    assert [t.update(100+i) for i in range(LENGTH-1)] == [0]*(LENGTH-1)
    assert t.update(1000) == 1  # 200th close, above the mean of all 200
    flat = Trend('trend200')
    assert [flat.update(100) for _ in range(LENGTH)][-1] == 0  # equal to the mean is not above it


def test_trend_is_causal_and_uses_only_the_last_200_closes():
    closes = [100+(i*37 % 23)-i/10 for i in range(500)]
    full = Trend('trend200')
    path = [full.update(c) for c in closes]
    prefix = Trend('trend200')
    assert path[:300] == [prefix.update(c) for c in closes[:300]]
    assert set(path[LENGTH:]) == {0, 1}
    assert full.average == sum((D(str(c)) for c in closes[-LENGTH:]), D(0))/LENGTH


def test_bad_inputs_refused():
    with pytest.raises(ValueError, match='variant'):
        Trend('trend50')
    with pytest.raises(ValueError, match='close'):
        Trend('hold').update(0)


def test_dividend_reference_matches_the_adjusted_close_convention():
    from datetime import date
    days = [date(2026, 3, d) for d in (2, 3, 4, 5, 6)]
    closes = dict(zip(days, (D(10), D('10.1'), D('9.95'), D('10.02'), D('10.04'))))
    dividends = {days[1]: D('.1'), days[3]: D('.05'), date(2026, 3, 7): D('.01')}
    levels, unmatched = income.dividend_reference(closes, dividends)
    assert set(levels) == set(days[1:])  # coverage starts at the first recorded ex-date
    assert unmatched == ['2026-03-07']
    assert levels[days[3]]/levels[days[2]] == closes[days[3]]/(closes[days[2]]-D('.05'))
    # A Yahoo-style back-adjusted series (factor 1 - dividend/previous close) agrees exactly.
    factor, adjusted = D(1), {}
    for previous, day in reversed(list(zip(days, days[1:]))):
        adjusted[day] = closes[day]*factor
        factor *= 1-dividends.get(day, D(0))/closes[previous]
    adjusted[days[0]] = closes[days[0]]*factor
    check = income.cross_check(adjusted, levels)
    assert check['passed'] and not check['disagreeing_days'] and check['paired_return_days'] == 3
    assert income.dividend_reference(closes, {}) == ({}, [])


def ctx(cash):
    return SimpleNamespace(position=lambda _: D(0), available_cash=lambda _: cash, marked_equity=lambda: D(140),
                           snapshot=lambda _: SimpleNamespace(bid=D(99), ask=D(101)))


def event(phase, day, mid=D(100), **meta):
    return SimpleNamespace(instrument_id=1, mid=mid, time=datetime(2026, 2, 2, tzinfo=UTC)+timedelta(days=day),
                           meta={'phase': phase, **meta})


def test_trend_strategy_buys_at_the_open_after_the_signal_close_and_never_on_terminal():
    bot = OptionIncomeHold({'instrument_id': 1, 'variant': 'trend200'})
    c = ctx(D(140))
    bot.on_start(c)
    for day in range(LENGTH-1):
        assert bot.on_event(c, event('close', day, D(100+day))) == []
        assert bot.on_event(c, event('open', day+1)) == []  # still warming up: no position wanted
    assert bot.on_event(c, event('close', LENGTH, D(1000))) == [] and bot.pending is not None
    assert bot.on_event(c, event('open', LENGTH+1, terminal_open=True)) == []
    order, = bot.on_event(c, event('open', LENGTH+1))
    assert order.side == 'buy' and order.size*order.limit_price <= D('132.99')


def test_settled_cash_required_for_entry():
    bot = OptionIncomeHold({'instrument_id': 1, 'variant': 'hold'})
    c = ctx(D(0))
    bot.on_start(c)
    bot.on_event(c, event('close', 0))
    assert bot.on_event(c, event('open', 1)) == [] and bot.skips and bot.pending is not None


def test_selection_ignores_descriptive_funds_and_breaks_ties_in_listed_order():
    def run(symbol, variant, net, selectable=True, complete=True):
        return {'symbol': symbol, 'variant': variant, 'selectable': selectable, 'status': 'complete',
                'trial_id': hash((symbol, variant)), 'metrics': {'net_usd': str(net), 'complete_execution': complete}}
    assert income.select_winner([run('JEPI', 'hold', 99, selectable=False), run('XYLD', 'hold', 5),
                                 run('QYLD', 'hold', 5), run('QYLD', 'trend200', 50, complete=False)])['symbol'] == 'XYLD'
    assert income.select_winner([run('XYLD', 'hold', 0), run('QYLD', 'trend200', -1)]) is None
    assert [g for g in income.grid() if not g[2]] == [('JEPI', 'hold', False), ('JEPQ', 'hold', False),
                                                       ('SPYI', 'hold', False)]


def synthetic_source():
    start = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)
    stamps = [start+timedelta(days=i) for i in range(100) if (start+timedelta(days=i)).weekday() < 5]
    def rows(drift):
        result = []
        for i, stamp in enumerate(stamps):
            close = D(100)+D(drift)*i+(D(i % 3)-1)
            quote = {'open': close-D('.2'), 'close': close, 'raw_open': close-D('.2'), 'raw_close': close, 'factor': '1'}
            result.append({'date': str(stamp.date()), 'opens_at': stamp.isoformat(),
                'closes_at': (stamp+timedelta(hours=6, minutes=30)).isoformat(),
                'conservative_cash_release': (stamp+timedelta(days=3)).isoformat(), 'quote': quote})
        return result
    return {'sha256': 'synthetic-'+uuid.uuid4().hex, 'panels': {
        'XYLD': {'passed': True, 'prices': rows('.1')}, 'SPY': {'passed': True, 'prices': rows('.2')},
        'QQQ': {'passed': True, 'prices': rows('.3')}}}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        tx = conn.begin()
        with Session(conn, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def test_hold_replay_costs_benchmarks_and_single_use_holdout(db, monkeypatch):
    from tradingbot.backtest import holdout
    # Keep the durable admission transaction inside this test's rollback boundary.
    monkeypatch.setattr(holdout, 'engine_for', lambda session: session.get_bind())
    data = synthetic_source()
    split = HoldoutSplit(data['sha256'], datetime(2026, 2, 2, tzinfo=UTC), datetime(2026, 5, 13, tzinfo=UTC))
    monkeypatch.setattr(income, 'split_for', lambda _: split)
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    suffix = uuid.uuid4().hex
    market = Market(venue_id=venue.id, external_id='income-test-'+suffix, market_type='equity')
    db.add(market); db.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id='income-test-'+suffix,
                      instrument_type='equity', symbol='XYLD', currency='USD', contract_multiplier=D(1))
    db.add(inst); db.flush()
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date()), source_hash='test', source_url='test')
    prices = data['panels']['XYLD']['prices']
    def replay(final):
        row = Strategy(key='income-test-'+uuid.uuid4().hex, name='Synthetic income',
            status='backtest', allocation_usd=D(140), config={'research_family': 'test-'+suffix})
        db.add(row); db.flush()
        bot = OptionIncomeHold({'instrument_id': inst.id, 'variant': 'hold'})
        bot.key = 'test-income-'+suffix
        runtime = income.IncomeBacktester(db, strategy=bot, strategy_id=row.id,
                                          source={'sha256': data['sha256'], 'prices': prices}, fx=fx)
        observed = []
        result = runtime.run(income.events(data, 'XYLD', inst.id, final, observed), split=split,
                             final_holdout=final, version_params={'synthetic': suffix})
        metrics, trips, fills = income.finish_metrics(db, result, runtime, allow_rejections=True, require_flat=False)
        return bot, runtime, observed, metrics, trips, fills
    bot, runtime, observed, metrics, trips, fills = replay(False)
    assert len(trips) == 1 and not metrics['open_positions'] and metrics['rejected_orders'] == 0
    entry, exit_ = fills
    first_close = next(e.time for e in observed if e.meta['phase'] == 'close')
    first_open_after = next(e.time for e in observed if e.meta['phase'] == 'open' and e.time > first_close)
    assert entry.side == 'buy' and entry.fill_ts == first_open_after
    assert exit_.side == 'sell' and exit_.fill_ts == max(e.time for e in observed if e.meta['phase'] == 'open')
    assert entry.price > D(entry.metadata_['research']['execution']['reference']) > 0
    assert exit_.price < D(exit_.metadata_['research']['execution']['reference'])
    assert entry.metadata_['research']['source'] == 'option_income_total_return_equivalent'
    extra = income.comparison(data, observed, runtime)
    assert D('.9') < D(extra['exposure']) < 1
    assert D(extra['QQQ']['full']['total_return']) > D(extra['SPY']['full']['total_return']) > 0
    assert D(extra['SPY']['equal_exposure']['usd_on_140']) > 0
    assert extra['strategy']['volatility'] > 0 and not any(w['covered'] for w in extra['stress'].values())
    replay(True)
    with pytest.raises(HoldoutViolation):
        replay(True)
