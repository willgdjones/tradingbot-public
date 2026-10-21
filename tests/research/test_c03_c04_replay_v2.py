"""Synthetic C04 execution, cash, variance and final-admission checks."""
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
import tradingbot.research.c03_c04_replay_v2 as replay
from tradingbot.strategy.c03_c04_monthly import variance_weight
from tradingbot.strategy.c03_c04_monthly_v2 import InverseVarianceV2 as InverseVariance
from tradingbot.strategy.interface import MarketEvent

@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def database_setup(db):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    row = StrategyRow(key='test-c04-'+suffix, name='Synthetic C04', status='backtest', allocation_usd=D(140))
    db.add(row)
    ids = {}
    for symbol in replay.SYMBOLS:
        market = Market(venue_id=venue.id, external_id=suffix+symbol, market_type='equity')
        db.add(market); db.flush()
        instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=suffix+symbol,
            instrument_type='equity', symbol=symbol, currency='USD', contract_multiplier=D(1))
        db.add(instrument); db.flush(); ids[symbol] = instrument.id
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date()-timedelta(days=1)), source_url='synthetic', source_hash='synthetic')
    return row.id, ids, fx


def synthetic_source():
    split = HoldoutSplit('test-c04-'+uuid.uuid4().hex, datetime(2020, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC))
    days, day = [], date(2020, 1, 2)
    while len(days) < 150:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    rows = []
    for index, day in enumerate(days):
        price = D(100) + D(index)/100 + D(index%2)/10
        if index >= 100:
            price -= D('.1')
        release = days[index+2] if index+2 < len(days) else day+timedelta(days=4)
        rows.append({'date': str(day), 'opens_at': str(day)+'T09:30:00-04:00',
            'closes_at': str(day)+'T16:00:00-04:00', 'scheduled_t1': str(day+timedelta(days=1)),
            'completed_settlement': str(day+timedelta(days=1)),
            'conservative_cash_release': str(release)+'T09:30:00-04:00',
            'quotes': {'SPY': {'open': str(price), 'close': str(price),
                'distribution': '.1' if index == 100 else '0'}}})
    return {'prices': rows, 'blackouts': [],
        'distributions': [{'symbol': 'SPY', 'ex_date': str(days[100]), 'record_date': str(days[101]),
            'scheduled_pay_date': str(days[105]), 'cash_available_session': str(days[106]), 'amount': '.1'}],
        'receipt': {'receipt_sha256': 'synthetic', 'identity': {'data_sha256': uuid.uuid4().hex}, 'split': split.metadata()}}, split


def runtime_fixture(db, monkeypatch):
    source, split = synthetic_source()
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    params = replay.strategy_params(source, ids, ids['SPY'], replay.VARIANTS[0])
    bot = InverseVariance(params)
    runtime = replay.C04Backtester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    return source, split, bot, runtime


def test_sample_variance_factor_cash_cap_and_observation_minimum():
    returns = [D('.1'), D('-.1')] * 8
    weight, variance = variance_weight(returns, '0.0225')
    assert variance == D(252)*D('.16')/15
    assert weight == D('.0225')/variance
    assert variance_weight([r/100 for r in returns], '0.01')[0] == D('.95')
    assert variance_weight([D('.01')]*16, '0.04') == (D(0), D(0))
    assert variance_weight(returns[:14], '0.0225') == (D(0), None)
    with pytest.raises(ValueError, match='frozen'):
        variance_weight(returns, '0.03')


def test_shared_ledger_dividend_receivable_and_durable_trial_before_prices(db, monkeypatch):
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
    assert income['cash_available_session'] > income['scheduled_pay_date'] > income['ex_date']
    assert not income['execution_fill']
    assert metrics['net_usd'] == metrics['execution_ledger_net_usd'] + metrics['dividend_income_usd']
    assert sum(f.metadata_['research']['terminal_liquidation'] for f in fills) == 1
    assert all(f.metadata_['research']['source_receipt'] == 'synthetic' for f in fills)
    assert bot.decisions[0]['weight'] == '0' and not bot.decisions[0]['complete_calendar_month']
    assert bot.decisions[1]['complete_calendar_month']
    assert min(f.fill_ts.date() for f in fills) == date(2020, 3, 2)
    detail = replay.diagnostics(bot, source, observed, trips, fills, runtime, False)
    assert detail['luck']['p_value'] is None
    assert abs(sum(map(D, detail['monthly_marked_net_usd'].values()))-metrics['net_usd']) < D('.0001')
    assert runtime.risk.stale_data_check(bot.ids['SPY'], runtime.now+timedelta(seconds=31))[0] is False


