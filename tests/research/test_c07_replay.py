"""Synthetic observations only; no C07 strategy outcomes during development."""
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
from tradingbot.research import c07_replay as replay
from tradingbot.strategy.c07_sector_reversal import SectorReversal


@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def synthetic_source():
    split = HoldoutSplit('test-c07-'+uuid.uuid4().hex, datetime(2020, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC))
    days, day = [], date(2020, 1, 6)
    while len(days) < 40:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    rows = []
    for index, day in enumerate(days):
        quotes = {}
        for symbol in replay.SYMBOLS:
            raw = D(10) if symbol in ('XLB', 'XLE', 'XLF') else D(10)+D(index)/20
            if symbol == 'XLF' and index >= 14:
                raw /= 2
            if symbol == 'XLB' and index >= 12:
                raw -= D('.1')
            if symbol == 'XLE' and index >= 10:
                raw -= D('.2')
            div = '.1' if symbol == 'XLB' and index == 12 else ('.2' if symbol == 'XLE' and index == 10 else '0')
            quotes[symbol] = {'open': str(raw), 'close': str(raw), 'signal_distribution': div,
                'split_ratio': '2' if symbol == 'XLF' and index == 14 else '1', 'in_kind_signal_value': '0'}
        settle = days[index+1] if index+1 < len(days) else day+timedelta(days=3)
        release = days[index+2] if index+2 < len(days) else day+timedelta(days=4)
        rows.append({'date': str(day), 'opens_at': str(day)+'T09:30:00-05:00',
            'closes_at': str(day)+'T16:00:00-05:00', 'scheduled_t1': str(settle),
            'completed_settlement': str(settle), 'conservative_cash_release': str(release)+'T09:30:00-05:00',
            'quotes': quotes, 'spy_close': str(D(100)+D(index)/10), 'spy_distribution': '0'})
    distributions = [{'symbol': symbol, 'ex_date': str(days[index]), 'record_date': str(days[index+1]),
        'pay_date': str(days[14]), 'cash_endpoint': str(days[14]),
        'cash_release': str(days[15])+'T09:30:00-05:00', 'amount': amount}
        for symbol, index, amount in [('XLB', 12, '.1'), ('XLE', 10, '.2')]]
    return {'prices': rows, 'blackouts': [{'symbol': 'XLF', 'decision': str(days[12]), 'exit': str(days[13]),
        'ex_date': str(days[14]), 'reentry': str(days[16])}], 'distributions': distributions,
        'receipt': {'receipt_sha256': 'synthetic', 'identity': {'data_sha256': uuid.uuid4().hex}, 'split': split.metadata()}}, split


def database_setup(db):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    row = StrategyRow(key='test-c07-'+suffix, name='Synthetic C07', status='backtest', allocation_usd=D(140))
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


def runtime_fixture(db, monkeypatch, variant=None):
    source, split = synthetic_source()
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    params = replay.strategy_params(source, {s: ids[s] for s in replay.SYMBOLS}, ids['SPY'], variant or replay.VARIANTS[0])
    bot = SectorReversal(params)
    runtime = replay.C07Backtester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    return source, split, bot, runtime


def test_calendar_uses_actual_first_sessions_in_ny_weeks():
    rows = [{'date': day} for day in ('2020-01-02', '2020-01-03', '2020-01-06', '2020-01-10',
                                     '2020-01-13', '2020-01-17', '2020-01-21', '2020-01-24')]
    cycles = replay.weekly_cycles(rows)
    assert cycles['2020-01-10'] == {'entry': '2020-01-13', 'exit': '2020-01-21'}
    assert cycles['2020-01-17'] == {'entry': '2020-01-21', 'exit': None}


def test_weekly_shared_ledger_cash_blackout_and_durable_admission(db, monkeypatch):
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
    assert income['symbol'] == 'XLB'  # XLE was bought on ex-date: no entitlement.
    assert D(income['cash_amount']) == D(income['quantity_before_ex_open'])*D('.1')
    assert income['cash_release'][:10] > income['pay_date'] > income['ex_date']
    assert not income['execution_fill']
    assert any(f.metadata_['research']['forced_blackout_exit'] for f in fills)
    assert any(f.metadata_['research']['blackout_reentry'] for f in fills)
    assert not any(f.metadata_['research']['terminal_liquidation'] for f in fills)
    for fill in fills:
        cycle = fill.metadata_['research']['weekly_cycle']
        day = str(fill.fill_ts.astimezone(replay.NEW_YORK).date())
        if fill.side == 'buy':
            assert cycle['initial_entry_session'] <= day < cycle['original_scheduled_exit']
        elif not fill.metadata_['research']['forced_blackout_exit']:
            assert day == cycle['original_scheduled_exit']
    details = replay.diagnostics(bot, source, observed, trips, fills, runtime, False)
    assert details['blackout']['count'] == 3 and details['luck']['p_value'] is None
    assert abs(sum(map(D, details['weekly_marked_net_usd'].values())) - metrics['net_usd']) < D('.0001')
    assert runtime.risk.stale_data_check(bot.ids['XLB'], runtime.now+timedelta(seconds=31))[0] is False


