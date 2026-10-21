from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit, strategy_identity
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Fill, Instrument, Market, Strategy, Venue, Trial, Incident
import tradingbot.research.c06_month_end as c06
from tradingbot.strategy.c06_month_end import MonthEndUnderweight


def source(exit_price='99'):
    dates = ['2026-01-30', '2026-02-25', '2026-02-26', '2026-02-27', '2026-03-02']
    prices = ['100', '100', '90', '90', exit_price]
    rows = []
    for day, price in zip(dates, prices):
        d = date.fromisoformat(day)
        rows.append({'date': day, 'open': price, 'close': price,
            'opens_at': day + 'T14:30:00+00:00', 'closes_at': day + 'T21:00:00+00:00',
            'scheduled_t1': str(d + timedelta(days=1)), 'completed_settlement': str(d + timedelta(days=1)),
            'conservative_cash_release': str(d + timedelta(days=2)) + 'T14:30:00+00:00'})
    return {'SPY': {'prices': rows, 'distributions': []},
            'IEF': {'prices': [{'date': d, 'close': '100'} for d in dates], 'distributions': []}}


@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


def setup(db):
    suffix = uuid.uuid4().hex[:12]
    venue = db.scalar(select(Venue).where(Venue.key == 'alpaca'))
    row = Strategy(key='test-c06-' + suffix, name='Synthetic C06', status='backtest', allocation_usd=D(140))
    db.add(row)
    ids = []
    for symbol in ['SPY', 'IEF']:
        market = Market(venue_id=venue.id, external_id='c06-' + suffix + symbol, market_type='equity')
        db.add(market); db.flush()
        instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id='c06-' + suffix + symbol,
            instrument_type='equity', symbol=symbol, currency='USD', contract_multiplier=D(1))
        db.add(instrument); db.flush(); ids.append(instrument.id)
    fx = SimpleNamespace(at=lambda ts: (D('.75'), ts.date() - timedelta(days=1)),
                         source_url='synthetic', source_hash='synthetic')
    return row.id, ids, fx


def training_split():
    return HoldoutSplit('test-c06-' + uuid.uuid4().hex, datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


def test_shared_ledger_risk_cash_and_reference_evidence(db, monkeypatch):
    sid, ids, fx = setup(db)
    data = source(); split = training_split()
    monkeypatch.setattr(c06, 'split_for', lambda _: split)
    bot = MonthEndUnderweight(c06.strategy_params(data, *ids, '0.600'))
    runtime = c06.C06Backtester(db, strategy=bot, strategy_id=sid, source=data, fx=fx)
    observed = []
    result = runtime.run(c06.events(data, bot.params, 10, False, observed), split=split)
    assert result.fills == 2 and result.orders_rejected == 0
    metrics, trips, fills = c06.finish_metrics(db, result, runtime, expected_trips=1)
    assert metrics['net_usd'] > 0 and metrics['fees_usd'] == D('.04')
    assert fills[0].size * fills[0].price <= 133 and fills[0].size * fills[0].price > 132
    assert fills[1].metadata_['research']['settlement_date'] == '2026-03-03'
    assert fills[1].metadata_['research']['conservative_cash_release'] == '2026-03-04T14:30:00+00:00'
    assert not fills[1].metadata_['research']['terminal_liquidation']  # ordinary scheduled exit
    assert 'amended_yahoo' in fills[0].metadata_['research']['source']
    assert runtime.risk.stale_data_check(ids[0], fills[1].fill_ts + timedelta(seconds=31))[0] is False
    detail = c06.diagnostics(bot, observed, trips, runtime.curve)
    assert detail['window_comparison']['all']['windows'] == 1
    assert D(detail['flow_windows'][0]['market_open_to_open_return']) == D('.1')
    assert detail['luck']['p_value'] is None and not detail['promotion_eligible']


def test_open_gap_trips_unchanged_daily_and_permanent_limits(db, monkeypatch):
    sid, ids, fx = setup(db)
    data = source('30'); split = training_split()
    monkeypatch.setattr(c06, 'split_for', lambda _: split)
    bot = MonthEndUnderweight(c06.strategy_params(data, *ids, '0.600'))
    runtime = c06.C06Backtester(db, strategy=bot, strategy_id=sid, source=data, fx=fx)
    result = runtime.run(c06.events(data, bot.params, 10, False, []), split=split)
    assert runtime.killed and runtime.daily_halted
    assert result.fills == 1 and result.orders_rejected == 1
    assert {e['kind'] for e in runtime.halt_events} == {'per_strategy_kill', 'global_daily_halt'}


def test_feed_excludes_later_close_at_intraday_cutoff(monkeypatch):
    data = source()
    split = HoldoutSplit('test-c06-intraday', datetime(2026, 2, 27, tzinfo=UTC), datetime(2026, 2, 28, 6, tzinfo=UTC))
    assert split.holdout_start == datetime(2026, 2, 27, 21, tzinfo=UTC)
    monkeypatch.setattr(c06, 'split_for', lambda _: split)
    params = c06.strategy_params(data, 1, 2, '0.600')
    feed = list(c06.events(data, params, 10, False, []))
    assert len(feed) == 1 and feed[0].meta['phase'] == 'open' and feed[0].meta['terminal_open']


def test_final_claim_precedes_any_c06_feed_iteration(db, monkeypatch):
    from tradingbot.backtest import engine
    sid, ids, fx = setup(db)
    data = source(); split = training_split()
    bot = MonthEndUnderweight(c06.strategy_params(data, *ids, '0.600'))
    runtime = c06.C06Backtester(db, strategy=bot, strategy_id=sid, source=data, fx=fx)
    observed = []
    def refuse(*args, **kwargs):
        assert observed == []
        raise ValueError('synthetic admission refused')
    monkeypatch.setattr(engine, 'claim_final', refuse)
    with pytest.raises(ValueError, match='admission refused'):
        runtime.run(c06.events(data, bot.params, 10, True, observed), split=split, final_holdout=True)
    assert observed == []


def test_frozen_strategy_identity_does_not_include_partition(db):
    sid, ids, fx = setup(db)
    data = source()
    params = c06.strategy_params(data, *ids, '0.600')
    first = c06.C06Backtester(db, strategy=MonthEndUnderweight(params), strategy_id=sid, source=data, fx=fx)
    second = c06.C06Backtester(db, strategy=MonthEndUnderweight(params), strategy_id=sid, source=data, fx=fx)
    def identity(runtime):
        return strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': {'slippage_bp_per_side': 10}},
            (type(runtime.ledger), type(runtime.risk)))[0]
    assert identity(first) == identity(second)


