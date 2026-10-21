"""Synthetic observations only; no real C02 strategy outcomes during development."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Instrument, Market, Strategy as StrategyRow, Trial, Venue
from tradingbot.research import c02_sector_momentum as replay
from tradingbot.strategy.c02_sector_momentum import SectorMomentum


@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def _month_sessions(start=date(2015, 1, 1), stop=date(2017, 1, 1)):
    weekdays, day = [], start
    while day < stop:
        if day.weekday() < 5:
            weekdays.append(day)
        day += timedelta(days=1)
    by_month = {}
    for d in weekdays:
        by_month.setdefault((d.year, d.month), []).append(d)
    picked = []
    for key in sorted(by_month):
        m = by_month[key]
        picked += [m[1], m[len(m) // 3], m[2 * len(m) // 3], m[-2]]  # four spread sessions
    return sorted(picked)


def synthetic_source():
    days = _month_sessions()
    split = HoldoutSplit('test-c02-' + uuid.uuid4().hex, datetime(2015, 1, 1, tzinfo=UTC),
                         datetime(2017, 1, 1, tzinfo=UTC))
    rate = {'XLK': D('.5'), 'XLE': D('.3'), 'XLF': D('.2')}
    rows = []
    for index, day in enumerate(days):
        quotes = {}
        for symbol in replay.SYMBOLS:
            price = D(10) + rate.get(symbol, D(0)) * index
            div = '.25' if symbol == 'XLK' and index == 38 else '0'
            quotes[symbol] = {'open': str(price), 'close': str(price), 'signal_distribution': div,
                              'split_ratio': '1', 'in_kind_signal_value': '0'}
        settle = days[index + 1] if index + 1 < len(days) else day + timedelta(days=2)
        release = days[index + 2] if index + 2 < len(days) else day + timedelta(days=4)
        rows.append({'date': str(day), 'opens_at': str(day) + 'T09:30:00-05:00',
            'closes_at': str(day) + 'T16:00:00-05:00', 'scheduled_t1': str(settle),
            'completed_settlement': str(settle), 'conservative_cash_release': str(release) + 'T09:30:00-05:00',
            'quotes': quotes, 'spy_close': str(D(100) + D(index) / 10), 'spy_distribution': '0'})
    # Four sessions/month. Month 11 is indices 40..43: XLK ex-date 38 (cash at
    # 40); XLF blacked out mid-cycle (decided close 40, flat at the 41 open,
    # re-enterable from the 43 open inside the same hold window once the forced
    # sale's T+1 proceeds have settled).
    distributions = [{'symbol': 'XLK', 'ex_date': str(days[38]), 'record_date': str(days[39]),
        'pay_date': str(days[39]), 'cash_endpoint': str(days[39]),
        'cash_release': str(days[40]) + 'T09:30:00-05:00', 'amount': '.25'}]
    blackouts = [{'symbol': 'XLF', 'kind': 'split', 'decision': str(days[40]), 'exit': str(days[41]),
        'ex_date': str(days[41]), 'reentry': str(days[43])}]
    return {'prices': rows, 'blackouts': blackouts, 'distributions': distributions,
        'receipt': {'receipt_sha256': 'synthetic', 'identity': {'data_sha256': uuid.uuid4().hex},
                    'split': split.metadata()}}, split


def database_setup(db):
    suffix = uuid.uuid4().hex
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    row = StrategyRow(key='test-c02-' + suffix, name='Synthetic C02', status='backtest', allocation_usd=D(140))
    db.add(row)
    ids = {}
    for symbol in (*replay.SYMBOLS, 'SPY'):
        market = Market(venue_id=venue.id, external_id=suffix + symbol, market_type='equity')
        db.add(market); db.flush()
        instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=suffix + symbol,
            instrument_type='equity', symbol=symbol, currency='USD', contract_multiplier=D(1))
        db.add(instrument); db.flush(); ids[symbol] = instrument.id
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date() - timedelta(days=1)),
                         source_url='synthetic', source_hash='synthetic')
    return row.id, ids, fx


def runtime_fixture(db, monkeypatch, variant='ret6'):
    source, split = synthetic_source()
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    params = replay.strategy_params(source, {s: ids[s] for s in replay.SYMBOLS}, ids['SPY'], variant)
    bot = SectorMomentum(params)
    runtime = replay.C02Backtester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    return source, split, bot, runtime


def test_monthly_cycle_maps_decision_to_next_and_following_first_open():
    rows = [{'date': d} for d in ('2020-01-02', '2020-01-31', '2020-02-03', '2020-02-28',
                                  '2020-03-02', '2020-03-31', '2020-04-01')]
    cycles = replay.monthly_cycles(rows)
    assert cycles['2020-01-31'] == {'entry': '2020-02-03', 'exit': '2020-03-02'}
    assert cycles['2020-03-31'] == {'entry': '2020-04-01', 'exit': None}


def test_monthly_shared_ledger_blackout_dividends_and_durable_admission(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    observed, commits = [], []
    original = db.commit
    monkeypatch.setattr(db, 'commit', lambda: (commits.append(len(observed)), original())[1])
    result = runtime.run(replay.events(source, bot.params, 10, False, observed), split=split)
    assert commits == [0] and result.orders_rejected == 0
    metrics, trips, fills = replay.finish_metrics(db, result, runtime)
    assert not metrics['open_positions']                 # terminal liquidation flattens
    assert metrics['dividend_income_usd'] > 0 and len(trips) > 0
    # Momentum consistently holds XLK, XLE, XLF (the three rising names).
    held = {bot.by_id[f.instrument_id] for f in fills}
    assert {'XLK', 'XLE', 'XLF'} <= held
    assert any(f.metadata_['research']['forced_blackout_exit'] for f in fills)
    assert any(f.metadata_['research']['blackout_reentry'] for f in fills)
    assert any(f.metadata_['research']['terminal_liquidation'] for f in fills)
    # A stayer is held across a rebalance: XLK is bought more than once without a
    # full sell in between (no weekly-style churn).
    details = replay.diagnostics(bot, source, observed, trips, fills, runtime, False)
    assert details['blackout']['count'] >= 1 and details['luck']['p_value'] is None
    assert abs(sum(map(D, details['monthly_marked_net_usd'].values())) - sum((t.net_pnl for t in trips), D(0))) < D('.01')
    [entitlement] = metrics['dividend_entitlements']
    assert entitlement['symbol'] == 'XLK' and not entitlement['execution_fill']


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


def test_interrupted_training_keeps_the_admitted_running_trial(db, monkeypatch):
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


def test_run_variant_failed_attempt_preserves_partial_evidence(db, monkeypatch):
    source, split = synthetic_source()
    monkeypatch.setattr(replay, 'split_for', lambda _: split)
    monkeypatch.setattr(replay, 'require_committed', lambda: 'synthetic')
    # Force a held-across-blackout failure: blackout a perpetually-held name but
    # withhold its causal prior-close decision by moving the decision off-calendar.
    source['blackouts'][0]['symbol'] = 'XLK'
    source['blackouts'][0]['decision'] = '1999-01-01'
    result = replay.run_variant(db, source, 'ret6', 10)
    assert result['status'] == 'failed' and not result['final_holdout']
    assert db.get(Trial, result['trial_id']).status == 'failed'
    assert result['metrics']['partial_replay'] and not result['metrics']['complete_execution']
