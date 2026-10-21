"""C03 source gate rejects missing/altered evidence before replay is possible."""
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace

import pytest

from tradingbot.research.c03_source_audit import (
    END, START, UNIVERSE, inspect_source, load_source, record_failure, sha,
)
from tradingbot.backtest.holdout import HoldoutSplit


def payload():
    return {'chart': {'result': [{
        'meta': {'symbol': 'SPY'},
        'timestamp': [int(datetime(2006, 1, d, 14, 30, tzinfo=UTC).timestamp()) for d in (3, 4)],
        'indicators': {'quote': [{'open': [10, 11], 'high': [12, 13], 'low': [9, 10],
                                 'close': [11, 12], 'volume': [100, 100]}],
                       'adjclose': [{'adjclose': [10, 11]}]}, 'events': {},
    }], 'error': None}}


def sessions():
    return {date(2006, 1, d): SimpleNamespace(closes_at=datetime(2006, 1, d, 21, tzinfo=UTC)) for d in (3, 4)}


def inspect(doc):
    return inspect_source(json.dumps(doc).encode(), 'SPY', sessions())


def test_coverage_does_not_imply_cash_or_strategy_admission():
    result = inspect(payload())
    assert result['coverage_ok'] is True
    assert result['sessions'] == 2
    assert 'pnl' not in result and 'returns' not in result
    assert 'passed' not in result and 'promotion' not in result


def test_null_and_invalid_ohlc_fail_closed():
    doc = payload()
    doc['chart']['result'][0]['indicators']['quote'][0]['open'][0] = None
    result = inspect(doc)
    assert not result['coverage_ok'] and result['null_rows'] == 1
    assert result['missing_sessions'] == ['2006-01-03']
    doc = payload()
    doc['chart']['result'][0]['indicators']['quote'][0]['open'][0] = 14
    assert inspect(doc)['invalid_sessions'] == ['2006-01-03']


def test_duplicate_timestamp_and_symbol_substitution_rejected():
    doc = payload()
    doc['chart']['result'][0]['timestamp'][1] = doc['chart']['result'][0]['timestamp'][0]
    with pytest.raises(ValueError, match='duplicated'):
        inspect(doc)
    doc = payload()
    doc['chart']['result'][0]['meta']['symbol'] = 'QQQ'
    with pytest.raises(ValueError, match='symbol'):
        inspect(doc)


def test_event_on_missing_session_cannot_silently_disappear():
    doc = payload()
    stamp = int(datetime(2006, 1, 5, 14, 30, tzinfo=UTC).timestamp())
    doc['chart']['result'][0]['events']['dividends'] = {str(stamp): {'date': stamp, 'amount': .5}}
    result = inspect(doc)
    assert not result['coverage_ok']
    assert result['orphan_event_dates'] == ['2006-01-05']


def test_capture_integrity_and_fixed_bounds(tmp_path):
    raw = json.dumps(payload()).encode()
    (tmp_path / 'raw.json').write_bytes(raw)
    receipt = {'symbol': 'SPY', 'sha256': sha(raw), 'start': START.isoformat(), 'end_exclusive': END.isoformat()}
    (tmp_path / 'manifest.json').write_text(json.dumps(receipt))
    assert load_source(tmp_path, 'SPY')[1] == raw
    (tmp_path / 'raw.json').write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='checksum'):
        load_source(tmp_path, 'SPY')
    (tmp_path / 'raw.json').write_bytes(raw)
    receipt['start'] = '2007-01-01T00:00:00+00:00'
    (tmp_path / 'manifest.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='bounds'):
        load_source(tmp_path, 'SPY')


def test_preregistered_universe_and_split_remain_fixed():
    assert UNIVERSE == ('SPY', 'IEF', 'GLD', 'EFA', 'VNQ')
    split = HoldoutSplit('c03-test', START, END)
    assert split.holdout_start == datetime(2020, 7, 10, 14, 24, tzinfo=UTC)
    assert not split.contains(datetime(2020, 7, 10, 20, tzinfo=UTC))


def test_failed_audit_ledger_is_idempotent_and_does_not_consume_holdout():
    import uuid
    from sqlalchemy.orm import Session
    from tradingbot.db.session import get_engine
    identity = {'test': uuid.uuid4().hex}
    split = HoldoutSplit('c03-audit-test:' + identity['test'], START, END)
    result = {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
              'audit_code_sha256': 'a' * 64, 'failed_prerequisites': ['test missing source']}
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                first = record_failure(session, result, 'test-commit')
                again = record_failure(session, result, 'test-commit')
                assert first.id == again.id
                assert first.status == 'failed' and first.final_holdout is False
                assert first.pnl_after_fees is None and first.trade_count is None
                assert first.luck_p_value is None and first.max_drawdown is None
                assert first.metrics['training_cases_attempted'] == first.metrics['final_holdout_attempts'] == 0
        finally:
            transaction.rollback()