def test_monthly_block_luck_is_deterministic_and_uses_zero_months():
    monthly = {f'fixture-{i}': D('1') if i % 2 else D('-.5') for i in range(36)}
    first = c06.monthly_luck(monthly, 30)
    assert first == c06.monthly_luck(monthly, 30)
    assert first['months'] == 36 and first['block_months'] == 3
    assert c06.monthly_luck(monthly, 29)['p_value'] is None


def test_calendar_year_marks_keep_prior_year_gains_out_of_exit_year():
    curve = [(datetime(2025, 12, 31, 21, tzinfo=UTC), D(150)),
             (datetime(2026, 1, 2, 14, 30, tzinfo=UTC), D(147)),
             (datetime(2026, 1, 2, 21, tzinfo=UTC), D(148))]
    assert c06.marked_period(curve, 2025, 2025)['marked_net_usd'] == '10'
    result = c06.marked_period(curve, 2026, 2026)
    assert result['marked_net_usd'] == '-2' and result['marked_drawdown']['dollars'] == '3'
    assert not c06.marked_period(curve, 2024, 2024)['covered']


def test_final_version_mismatch_refused_before_feed(db, monkeypatch):
    _, _, fx = setup(db)
    data = source()
    data['receipt'] = {'identity': {'data_sha256': uuid.uuid4().hex}}
    split = training_split()
    monkeypatch.setattr(c06, 'split_for', lambda _: split)
    monkeypatch.setattr(c06, 'require_committed', lambda: 'synthetic')
    monkeypatch.setattr(c06, 'ReferenceFX', lambda _: fx)
    seen = []
    def forbidden(*args):
        seen.append(True)
        raise AssertionError('preflight must not construct the feed')
    monkeypatch.setattr(c06, 'events', forbidden)
    with pytest.raises(ValueError, match='before data consumption'):
        c06.run_variant(db, data, '0.600', 10, final=True, expected_version='wrong')
    assert not seen
    trial = db.scalar(select(Trial).where(Trial.dataset_key == split.dataset_key))
    assert trial.status == 'failed' and not trial.final_holdout


def test_repeated_final_cli_logs_refusal_without_feed(db, monkeypatch):
    data = source()
    digest = uuid.uuid4().hex
    data['receipt'] = {'identity': {'data_sha256': digest}}
    key = f'c06-{digest[:10]}-0.600-10-final'
    row = Strategy(key=key, name='Synthetic prior final', status='backtest', allocation_usd=140)
    db.add(row); db.flush()
    monkeypatch.setattr(c06, 'require_committed', lambda: 'synthetic')
    with pytest.raises(ValueError, match='already attempted'):
        c06.run_variant(db, data, '0.600', 10, final=True, expected_version='synthetic')
    incident = db.scalar(select(Incident).where(Incident.details['requested_strategy_id'].as_integer() == row.id))
    assert incident and incident.details['kind'] == 'holdout_reuse'