def test_repeated_names_sell_then_wait_for_settled_cash_without_extending_exit(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    # Isolate settlement: no cash from a prior blackout sale or dividend.
    source['blackouts'].clear()
    source['distributions'].clear()
    for row in source['prices']:
        for symbol in ('XLB', 'XLE', 'XLF'):
            row['quotes'][symbol].update(open='10', close='10', split_ratio='1', signal_distribution='0')
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    _, _, fills = replay.finish_metrics(db, result, runtime)
    xlb = [f for f in fills if f.instrument_id == bot.ids['XLB']]
    assert any(f.side == 'sell' and str(f.fill_ts.astimezone(replay.NEW_YORK).date()) == '2020-01-27' for f in xlb)
    later = [f for f in xlb if f.side == 'buy' and f.metadata_['research']['weekly_cycle']['initial_entry_session'] == '2020-01-27']
    assert later and all(str(f.fill_ts.astimezone(replay.NEW_YORK).date()) == '2020-01-29' for f in later)
    assert all(f.metadata_['research']['weekly_cycle']['original_scheduled_exit'] == '2020-02-03' for f in later)


def test_undated_cash_availability_stays_an_unspendable_receivable(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    source['distributions'][0]['cash_release'] = None
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    metrics, _, _ = replay.finish_metrics(db, result, runtime)
    assert metrics['income_without_in_sample_availability_usd'] == metrics['dividend_income_usd'] > 0
    assert metrics['ending_unsettled_cash_and_receivables_usd'] >= metrics['dividend_income_usd']


def test_risk_vetoed_blackout_exit_fails_before_unresolved_conversion(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch, replay.VARIANTS[2])
    source['blackouts'][0]['symbol'] = 'XLB'
    for row in source['prices'][11:]:
        row['quotes']['XLB'].update(open='2', close='2')
    with pytest.raises(ValueError, match='held across corporate-action blackout'):
        runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    assert runtime.killed and runtime.halt_events
    assert runtime.now.date() == date(2020, 1, 23)


def test_failed_attempt_keeps_partial_regimes_fills_and_risk_evidence(db, monkeypatch):
    source, split = synthetic_source()
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    source['blackouts'][0]['symbol'] = 'XLB'
    for row in source['prices'][11:]:
        row['quotes']['XLB'].update(open='2', close='2')
    result = replay.run_variant(db, source, replay.VARIANTS[2], 10)
    assert result['status'] == 'failed' and not result['final_holdout']
    metrics = result['metrics']
    assert metrics['partial_replay'] and not metrics['complete_execution']
    assert 'partial_measurement_error' not in metrics
    assert metrics['fills'] > 0 and metrics['rejected_orders'] > 0
    assert metrics['calendar_regimes']['2020-2021']['covered']
    assert metrics['blackout']['processed_count'] == 1
    assert metrics['halt_events'] and metrics['open_positions']
    assert db.get(Trial, result['trial_id']).status == 'failed'


def test_final_claim_precedes_feed_and_refusal_consumes_no_prices(db, monkeypatch):
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


def test_interrupted_training_keeps_the_admitted_trial(db, monkeypatch):
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


def test_family_final_guard_rejects_changed_source_identity(db, monkeypatch):
    from tradingbot.backtest.holdout import register_split
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    register_split(db, split)
    row = db.get(StrategyRow, runtime.strategy_id)
    row.config = {'candidate': 'C07-amendment21'}
    trial = Trial(strategy_id=row.id, mode='backtest', status='failed', final_holdout=True,
        strategy_version=uuid.uuid4().hex*2, dataset_key=split.dataset_key, holdout_start=split.holdout_start)
    db.add(trial); db.commit()
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    with pytest.raises(ValueError, match='family final already consumed'):
        replay.run_variant(db, source, replay.VARIANTS[1], 10, final=True)
    earliest = db.scalar(select(Trial.id).join(StrategyRow, Trial.strategy_id == StrategyRow.id).where(
        Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C07-amendment21').order_by(Trial.id))
    assert db.scalar(select(Incident).where(Incident.details['first_trial_id'].astext == str(earliest))) is not None


@pytest.mark.parametrize('failed', [False, True])
def test_independent_stored_audit_handles_multiple_same_day_incomes_and_failed_inventory(db, monkeypatch, failed):
    from tradingbot.research import c07_result_audit as audit
    source, split = synthetic_source()
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    monkeypatch.setattr(audit, 'split_for', lambda _: split)
    monkeypatch.setattr(audit, 'SOURCE_RECEIPT', 'synthetic')
    # Both positions are owned before this ex-open: a date -> single-row map
    # would silently drop an entitlement and fail independent reconciliation.
    source['distributions'][1]['ex_date'] = source['distributions'][0]['ex_date']
    if failed:
        source['blackouts'][0]['symbol'] = 'XLB'
        for row in source['prices'][11:]:
            row['quotes']['XLB'].update(open='2', close='2')
    result = replay.run_variant(db, source, replay.VARIANTS[2] if failed else replay.VARIANTS[0], 10)
    receipt = audit.audit_run(db, source, result)
    assert receipt['audit_status'] == 'PASS'
    assert receipt['execution_status'] == ('failed' if failed else 'complete')
    assert receipt['cash_entitlements_checked'] == (1 if failed else 2)
    assert receipt['complete_execution'] is not failed