def test_missing_first_return_prevents_partial_month_and_cash_delay_keeps_target(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    source['prices'] = [r for r in source['prices'] if r['date'] >= '2020-02-14']
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    assert not bot.decisions[0]['complete_calendar_month']
    assert bot.decisions[0]['observations'] >= 0 and bot.decisions[0]['weight'] == '0'
    assert bot.decisions[1]['complete_calendar_month']
    _, _, fills = replay.finish_metrics(db, result, runtime)
    assert min(f.fill_ts.date() for f in fills) == date(2020, 4, 1)


def test_ex_open_buyer_gets_no_dividend(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    source['distributions'][0]['ex_date'] = '2020-03-02'
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    assert replay.finish_metrics(db, result, runtime)[0]['dividend_income_usd'] == 0


def test_source_checksum_and_fixed_partition_admission():
    source = replay.load_source()
    assert replay.split_for(source).holdout_start == datetime(2020,7,10,14,24,tzinfo=UTC)
    assert len(source['prices']) == 5218 and len(source['distributions']) == 83
    assert set(source['prices'][0]['quotes']['SPY']) == {'open','close','distribution'}


def test_ex_date_distribution_enters_return_once_and_targets_are_frozen(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    ctx = SimpleNamespace(marked_equity=lambda: D(100))
    bot.on_start(ctx)
    def close(day, price, dividend='0'):
        return MarketEvent.quote(bot.ids['SPY'], datetime.fromisoformat(day+'T16:00:00-04:00'),
            mid=D(price), meta={'phase':'close','distribution':dividend})
    bot.on_event(ctx, close('2020-01-30', '100'))
    bot.on_event(ctx, close('2020-01-31', '99', '1'))
    assert bot.daily_returns['2020-01-31'] == 0
    assert bot.targets['SPY'] == 0  # no complete January
    bot.targets, bot.pending, bot.reserve = {'SPY': D(95)}, {'SPY'}, D(5)
    snap = replay.scenario_quote(bot.ids['SPY'], datetime(2020,2,3,14,30,tzinfo=UTC), D(10), 10).as_snapshot()
    cashctx = SimpleNamespace(snapshot=lambda _:snap, position=lambda _:D(0), available_cash=lambda _:D(20))
    assert bot._allocate_buys(cashctx, '2020-02-03')['SPY'] == (D('14.99'), False)
    cashctx.available_cash = lambda _:D(200)
    assert bot._allocate_buys(cashctx, '2020-02-03')['SPY'] == (D(95), True)
    assert bot.targets == {'SPY': D(95)} and bot.reserve == 5

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
    row.config = {'candidate': 'C04-readmission'}
    trial = Trial(strategy_id=row.id, mode='backtest', status='failed', final_holdout=True,
        strategy_version=uuid.uuid4().hex*2, dataset_key=split.dataset_key, holdout_start=split.holdout_start)
    db.add(trial); db.commit()
    first_id = db.scalar(select(Trial.id).join(StrategyRow, Trial.strategy_id == StrategyRow.id).where(
        Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C04-readmission').order_by(Trial.id))
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    with pytest.raises(ValueError, match='family final already consumed'):
        replay.run_variant(db, source, replay.VARIANTS[1], 10, final=True)
    assert db.scalar(select(Incident).where(Incident.details['first_trial_id'].astext == str(first_id))) is not None


def test_buy_capacity_values_all_owned_shares_at_rounded_limit(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    bot.on_start(None)
    iid = bot.ids['SPY']
    snap = replay.scenario_quote(iid, datetime(2020,2,3,14,30,tzinfo=UTC), D('142.16'), 10).as_snapshot()
    held = D('.961008')
    bot.targets, bot.pending, bot.reserve = {'SPY':D(140)}, {'SPY'}, D(10)
    ctx = SimpleNamespace(snapshot=lambda _:snap, position=lambda _:held, available_cash=lambda _:D(100))
    allocation, complete = bot._allocate_buys(ctx,'2020-02-03')['SPY']
    orders = bot._order(snap,iid,(allocation/snap.ask).quantize(D('.000000001'),rounding='ROUND_FLOOR'),'buy','2020-02-03','test')
    [order] = orders
    assert (held+order.size)*order.limit_price <= 140
    original = ((D(140)-held*snap.reference_price)/snap.ask).quantize(D('.000000001'),rounding='ROUND_FLOOR')
    assert (held+original)*order.limit_price > 140
    assert complete and bot.targets['SPY'] == 140


def test_compounded_equity_at_full_slot_generates_no_risk_rejects(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    # A large synthetic distribution leaves spendable cash after the reserve,
    # then the following quiet month restores the full-slot target.
    source['distributions'][0]['amount'] = '10'
    for index,row in enumerate(source['prices']):
        price = D(100)+D(index)/10+D(index%2)/10
        row['quotes']['SPY'].update(open=str(price*D('.995')), close=str(price),
            distribution='10' if index == 100 else '0')
    result = runtime.run(replay.events(source,bot.params,10,False,[]),split=split)
    assert result.orders_rejected == 0
    assert any('rounded limit' in r['reason'] for r in bot.skips)
    assert not replay.finish_metrics(db,result,runtime)[0]['open_positions']
