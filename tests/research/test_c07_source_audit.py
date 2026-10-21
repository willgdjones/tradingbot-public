from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import Trial
from tradingbot.db.session import get_engine
from tradingbot.research.c07_source_audit import (
    END, START, load_sector, record_failure, sha, xlf_failure,
)


def test_capture_hash_identity_and_bounds_are_all_required(tmp_path):
    raw = b'{"archived":true}'
    digest = sha(raw)
    receipt = {'symbol': 'XLF', 'sha256': digest,
               'requested_start': '2006-01-01', 'requested_end_exclusive': '2026-10-01'}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(receipt))
    (tmp_path / 'raw.json').write_bytes(raw)
    assert load_sector(tmp_path, 'XLF', digest)[1] == raw
    (tmp_path / 'raw.json').write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='checksum'):
        load_sector(tmp_path, 'XLF', digest)
    (tmp_path / 'raw.json').write_bytes(raw)
    receipt['requested_start'] = '2017-01-01'
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='bounds'):
        load_sector(tmp_path, 'XLF', digest)
    with pytest.raises(ValueError, match='universe'):
        load_sector(tmp_path, 'XLRE', digest)


def test_closed_xlf_bead_does_not_admit_its_data():
    root = Path(__file__).resolve().parents[2]
    receipt = json.loads((root / 'docs/research/17-xlf-action-amendment.json').read_text())
    failures = xlf_failure(receipt)
    assert len(failures) == 4
    assert any('availability' in failure for failure in failures)
    receipt['dataset_admitted'] = True
    with pytest.raises(ValueError, match='receipt changed'):
        xlf_failure(receipt)


def result_fixture():
    identity = {'synthetic_test': uuid.uuid4().hex}
    split = HoldoutSplit('c07-source-test:' + identity['synthetic_test'], START, END)
    return {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
            'code_sha256': {'synthetic': 'a' * 64}, 'failed_prerequisites': ['synthetic missing evidence'],
            'training_cases_attempted': 0, 'final_holdout_attempts': 0}


@pytest.mark.parametrize('field,value', [('status', 'PASS'), ('failed_prerequisites', []),
    ('training_cases_attempted', 1), ('final_holdout_attempts', 1)])
def test_performance_attempt_cannot_be_mislabeled_as_source_failure(field, value):
    result = result_fixture()
    result[field] = value
    with pytest.raises(ValueError, match='failed source audit'):
        record_failure(None, result, 'synthetic')


def test_changed_holdout_boundary_is_rejected_before_database_access():
    result = result_fixture()
    assert result['split']['holdout_start'] == datetime(2020, 7, 10, 14, 24, tzinfo=UTC).isoformat()
    result['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='bounds'):
        record_failure(None, result, 'synthetic')


def test_failed_audit_is_idempotent_without_performance_or_holdout_consumption():
    engine = get_engine()
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    result = result_fixture()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                first = record_failure(session, result, 'synthetic-commit')
                before = deepcopy(first.params)
                again = record_failure(session, result, 'different-wrapper-commit')
                assert again.id == first.id and again.params == before
                assert first.status == 'failed' and first.final_holdout is False
                assert all(getattr(first, name) is None for name in (
                    'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value'))
                assert session.scalar(select(Trial.id).where(
                    Trial.dataset_key == first.dataset_key, Trial.final_holdout)) is None
        finally:
            transaction.rollback()
