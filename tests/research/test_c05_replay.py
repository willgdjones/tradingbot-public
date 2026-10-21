"""Synthetic tests only: no candidate return inspection during development."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Incident, Instrument, Market, Strategy as StrategyRow, Trial, Venue
import tradingbot.research.c05_replay as replay
from tradingbot.research.turn_of_month import scenario_quote
from tradingbot.strategy.c05_commodity_trend import CommodityTrend, positive_signal


def test_signals_require_in_partition_history_and_equality_is_cash():
    rising = [D(1) + D(n)/1000 for n in range(253)]
    assert not positive_signal(rising[:252], replay.VARIANTS[0])
    assert positive_signal(rising, replay.VARIANTS[0])
    assert not positive_signal(rising[:126], replay.VARIANTS[1])
    assert positive_signal(rising[:127], replay.VARIANTS[1])
    assert not positive_signal(rising[:199], replay.VARIANTS[2])
    assert positive_signal(rising[:200], replay.VARIANTS[2])
    for variant in replay.VARIANTS:
        assert not positive_signal([D(1)] * 253, variant)


class Context:
    def __init__(self, day='2020-07-01'):
        self.quantities = {i: D(0) for i in range(1, 6)}
        self.cash, self.equity = D(140), D(140)
        self.refs = {i: scenario_quote(i, datetime.fromisoformat(day+'T09:30:00-04:00'), D(10), 10).as_snapshot()
                     for i in range(1, 6)}
    def position(self, iid): return self.quantities[iid]
    def snapshot(self, iid): return self.refs[iid]
    def available_cash(self, _): return self.cash
    def marked_equity(self): return self.equity


def simple_bot():
    params = {'symbols': list(replay.SYMBOLS), 'instrument_ids': dict(zip(replay.SYMBOLS, range(1, 6))),
        'variant': replay.VARIANTS[1], 'sleeve_weight': '.19', 'cash_reserve_weight': '.05',
        'slot_usd': '140', 'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001',
        'blackouts': [], 'month_ends': ['2020-06-30'], 'next_session': {'2020-06-30': '2020-07-01'}}
    bot, ctx = CommodityTrend(params), Context()
    bot.on_start(ctx)
    return bot, ctx


def test_monthly_targets_no_inactive_redistribution_and_fixed_during_cash_delay():
    bot, ctx = simple_bot()
    bot.signals['GLD'] = bot.signals['UNG'] = True
    bot._freeze(ctx, bot.symbols, '2020-06-30', 'monthly rebalance')
    assert bot.targets['GLD'] == bot.targets['UNG'] == D('26.60')
    assert bot.targets['DBA'] == 0 and bot.reserve == 7
    ctx.cash = D(12)
    first = bot._allocate_buys(ctx, '2020-07-01')
    assert first['GLD'][0] == first['UNG'][0] == D('2.49')
    ctx.cash, ctx.equity = D(200), D(200)
    later = bot._allocate_buys(ctx, '2020-07-01')
    assert later['GLD'][0] == D('26.60') and bot.reserve == 7
    bot._freeze(ctx, bot.symbols, '2020-06-30', 'monthly rebalance')
    assert bot.targets['GLD'] == D(28)  # aggregate slot / five sleeves


def test_subdollar_pro_rata_share_is_not_redistributed():
    bot, ctx = simple_bot()
    bot.targets, bot.pending, bot.reserve = {'GLD': D('.5'), 'SLV': D(10)}, {'GLD', 'SLV'}, D(0)
    ctx.cash = D('5.27')  # 5.25 after both estimated fee reserves
    result = bot._allocate_buys(ctx, '2020-07-01')
    assert result['GLD'][0] == D('.25') and result['SLV'][0] == D(5)


def test_stale_other_open_prevents_cross_asset_sizing():
    bot, ctx = simple_bot()
    bot.targets, bot.pending = {'GLD': D(10), 'SLV': D(10)}, {'GLD', 'SLV'}
    ctx.refs[2] = scenario_quote(2, datetime(2020, 6, 30, tzinfo=UTC), D(10), 10).as_snapshot()
    with pytest.raises(ValueError, match='fresh opens'):
        bot._allocate_buys(ctx, '2020-07-01')


@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def synthetic_source():
    split = HoldoutSplit('test-c05-'+uuid.uuid4().hex, datetime(2020, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC))
    days, day = [], date(2020, 1, 2)
    while len(days) < 165:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    rows = []
    for index, day in enumerate(days):
        base = D(10) + D(index)/1000
        quotes = {}
        for symbol in replay.SYMBOLS:
            raw = base * (4 if symbol == 'UNG' and index >= 141 else 1)
            if symbol == 'DBA' and index >= 138:
                raw -= D('.1')
            quotes[symbol] = {'open': str(raw), 'close': str(raw), 'adjusted_close': str(base),
                'split_continuous_close': str(base*4 if symbol == 'UNG' else base), 'split_ratio': '1'}
        release = days[index+2] if index+2 < len(days) else day+timedelta(days=4)
        rows.append({'date': str(day), 'opens_at': str(day)+'T09:30:00-04:00',
            'closes_at': str(day)+'T16:00:00-04:00', 'scheduled_t1': str(day+timedelta(days=1)),
            'completed_settlement': str(day+timedelta(days=1)),
            'conservative_cash_release': str(release)+'T09:30:00-04:00',
            'quotes': quotes, 'spy_close': '100', 'spy_distribution': '0'})
    return {'prices': rows, 'blackouts': [{'symbol': 'UNG', 'decision': str(days[139]), 'exit': str(days[140]),
        'ex_date': str(days[141]), 'reentry': str(days[142])}],
        'distributions': [{'symbol': 'DBA', 'ex_date': str(days[138]), 'record_date': str(days[139]),
            'payable_date': str(days[141]), 'cash_available_session': str(days[142]), 'amount': '.1'}],
        'receipt': {'receipt_sha256': 'synthetic', 'identity': {'data_sha256': uuid.uuid4().hex}, 'split': split.metadata()}}, split


def database_setup(db):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    row = StrategyRow(key='test-c05-'+suffix, name='Synthetic C05', status='backtest', allocation_usd=D(140))
    db.add(row)
    ids = {}
    for symbol in (*replay.SYMBOLS, 'SPY'):
        market = Market(venue_id=venue.id, external_id=suffix+symbol, market_type='equity')
        db.add(market); db.flush()
        instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=suffix+symbol,
            instrument_type='equity', symbol=symbol, currency='USD', contract_multiplier=D(1))
        db.add(instrument); db.flush(); ids[symbol] = instrument.id
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date()-timedelta(days=1)), source_url='synthetic', source_hash='synthetic')
    return row.id, ids, fx


def runtime_fixture(db, monkeypatch):
    source, split = synthetic_source()
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    params = replay.strategy_params(source, {s: ids[s] for s in replay.SYMBOLS}, ids['SPY'], replay.VARIANTS[1])
    bot = CommodityTrend(params)
    runtime = replay.C05Backtester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    return source, split, bot, runtime


def test_shared_ledger_dividends_blackout_and_durable_trial_before_prices(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    observed, commits = [], []
    original = db.commit
    def commit():
        commits.append(len(observed)); original()
    monkeypatch.setattr(db, 'commit', commit)
    result = runtime.run(replay.events(source, bot.params, 10, False, observed), split=split)
    assert commits == [0] and result.orders_rejected == 0
    metrics, trips, fills = replay.finish_metrics(db, result, runtime)
    assert not metrics['open_positions'] and metrics['dividend_income_usd'] > 0
    [income] = metrics['dividend_entitlements']
    assert D(income['cash_amount']) == D(income['quantity_before_ex_open'])*D('.1')
    assert income['cash_available_session'] > income['payable_date'] > income['ex_date']
    assert not income['execution_fill']
    assert metrics['net_usd'] == metrics['execution_ledger_net_usd'] + metrics['dividend_income_usd']
    assert any(f.metadata_['research']['forced_blackout_exit'] for f in fills)
    assert any(f.metadata_['research']['blackout_reentry'] for f in fills)
    assert sum(f.metadata_['research']['terminal_liquidation'] for f in fills) == 5
    detail = replay.diagnostics(bot, source, observed, trips, fills, runtime, False)
    assert detail['blackout']['count'] == 2 and detail['luck']['p_value'] is None
    assert abs(sum(map(D, detail['monthly_marked_net_usd'].values()))-metrics['net_usd']) < D('.0001')
    assert runtime.risk.stale_data_check(bot.ids['GLD'], runtime.now+timedelta(seconds=31))[0] is False


def test_ex_open_purchase_gets_no_dividend(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    source['distributions'][0]['ex_date'] = '2020-07-01'  # first possible purchase after warm-up
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    assert replay.finish_metrics(db, result, runtime)[0]['dividend_income_usd'] == 0


def test_total_return_adapter_never_double_credits_dividends_or_emits_blackout_trades(db, monkeypatch):
    from tradingbot.research import c05_total_return as adjusted
    source, split = synthetic_source()
    source['blackouts'], source['distributions'] = [], []
    for row in source['prices']:
        for quote in row['quotes'].values():
            quote['open'] = quote['close'] = quote['adjusted_close']
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    params = replay.strategy_params(source, {s: ids[s] for s in replay.SYMBOLS}, ids['SPY'], replay.VARIANTS[1])
    bot = adjusted.TotalReturnTrend(params)
    runtime = adjusted.TotalReturnBacktester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    observed = []
    result = runtime.run(adjusted.events(source, params, 10, False, observed), split=split)
    metrics, _, fills = replay.finish_metrics(db, result, runtime)
    assert result.orders_rejected == 0 and fills and not metrics['open_positions']
    assert metrics['dividend_income_usd'] == 0 and not metrics['dividend_entitlements']
    assert metrics['net_usd'] == metrics['execution_ledger_net_usd']
    assert all(f.metadata_['research']['units'] == 'virtual_total_return_equivalent' for f in fills)
    assert all(not f.metadata_['research']['forced_blackout_exit'] for f in fills)
    assert all(e.meta['source'] == 'yahoo_adjusted_total_return_scenario'
               for e in observed if e.meta['symbol'] != 'SPY')


def test_reductions_cannot_fund_same_day_additions_and_delays_keep_frozen_target(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    # GLD is still above its February price after a July drop. Its monthly
    # target increases shares while the other four sleeves must reduce.
    for row in source['prices']:
        quote = row['quotes']['GLD']
        if row['date'] < '2020-03-01':
            price = D(2)
        elif row['date'] >= '2020-07-31':
            price = D(quote['open']) / 2
        else:
            continue
        quote.update(open=str(price), close=str(price), adjusted_close=str(price))
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    metrics, _, fills = replay.finish_metrics(db, result, runtime)
    gld_buys = [f for f in fills if f.instrument_id == bot.ids['GLD'] and f.side == 'buy'
                and f.fill_ts.astimezone(replay.NEW_YORK).date() >= date(2020, 8, 1)]
    assert result.orders_rejected == 0 and not metrics['open_positions']
    assert len(gld_buys) == 1 and gld_buys[0].fill_ts.astimezone(replay.NEW_YORK).date() == date(2020, 8, 5)
    assert any(s['date'] == '2020-08-03' and s.get('symbol') == 'GLD' and 'cash delay' in s['reason'] for s in bot.skips)
    reductions = [f for f in fills if f.side == 'sell' and f.fill_ts.astimezone(replay.NEW_YORK).date() == date(2020, 8, 3)]
    assert len(reductions) == 4
    assert all(f.metadata_['research']['conservative_cash_release'].startswith('2020-08-05') for f in reductions)


def test_final_claim_precedes_feed_and_refusal_never_constructs_prices(db, monkeypatch):
    from tradingbot.backtest import engine
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    observed = []
    def refuse(*args, **kwargs):
        assert not observed
        raise ValueError('synthetic claim refusal')
    monkeypatch.setattr(engine, 'claim_final', refuse)
    with pytest.raises(ValueError, match='claim refusal'):
        runtime.run(replay.events(source, bot.params, 10, True, observed), split=split, final_holdout=True)
    assert not observed


def test_interrupted_training_attempt_remains_durable(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    def interrupted():
        assert db.get(Trial, runtime.last_trial_id).status == 'running'
        raise RuntimeError('synthetic interruption')
        yield
    with pytest.raises(RuntimeError, match='interruption'):
        runtime.run(interrupted(), split=split)
    tid = runtime.last_trial_id
    db.rollback()
    assert db.get(Trial, tid).status == 'running'


def test_family_final_guard_survives_changed_source_identity(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    from tradingbot.backtest.holdout import register_split
    register_split(db, split)
    row = db.get(StrategyRow, runtime.strategy_id)
    row.config = {'candidate': 'C05-amendment21'}
    trial = Trial(strategy_id=row.id, mode='backtest', status='failed', final_holdout=True,
        strategy_version=uuid.uuid4().hex*2, dataset_key=split.dataset_key, holdout_start=split.holdout_start)
    db.add(trial); db.commit()
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    with pytest.raises(ValueError, match='family final already consumed'):
        replay.run_variant(db, source, replay.VARIANTS[1], 10, final=True)
    # A real final may predate this rolled-back synthetic fixture. The family
    # guard must cite that earliest consumed attempt, never the latest fixture.
    earliest = db.scalar(select(Trial.id).join(StrategyRow, Trial.strategy_id == StrategyRow.id).where(
        Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C05-amendment21').order_by(Trial.id))
    assert db.scalar(select(Incident).where(Incident.details['first_trial_id'].astext == str(earliest))) is not None
