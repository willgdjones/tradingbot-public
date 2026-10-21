from copy import deepcopy
from decimal import Decimal as D
import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c13_capture as capture
from tradingbot.research import c13_source_audit as c


def fixture_result():
    identity = {'synthetic_test': str(uuid4()), 'policy': deepcopy(c.POLICY)}
    split = HoldoutSplit('c13-source-test:' + identity['synthetic_test'], c.START, c.END)
    return {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
            'code_sha256': {'synthetic': 'a' * 64}, 'failed_prerequisites': c.FAILURES,
            'dataset_admitted': False, 'strategy_outcomes_inspected': False,
            'planned_configurations': c.configurations(), 'promotion': 'none',
            **{k: None for k in c.METRICS}, 'training_cases_attempted': 0,
            'final_holdout_attempts': 0}


@pytest.mark.parametrize('field,value', [
    ('status', 'PASS'), ('failed_prerequisites', []), ('dataset_admitted', True),
    ('strategy_outcomes_inspected', True), ('pnl', 0), ('trade_count', 0),
    ('training_cases_attempted', 1), ('final_holdout_attempts', 1),
    ('planned_configurations', []), ('promotion', 'paper')])
def test_null_failure_cannot_hide_results_or_promote(field, value):
    result = fixture_result()
    result[field] = value
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')


def test_no_changed_universe_or_recycled_split():
    result = fixture_result()
    result['identity']['policy']['universe'] = ['F']
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')
    result = fixture_result()
    result['split']['holdout_start'] = '2026-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='bounds'):
        c.record_failure(None, result, 'synthetic')


def test_capital_bound_preserves_multiplier_and_never_claims_affordability():
    full = c.capital_bound()
    assert D(full['combined_asks_upper_bound_before_fees_per_share']) == D('.45')
    # Cash is a separate constraint; a large margin-style buying power must not
    # be passed as settled cash by a consumer. More equity cannot enlarge $49.
    constrained = c.capital_bound(D('1000'), D('20'))
    assert D(constrained['opening_budget_usd']) == D('20')
    assert D(constrained['combined_asks_upper_bound_before_fees_per_share']) == D('.16')
    assert full['affordable_event_count'] is None and full['necessary_condition_only']
    assert not c.capital_bound(D('140'), D('4'))['positive_premiums_possible_before_fees']
    for bad in ('-1', 'NaN', 'Infinity'):
        with pytest.raises(ValueError):
            c.capital_bound(D(bad))


def test_archived_source_rejects_altered_bytes_identity_or_capture_code(tmp_path):
    key = 'historical-data'
    folder = tmp_path / key
    folder.mkdir()
    code = b'captured source code'
    code_dir = tmp_path / 'capture-code'
    code_dir.mkdir()
    code_path = code_dir / (capture.sha(code) + '.py')
    code_path.write_bytes(code)
    raw = b'original source response'
    meta = {'url': capture.SOURCES[key], 'method': 'GET', 'sha256': capture.sha(raw),
            'bytes': len(raw), 'capture_code_sha256': capture.sha(code)}
    (folder / 'raw').write_bytes(raw)
    (folder / 'manifest.json').write_text(json.dumps(meta))
    assert capture.load(key, tmp_path)[1] == raw
    (folder / 'raw').write_bytes(raw + b'x')
    with pytest.raises(ValueError, match='bytes changed'):
        capture.load(key, tmp_path)
    (folder / 'raw').write_bytes(raw)
    meta['url'] = 'https://example.com/other'
    (folder / 'manifest.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='identity'):
        capture.load(key, tmp_path)
    meta['url'] = capture.SOURCES[key]
    (folder / 'manifest.json').write_text(json.dumps(meta))
    code_path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='code changed'):
        capture.load(key, tmp_path)


def test_harness_cannot_relabel_current_quotes_as_historical(tmp_path, monkeypatch):
    reports = []
    for i in range(8):
        reports.append({'directory': f'data/options/{i}', 'dataset': 'quotes', 'request': {},
                        'complete': True, 'pages': 1, 'records': 1,
                        'response_set_sha256': 'a' * 64, 'semantics': 'synthetic current quote',
                        'retrieved_first': '2026-10-01', 'retrieved_last': '2026-10-01',
                        'historical_bbo': True, 'historical_chain_membership': False,
                        'executable_fill_evidence': False})
    path = tmp_path / c.HARNESS
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'strategy_evaluation': False, 'reports': reports}))
    monkeypatch.setattr(c, 'audit_options', lambda _: reports[0])
    with pytest.raises(ValueError, match='New execution evidence'):
        c.verify_harness(tmp_path)


def test_ledger_failure_idempotent_and_no_final_or_performance():
    engine = get_engine()
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    result = fixture_result()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                before = list(session.scalars(select(Trial.id).where(Trial.final_holdout).order_by(Trial.id)))
                trial = c.record_failure(session, result, 'synthetic-commit')
                params = deepcopy(trial.params)
                again = c.record_failure(session, result, 'later-wrapper')
                assert trial.id == again.id and trial.params == params
                assert trial.git_commit == 'synthetic-commit'
                assert trial.status == 'failed' and not trial.final_holdout
                assert all(getattr(trial, name) is None for name in (
                    'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value',
                    'sharpe', 'win_rate', 'pnl'))
                assert list(session.scalars(select(Trial.id).where(Trial.final_holdout).order_by(Trial.id))) == before
                assert session.scalar(select(Trial.id).where(
                    Trial.dataset_key == trial.dataset_key, Trial.final_holdout)) is None
        finally:
            transaction.rollback()
