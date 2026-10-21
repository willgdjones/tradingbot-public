from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
from types import SimpleNamespace
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.data.archive import canonical, SCHEMA
from tradingbot.data.c04_sources import Distribution
from tradingbot.data.free_history import parse_yahoo
from tradingbot.db.models import Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c10_source_audit as c
from tradingbot.research.c06_sources import ishares_distributions


def test_actual_issuer_event_is_preserved_when_yahoo_omits_it():
    sources, bodies = c.public_sources(c.ARCHIVE)
    _, bars = parse_yahoo(bodies['yahoo-tlt'].decode())
    result, issuer = c.distributions_audit(bars, ishares_distributions(bodies['tlt-issuer'].decode()))
    assert result['issuer_count'] == 248 and result['yahoo_count'] == 247
    assert result['issuer_only'] == [{'ex_date': '2012-11-01', 'record_date': '2012-11-05',
                                      'pay_date': '2012-11-07', 'amount': '0.269553'}]
    assert not result['source_amendment_applied']
    assert result['amount_disagreements_beyond_0.0005'] == []
    assert issuer[date(2012, 11, 1)].amount == D('.269553')
    assert sources['stooq-tlt']['status'] == 200
    assert b'Date,Open,High,Low,Close,Volume' not in bodies['stooq-tlt']


def test_exhausted_all_type_action_query_does_not_prove_full_coverage():
    first, missing, last = date(2016, 2, 1), date(2016, 8, 1), date(2026, 9, 1)
    issuer = {d: Distribution(d, d, d, D('.25')) for d in (first, missing, last)}
    groups = {'cash_dividends': [{'ex_date': str(d), 'rate': '.25', 'id': str(d), 'symbol': 'TLT'}
                                 for d in (first, last)]}
    result = c.actions_audit(groups, issuer)
    assert result['issuer_dates_missing_within_observed_bounds'] == ['2016-08-01']
    assert not result['full_interval_share_action_completeness_proven']
    groups['cash_dividends'].append(groups['cash_dividends'][0])
    with pytest.raises(ValueError, match='duplicate'):
        c.actions_audit(groups, issuer)


def reference_fixture():
    day = date(2020, 7, 27)
    return day, [SimpleNamespace(date=day, open=D(100), close=D(100))]


def test_open_validation_and_missing_overlap_dates_are_not_hidden_by_close_agreement():
    day, bars = reference_fixture()
    later = date(2020, 7, 29)
    bars.append(SimpleNamespace(date=later, open=D(100), close=D(100)))
    groups = {'TLT': [{'t': '2020-07-27T04:00:00Z', 'o': '102', 'c': '100'},
                      {'t': '2020-07-29T04:00:00Z', 'o': '100', 'c': '100'}]}
    result = c.reference_audit(groups, bars, {day: None, date(2020, 7, 28): None, later: None})
    assert len(result['breaches']) == 1 and result['breaches'][0]['field'] == 'open'
    assert result['missing_overlap_sessions'] == ['2020-07-28']
    assert not result['pre_overlap_validation_claimed']


@pytest.mark.parametrize('price', ['NaN', 'Infinity', '-1', '0'])
def test_invalid_independent_price_stops_source_check(price):
    day, bars = reference_fixture()
    with pytest.raises(ValueError, match='price'):
        c.reference_audit({'TLT': [{'t': '2020-07-27T04:00:00Z', 'o': price, 'c': '100'}]}, bars, {day: None})


def test_api_capture_requires_exact_request_exhaustion_and_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'ROOT', tmp_path)
    request = {'url': 'https://example.invalid', 'params': {'symbols': 'TLT'}}
    dataset = 'corporate_actions'
    manifest = {'format_version': 1, 'venue': 'alpaca', 'dataset': dataset, 'request': request}
    folder = tmp_path / 'raw/alpaca' / dataset / c.RUN / c.sha(canonical(manifest).encode())[:24]
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(canonical(manifest))
    payload = canonical({'corporate_actions': {'cash_dividends': []}, 'next_page_token': None})
    digest = c.sha(payload.encode())
    monkeypatch.setattr(c, 'PINNED', {dataset: digest})
    row = {'format_version': 1, 'venue': 'alpaca', 'dataset': dataset, 'page': 0,
           'retrieved_at': datetime.now(UTC), 'request_json': canonical(request), 'response_json': payload,
           'response_sha256': digest, 'record_count': 0, 'next_request_json': None}
    path = folder / 'page-00000000.parquet'
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), path)
    assert c.api_page(tmp_path, dataset, request)[0]['exhausted']
    with pytest.raises(ValueError, match='identity'):
        c.api_page(tmp_path, dataset, {**request, 'params': {'symbols': 'IEF'}})
    for field, changed in [('next_request_json', '{}'), ('response_json', payload + ' '), ('record_count', 1)]:
        mutated = {**row, field: changed}
        pq.write_table(pa.Table.from_pylist([mutated], schema=SCHEMA), path)
        with pytest.raises(ValueError, match='checksum|cursor|count'):
            c.api_page(tmp_path, dataset, request)


def fixture_result():
    identity = {'synthetic_test': uuid.uuid4().hex}
    split = HoldoutSplit('c10-source-test:' + identity['synthetic_test'], c.START, c.END)
    return {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
            'code_sha256': {'synthetic': 'a' * 64}, 'failed_prerequisites': ['synthetic evidence gap'],
            'dataset_admitted': False, 'strategy_outcomes_inspected': False,
            'planned_configurations': [{'entry_sessions_from_month_end': 3, 'costs_bp_per_side': 10,
                                         'state': 'unattempted_source_gate_failed'}],
            'pnl': None, 'fees': None, 'drawdown': None, 'regimes': None, 'trade_count': None,
            'luck_p_value': None, 'training_cases_attempted': 0, 'final_holdout_attempts': 0}


@pytest.mark.parametrize('field,value', [('status', 'PASS'), ('failed_prerequisites', []),
    ('training_cases_attempted', 1), ('final_holdout_attempts', 1), ('dataset_admitted', True),
    ('strategy_outcomes_inspected', True), ('pnl', 0), ('trade_count', 0)])
def test_source_failure_cannot_hide_performance_or_holdout_use(field, value):
    result = fixture_result()
    result[field] = value
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')


def test_source_failure_cannot_move_holdout_boundary():
    result = fixture_result()
    result['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='bounds'):
        c.record_failure(None, result, 'synthetic')


def test_source_trial_is_idempotent_and_retains_null_metrics_without_final():
    engine = get_engine()
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    result = fixture_result()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                trial = c.record_failure(session, result, 'synthetic-commit')
                params = deepcopy(trial.params)
                again = c.record_failure(session, result, 'different-wrapper-commit')
                assert trial.id == again.id and trial.params == params
                assert trial.git_commit == 'synthetic-commit'
                assert trial.status == 'failed' and not trial.final_holdout
                assert all(getattr(trial, name) is None for name in (
                    'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value'))
                assert session.scalar(select(Trial.id).where(
                    Trial.dataset_key == trial.dataset_key, Trial.final_holdout)) is None
        finally:
            transaction.rollback()
