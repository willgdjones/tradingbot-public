"""C05 admission stops at source evidence, without evaluating its signals."""
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace
import uuid

import pytest

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.research.c05_commodity_trend import (
    DOCUMENTS, END, START, UNIVERSE, inspect_source, load_document, load_source,
    record_failure, sha, verify_fractional_evidence,
)


def payload():
    return {'chart': {'result': [{
        'meta': {'symbol': 'GLD'},
        'timestamp': [int(datetime(2008, 1, d, 14, 30, tzinfo=UTC).timestamp()) for d in (2, 3)],
        'indicators': {'quote': [{'open': [10, 11], 'high': [12, 13], 'low': [9, 10],
                                 'close': [11, 12], 'volume': [100, 100]}],
                       'adjclose': [{'adjclose': [10, 11]}]}, 'events': {},
    }], 'error': None}}


def inspect(doc):
    sessions = {date(2008, 1, d): SimpleNamespace(closes_at=datetime(2008, 1, d, 21, tzinfo=UTC)) for d in (2, 3)}
    # The shared calendar includes years before the C05-specific source interval.
    sessions[date(2007, 12, 31)] = SimpleNamespace(closes_at=datetime(2007, 12, 31, 21, tzinfo=UTC))
    return inspect_source(json.dumps(doc).encode(), 'GLD', sessions)


def test_coverage_uses_c05_bounds_without_return_or_admission_claim():
    result = inspect(payload())
    assert result['coverage_ok'] and result['expected_sessions'] == 2
    assert 'pnl' not in result and 'returns' not in result and 'passed' not in result
    assert UNIVERSE == ('GLD', 'SLV', 'USO', 'UNG', 'DBA')
    assert HoldoutSplit('c05-test', START, END).holdout_start == datetime(2021, 2, 14, 14, 24, tzinfo=UTC)


def test_missing_null_and_invalid_prices_cannot_be_admitted():
    doc = payload()
    quote = doc['chart']['result'][0]['indicators']['quote'][0]
    quote['open'][0] = None
    result = inspect(doc)
    assert not result['coverage_ok'] and result['null_rows'] == 1
    assert result['missing_sessions'] == ['2008-01-02']
    quote['open'][0] = 14
    assert inspect(doc)['invalid_sessions'] == ['2008-01-02']
    quote['open'][0], quote['volume'][0] = 10, None
    assert inspect(doc)['null_volume'] == ['2008-01-02']


def test_wrong_identity_duplicate_timestamps_and_truncated_arrays_rejected():
    doc = payload()
    result = doc['chart']['result'][0]
    result['meta']['symbol'] = 'SLV'
    with pytest.raises(ValueError, match='symbol'):
        inspect(doc)
    result['meta']['symbol'] = 'GLD'
    result['indicators']['quote'][0]['volume'].pop()
    with pytest.raises(ValueError, match='lengths'):
        inspect(doc)
    doc = payload()
    doc['chart']['result'][0]['timestamp'][1] = doc['chart']['result'][0]['timestamp'][0]
    with pytest.raises(ValueError, match='duplicated'):
        inspect(doc)


def test_split_numerical_agreement_and_invalid_denominator():
    doc = payload()
    result = doc['chart']['result'][0]
    stamp = result['timestamp'][0]
    event = {'date': stamp, 'numerator': 10.0, 'denominator': 1.0, 'splitRatio': '10:1'}
    result['events']['splits'] = {str(stamp): event}
    assert inspect(doc)['split_events'] == [{'date': '2008-01-02', 'ratio': '10'}]
    event['splitRatio'] = '1:10'
    with pytest.raises(ValueError, match='inconsistent'):
        inspect(doc)
    event['denominator'] = 0
    with pytest.raises(ValueError, match='invalid'):
        inspect(doc)


