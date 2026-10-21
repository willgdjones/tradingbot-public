from copy import deepcopy
from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import FamilyHoldoutSpend, Fill, Order, Strategy, Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c15_low_volatility as c15


def result():
    split = HoldoutSplit('c15-test:'+uuid.uuid4().hex, c15.START, c15.END)
    return {'status': 'DATA_FAIL', 'failed_symbols': ['XLE', 'XLU'],
        'crosschecks': {s: {'reference': {'passed': s not in ('XLE', 'XLU')}} for s in c15.SYMBOLS},
        'dataset_admitted': False, 'strategy_outcomes_inspected': False,
        'training_cases_attempted': 0, 'final_holdout_attempts': 0, 'actual_allocation_usd': '0',
        'planned_configurations': c15.configurations(), 'split': split.metadata(),
        'identity': {'synthetic_test': uuid.uuid4().hex}, 'code_sha256': {'synthetic': 'a'*64},
        **{k: None for k in c15.UNMEASURED}}


def test_fixed_universe_rejects_dropping_failed_fund_and_checks_all_routes():
    checks = result()['crosschecks']
    assert c15.failed_symbols(checks) == ['XLE', 'XLU']
    checks['XLE']['second'] = {'passed': True}
    assert c15.failed_symbols(checks) == ['XLU']
    del checks['XLU']
    with pytest.raises(ValueError, match='nine-sector'):
        c15.failed_symbols(checks)
    split = HoldoutSplit('bounds', c15.START, c15.END)
    assert split.holdout_start == datetime(2020, 7, 10, 14, 24, tzinfo=UTC)


@pytest.mark.parametrize('field,value', [
    ('pnl', '0'), ('trade_count', 0), ('drawdown', '0'), ('regimes', {}),
    ('dataset_admitted', True), ('strategy_outcomes_inspected', True),
    ('training_cases_attempted', 1), ('final_holdout_attempts', 1),
    ('actual_allocation_usd', '140'), ('failed_symbols', ['XLE']),
    ('planned_configurations', []),
])
def test_no_database_write_for_performance_or_changed_audit_scope(field, value):
    evidence = result(); evidence[field] = value
    with pytest.raises(ValueError, match='only fixed-universe'):
        c15.record_failure(None, evidence, 'synthetic')


def test_changed_time_bounds_refused_before_any_database_write():
    evidence = result()
    evidence['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='differs'):
        c15.record_failure(None, evidence, 'synthetic')


def test_source_failure_is_idempotent_unmeasured_and_spends_no_final():
    evidence = result()
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            with Session(connection) as session:
                before = session.scalar(select(func.count()).select_from(FamilyHoldoutSpend))
                first = c15.record_failure(session, evidence, 'synthetic')
                again = c15.record_failure(session, deepcopy(evidence), 'later-commit')
                assert first.id == again.id and first.git_commit == 'synthetic'
                assert first.status == 'failed' and not first.final_holdout
                assert all(getattr(first, k) is None for k in (
                    'pnl', 'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value'))
                strategy = session.get(Strategy, first.strategy_id)
                assert strategy.allocation_usd == 0 and strategy.status == 'idea'
                assert strategy.config['research_family'] == 'c15'
                assert first.params['planned_configurations'] == c15.configurations()
                assert session.scalar(select(func.count()).select_from(Trial).where(
                    Trial.strategy_id == first.strategy_id,
                    Trial.params['source_audit_version'].astext == first.params['source_audit_version'])) == 1
                assert session.scalar(select(func.count()).select_from(FamilyHoldoutSpend)) == before
                assert session.scalar(select(func.count()).select_from(Order).where(Order.trial_id == first.id)) == 0
                assert session.scalar(select(func.count()).select_from(Fill).where(Fill.trial_id == first.id)) == 0
        finally:
            transaction.rollback()


def test_source_evidence_cannot_be_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(c15, 'ARCHIVE', tmp_path)
    evidence = result()
    digest = c15.write_once('audit.json', evidence)
    assert c15.write_once('audit.json', evidence) == digest
    evidence['failed_symbols'] = ['XLE']
    with pytest.raises(ValueError, match='refuse replacement'):
        c15.write_once('audit.json', evidence)
