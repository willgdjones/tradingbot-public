"""Synthetic C08 causality, flat-state and blackout contracts."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit, register_split, strategy_identity
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Incident, Instrument, Market, Strategy as StrategyRow, Trial, Venue
import tradingbot.research.c08_inventory as replay
from tradingbot.research.turn_of_month import scenario_quote
from tradingbot.strategy.c08_inventory import InventoryScarcity


def parameters():
    return {'uso_id': 1, 'threshold': '0', 'target_weight': '.95', 'slot_usd': '140',
            'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001',
            'blackouts': [{'decision': '2020-04-27', 'exit': '2020-04-28', 'reentry': '2020-04-30'}]}


def report(current='90', release='2020-04-22', observation='2020-04-17', available='2020-04-23T00:00:00-04:00'):
    return {'key': 'release-' + observation, 'commercial_current': current, 'commercial_year_ago': '100',
            'release_date': release, 'observation_date': observation, 'available_at': available}


class Context:
    def __init__(self):
        self.quantity, self.cash, self.equity = D(0), D(140), D(140)
        self.ref = SimpleNamespace(bid=D('9.99'), ask=D('10.01'))
    def position(self, _): return self.quantity
    def snapshot(self, _): return self.ref
    def marked_equity(self): return self.equity
    def available_cash(self, _): return self.cash


def setup():
    bot, ctx = InventoryScarcity(parameters()), Context()
    bot.on_start(ctx)
    return bot, ctx


def event(day, releases=(), *, phase='open', terminal=False):
    stamp = datetime.fromisoformat(day + ('T09:30:00-04:00' if phase == 'open' else 'T16:00:00-04:00'))
    return scenario_quote(1, stamp, D(10), 10, phase=phase, releases=list(releases), terminal_open=terminal)


def test_weekly_long_state_retains_quantity_and_threshold_is_strict():
    bot, ctx = setup()
    [order] = bot.on_event(ctx, event('2020-04-23', [report()]))
    assert order.side == 'buy' and order.size * ctx.ref.ask <= D(133)
    ctx.quantity = order.size
    assert bot.on_event(ctx, event('2020-04-24')) == []
    ctx.equity = D(200)
    assert bot.on_event(ctx, event('2020-04-27')) == []
    equal, empty = setup()
    assert equal.on_event(empty, event('2020-04-23', [report('100')])) == []


def test_same_publication_selects_newest_observation_without_old_overwrite():
    bot, ctx = setup()
    newer = report('110', '2020-06-29', '2020-06-26', '2020-06-30T00:00:00-04:00')
    older = report('80', '2020-06-29', '2020-06-19', '2020-06-30T00:00:00-04:00')
    assert bot.on_event(ctx, event('2020-06-30', [newer, older])) == []
    assert bot.latest['observation_date'] == '2020-06-26'
    assert bot.on_event(ctx, event('2020-07-01', [older])) == []
    assert len(bot.skips) == 1


@pytest.mark.parametrize('bad', [
    report(release='2020-04-23'), report(available='2020-04-23T10:00:00-04:00'),
    report(current='NaN'), report(current='0'), report(observation='2020-04-22'),
])
def test_unavailable_or_invalid_release_is_refused(bad):
    bot, ctx = setup()
    with pytest.raises(ValueError):
        bot.on_event(ctx, event('2020-04-23', [bad]))


def test_fourteen_complete_calendar_days_then_next_session_cash():
    bot, ctx = setup()
    bot.on_event(ctx, event('2020-06-04', [report('90', '2020-06-03', '2020-05-29', '2020-06-04T00:00:00-04:00')]))
    ctx.quantity = D(10)
    assert bot.on_event(ctx, event('2020-06-17')) == []
    [exit_] = bot.on_event(ctx, event('2020-06-18'))
    assert exit_.side == 'sell' and exit_.reason == 'C08 stale inventory exit'


def test_blackout_exits_after_decision_stays_flat_and_reenters_from_fresh_equity():
    bot, ctx = setup()
    bot.on_event(ctx, event('2020-04-23', [report()]))
    ctx.quantity = D(10)
    bot.on_event(ctx, event('2020-04-27', phase='close'))
    [exit_] = bot.on_event(ctx, event('2020-04-28'))
    assert exit_.reason == 'C08 forced blackout exit' and exit_.size == 10
    ctx.quantity = D(0)
    assert bot.on_event(ctx, event('2020-04-29')) == []
    ctx.equity, ctx.cash = D(100), D(100)
    [entry] = bot.on_event(ctx, event('2020-04-30'))
    assert entry.reason == 'C08 blackout reentry' and entry.size * ctx.ref.ask <= 95


def test_failed_forced_exit_cannot_continue_into_action_and_requires_decision():
    bot, ctx = setup()
    ctx.quantity = D(10)
    with pytest.raises(ValueError, match='causal blackout'):
        bot.on_event(ctx, event('2020-04-28'))
    with pytest.raises(ValueError, match='forced exit failed'):
        bot.on_event(ctx, event('2020-04-28', phase='close'))
    with pytest.raises(ValueError, match='causal blackout'):
        bot.on_event(ctx, event('2020-04-29'))


def test_cash_delay_keeps_original_target_and_terminal_never_opens():
    bot, ctx = setup()
    ctx.cash = D(0)
    assert bot.on_event(ctx, event('2020-04-23', [report()])) == []
    ctx.equity, ctx.cash = D(200), D(200)
    [entry] = bot.on_event(ctx, event('2020-04-24'))
    assert entry.size * ctx.ref.ask <= 133
    ctx.quantity = entry.size
    [exit_] = bot.on_event(ctx, event('2020-04-27', terminal=True))
    assert exit_.reason == 'C08 terminal liquidation'
    flat, ctx = setup()
    assert flat.on_event(ctx, event('2020-04-23', [report()], terminal=True)) == []


@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def synthetic_source():
    split = HoldoutSplit('test-c08-' + uuid.uuid4().hex, datetime(2020, 1, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC))
    rows = []
    for day, price in [('2020-04-23', '10'), ('2020-04-24', '10'), ('2020-04-27', '11'),
                       ('2020-04-28', '11'), ('2020-04-29', '88'), ('2020-04-30', '90'),
                       ('2020-05-01', '91'), ('2020-05-04', '93')]:
        d = date.fromisoformat(day)
        rows.append({'date': day, 'open': price, 'close': price,
            'opens_at': day + 'T09:30:00-04:00', 'closes_at': day + 'T16:00:00-04:00',
            'scheduled_t1': str(d + timedelta(days=1)), 'completed_settlement': str(d + timedelta(days=1)),
            'conservative_cash_release': str(d + timedelta(days=2)) + 'T09:30:00-04:00',
            'spy_close': '100', 'spy_distribution': '0',
            'uso_split_continuous_close': str(D(price) * (8 if day < '2020-04-29' else 1))})
    return {'prices': rows, 'releases': [report()], 'blackouts': parameters()['blackouts'],
            'exposure_regimes': [{'name': 'fixture', 'start': '2020-01-01', 'end': '2021-01-01'}],
            'receipt': {'receipt_sha256': 'synthetic', 'identity': {'data_sha256': uuid.uuid4().hex}, 'split': split.metadata()}}, split


def database_setup(db):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    row = StrategyRow(key='test-c08-' + suffix, name='Synthetic C08', status='backtest', allocation_usd=D(140))
    db.add(row)
    ids = []
    for symbol in ('USO', 'SPY'):
        market = Market(venue_id=venue.id, external_id=suffix + symbol, market_type='equity')
        db.add(market); db.flush()
        instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=suffix + symbol,
            instrument_type='equity', symbol=symbol, currency='USD', contract_multiplier=D(1))
        db.add(instrument); db.flush(); ids.append(instrument.id)
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date() - timedelta(days=1)),
                         source_url='synthetic', source_hash='synthetic')
    return row.id, ids, fx


def runtime_fixture(db, monkeypatch):
    source, split = synthetic_source()
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    params = replay.strategy_params(source, *ids, '0')
    bot = InventoryScarcity(params)
    runtime = replay.C08Backtester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    return source, split, bot, runtime


def test_shared_ledger_cash_blackout_costs_and_durable_training_before_feed(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    observed, commits = [], []
    original_commit = db.commit
    def commit():
        commits.append(len(observed))
        original_commit()
    monkeypatch.setattr(db, 'commit', commit)
    result = runtime.run(replay.events(source, bot.params, 10, False, observed), split=split)
    assert commits == [0]
    assert result.fills == 4 and result.orders_rejected == 0
    metrics, trips, fills = replay.finish_metrics(db, result, runtime, expected_trips=2)
    assert metrics['net_usd'] > 0 and metrics['fees_usd'] == D('.08')
    assert fills[1].metadata_['research']['forced_blackout_exit']
    assert fills[2].metadata_['research']['blackout_reentry']
    assert fills[2].fill_ts.astimezone(replay.NEW_YORK).date() == date(2020, 4, 30)
    assert fills[-1].metadata_['research']['terminal_liquidation']
    details = replay.diagnostics(bot, source, observed, trips, fills, runtime, False)
    assert details['blackout']['count'] == 2
    assert D(details['blackout']['forced_exit_cost']['fees_usd']) == D('.03')
    assert D(details['blackout']['forced_exit_cost']['adverse_reference_cost_usd']) > 0
    assert details['luck']['p_value'] is None
    assert abs(sum(map(D, details['monthly_marked_net_usd'].values())) - metrics['net_usd']) < D('.00001')
    assert runtime.risk.stale_data_check(bot.params['uso_id'], fills[-1].fill_ts + timedelta(seconds=31))[0] is False


def test_final_admission_failure_never_iterates_feed(db, monkeypatch):
    from tradingbot.backtest import engine
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    observed = []
    def refused(*args, **kwargs):
        assert not observed
        raise ValueError('synthetic final refusal')
    monkeypatch.setattr(engine, 'claim_final', refused)
    with pytest.raises(ValueError, match='final refusal'):
        runtime.run(replay.events(source, bot.params, 10, True, observed), split=split, final_holdout=True)
    assert not observed


def test_interrupted_training_attempt_remains_after_caller_rollback(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    def interrupted():
        assert db.get(Trial, runtime.last_trial_id).status == 'running'
        raise RuntimeError('synthetic interrupted feed')
        yield
    with pytest.raises(RuntimeError, match='interrupted feed'):
        runtime.run(interrupted(), split=split)
    trial_id = runtime.last_trial_id
    db.rollback()
    assert db.get(Trial, trial_id).status == 'running'  # Durable attempt survives; no replay allowed.


def test_partition_local_publication_warmup_and_same_version(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    # Intraday cutoff equals April23 12:00 UTC, after the report became known.
    boundary = HoldoutSplit('test-cutoff', datetime(2020, 4, 22, 19, 12, tzinfo=UTC), datetime(2020, 4, 23, 19, 12, tzinfo=UTC))
    assert boundary.holdout_start == datetime(2020, 4, 23, 12, tzinfo=UTC)
    monkeypatch.setattr(replay, 'split_for', lambda _: boundary)
    final_feed = list(replay.events(source, bot.params, 10, True, []))
    assert all(not event.meta.get('releases') for event in final_feed)
    assert final_feed[0].meta['terminal_open']
    identity = strategy_identity(runtime.version_strategy, type(runtime),
        {'runtime': runtime.version_context, 'run': {'bp': 10}}, (type(runtime.ledger), type(runtime.risk)))[0]
    second = replay.C08Backtester(db, strategy=InventoryScarcity(bot.params), strategy_id=runtime.strategy_id, source=source, fx=runtime.fx)
    assert identity == strategy_identity(second.version_strategy, type(second),
        {'runtime': second.version_context, 'run': {'bp': 10}}, (type(second.ledger), type(second.risk)))[0]


def test_loss_limits_can_reject_forced_exit_and_stop_before_conversion(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    row = next(r for r in source['prices'] if r['date'] == '2020-04-28')
    row['open'] = row['close'] = '1'
    with pytest.raises(ValueError, match='forced exit failed'):
        runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    assert runtime.killed and runtime.daily_halted
    assert runtime.positions[bot.params['uso_id']][0] > 0
    assert runtime.now.astimezone(replay.NEW_YORK).date() == date(2020, 4, 28)
    assert db.get(Trial, runtime.last_trial_id).status == 'failed'


def test_changed_source_or_version_cannot_recycle_family_final(db, monkeypatch):
    source, split = synthetic_source()
    prior = StrategyRow(key='test-c08-prior-' + uuid.uuid4().hex, name='Synthetic prior C08 final',
        status='backtest', allocation_usd=140, config={'candidate': 'C08-amendment21'})
    db.add(prior); db.flush()
    register_split(db, split)
    trial = Trial(strategy_id=prior.id, mode='backtest', final_holdout=True, status='running',
                  strategy_version=uuid.uuid4().hex, params={}, dataset_key=split.dataset_key,
                  holdout_start=split.holdout_start)
    db.add(trial); db.flush()
    # This database may already contain the genuine consumed C08 final. The
    # synthetic attempt must be refused against the earliest family receipt,
    # without hiding, modifying or replaying that real evidence.
    first_id = db.scalar(select(Trial.id).join(StrategyRow).where(
        Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C08-amendment21'
    ).order_by(Trial.id))
    before = set(db.scalars(select(Incident.id)))
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    def forbidden(*args, **kwargs):
        raise AssertionError('reused final must not construct source events')
    monkeypatch.setattr(replay, 'events', forbidden)
    with pytest.raises(ValueError, match='already consumed'):
        replay.run_variant(db, source, '-0.05', 10, final=True, expected_version='different')
    incident = db.scalar(select(Incident).where(Incident.id.not_in(before),
        Incident.details['first_trial_id'].as_integer() == first_id))
    assert incident and incident.details['kind'] == 'holdout_reuse'


def test_failed_runner_retains_partial_fees_marks_and_unresolved_position(db, monkeypatch):
    source, split = synthetic_source()
    _, ids, fx = database_setup(db)
    source['prices'][3]['open'] = source['prices'][3]['close'] = '1'
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    monkeypatch.setattr(replay, 'ReferenceFX', lambda _: fx)
    venue_id = db.scalar(select(Venue.id).where(Venue.key == 'alpaca'))
    monkeypatch.setattr(replay, 'instrument_for', lambda s, symbol: (ids[0 if symbol == 'USO' else 1], venue_id))
    result = replay.run_variant(db, source, '0', 10)
    assert result['status'] == 'failed' and result['metrics']['partial_replay']
    assert result['metrics']['open_positions']
    assert D(result['metrics']['fees_usd']) > 0
    assert D(result['metrics']['max_marked_drawdown_usd']) > 50
    db.rollback()
    trial = db.get(Trial, result['trial_id'])
    assert trial.status == 'failed' and trial.metrics == result['metrics']
    with pytest.raises(ValueError, match='already attempted'):
        replay.run_variant(db, source, '0', 10)