def test_orphaned_actions_and_duplicate_split_dates_fail_closed():
    doc = payload()
    result = doc['chart']['result'][0]
    stamp = int(datetime(2008, 1, 4, 14, 30, tzinfo=UTC).timestamp())
    event = {'date': stamp, 'numerator': 1, 'denominator': 4, 'splitRatio': '1:4'}
    result['events']['splits'] = {str(stamp): event}
    assert not inspect(doc)['coverage_ok']
    assert inspect(doc)['orphan_event_dates'] == ['2008-01-04']
    result['events']['splits']['other'] = dict(event)
    with pytest.raises(ValueError, match='duplicated'):
        inspect(doc)


def test_archival_bytes_bounds_and_document_url_are_verified(tmp_path):
    raw = json.dumps(payload()).encode()
    (tmp_path / 'raw.json').write_bytes(raw)
    receipt = {'symbol': 'GLD', 'sha256': sha(raw), 'start': START.isoformat(), 'end_exclusive': END.isoformat()}
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(receipt))
    assert load_source(tmp_path, 'GLD')[1] == raw
    (tmp_path / 'raw.json').write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='checksum'):
        load_source(tmp_path, 'GLD')
    (tmp_path / 'raw.json').write_bytes(raw)
    receipt['start'] = '2006-01-01T00:00:00+00:00'
    manifest.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='bounds'):
        load_source(tmp_path, 'GLD')
    key = 'alpaca-corporate-actions'
    receipt = {'key': key, 'request_url': DOCUMENTS[key], 'sha256': sha(raw)}
    manifest.write_text(json.dumps(receipt))
    (tmp_path / 'raw').write_bytes(raw)
    assert load_document(tmp_path, key)[1] == raw
    receipt['request_url'] = 'https://example.invalid/unrelated'
    manifest.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='identity'):
        load_document(tmp_path, key)


def evidence():
    bodies = {
        'uso-2020-issuer-release': 'April 29, 2020 cash in lieu',
        'ung-2011-issuer-release': 'March 9, 2011 cash in lieu',
        'ung-2012-split': 'February 22, 2012 cash in lieu',
        'ung-2018-issuer-release': 'January 5, 2018 cash in lieu',
        'ung-2024-issuer-release': 'January 24, 2024 cash in lieu',
        'alpaca-corporate-actions': 'reverse splits cash from DTC',
        'alpaca-2021-fractionals': 'August 2nd, 2021 removing cash-in-lieu transactions',
    }
    return {k: ({'status_code': 200}, f'<p>{v}</p>'.encode()) for k, v in bodies.items()}


def test_conflicting_broker_sources_never_supply_invented_cash_dates():
    docs = evidence()
    gate = verify_fractional_evidence(docs)
    assert gate['account_specific_fractional_treatment'] is None and gate['cash_credit_dates'] is None
    assert gate['conclusion'].startswith('Unresolved')
    docs['alpaca-2021-fractionals'][0]['status_code'] = 403
    with pytest.raises(ValueError, match='evidence incomplete'):
        verify_fractional_evidence(docs)
    docs = evidence()
    docs['ung-2012-split'] = ({'status_code': 200}, b'An unrelated corporate action')
    with pytest.raises(ValueError, match='ung-2012-split'):
        verify_fractional_evidence(docs)


def test_failed_source_trial_is_idempotent_null_and_not_a_final():
    from sqlalchemy.orm import Session
    from tradingbot.db.session import get_engine
    identity = {'test': uuid.uuid4().hex}
    split = HoldoutSplit('c05-audit-test:' + identity['test'], START, END)
    result = {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
              'code_sha256': {'test': 'a' * 64}, 'failed_prerequisites': ['test action policy unresolved']}
    with get_engine().connect() as connection:
        tx = connection.begin()
        try:
            with Session(bind=connection) as session:
                trial = record_failure(session, result, 'test-commit')
                assert record_failure(session, result, 'test-commit').id == trial.id
                assert trial.status == 'failed' and trial.final_holdout is False
                assert trial.pnl_after_fees is None and trial.trade_count is None
                assert trial.max_drawdown is None and trial.luck_p_value is None
                assert trial.metrics['training_cases_attempted'] == trial.metrics['final_holdout_attempts'] == 0
                result['failed_prerequisites'] = []
                with pytest.raises(ValueError, match='concrete data failure'):
                    record_failure(session, result, 'test-commit')
        finally:
            tx.rollback()
