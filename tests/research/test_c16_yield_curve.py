from copy import deepcopy
from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import FamilyHoldoutSpend, Fill, Order, Strategy, Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c16_yield_curve as c16


def result():
    split = HoldoutSplit('c16-test:'+uuid.uuid4().hex, c16.START, c16.END)
    return {'status': 'SIGNAL_EVIDENCE_GAP', 'price_status': 'SOURCE_PASS',
        'price_crosscheck': {'passed': True}, 'dataset_admitted': False,
        'macro_evidence': {'status': 'SIGNAL_EVIDENCE_GAP', 'required_series': ['DGS10', 'DGS2'],
            'vintage_records_archived': 0, 'absence_of_valid_historical_observation_proven': False,
            'current_revised_values_used': False, 'new_key_created': False, 'data_spend_usd': '0'},
        'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0,
        'actual_allocation_usd': '0', 'planned_configurations': c16.configurations(),
        'split': split.metadata(), 'identity': {'synthetic_test': uuid.uuid4().hex},
        'code_sha256': {'synthetic': 'a'*64}, **{k: None for k in c16.UNMEASURED}}


@pytest.mark.parametrize('field,value', [
    ('current_revised_values_used', True), ('absence_of_valid_historical_observation_proven', True),
    ('vintage_records_archived', 1), ('required_series', ['DGS10']), ('status', 'DATA_FAIL'),
])
def test_no_substitution_of_revised_yields_or_unproven_historical_cash_absence(field, value):
    evidence = result()
    evidence['macro_evidence'][field] = value
    with pytest.raises(ValueError, match='causal evidence gap'):
        c16.record_gap(None, evidence, 'synthetic')


@pytest.mark.parametrize('field,value', [
    ('pnl', '0'), ('trade_count', 0), ('drawdown', '0'), ('regimes', {}),
    ('historical_stale_observation_decisions', 0), ('price_status', 'DATA_FAIL'),
    ('price_crosscheck', {'passed': False}), ('dataset_admitted', True),
    ('strategy_outcomes_inspected', True), ('training_cases_attempted', 1),
    ('final_holdout_attempts', 1), ('actual_allocation_usd', '140'), ('planned_configurations', []),
])
def test_no_database_write_for_measured_performance_or_changed_scope(field, value):
    evidence = result()
    evidence[field] = value
    with pytest.raises(ValueError, match='only unmeasured'):
        c16.record_gap(None, evidence, 'synthetic')


def test_frozen_time_bounds_and_cost_threshold_cases():
    evidence = result()
    assert evidence['split']['holdout_start'] == datetime(2020, 7, 10, 14, 24, tzinfo=UTC).isoformat()
    assert [(x['threshold_percentage_points'], x['cost_bp']) for x in c16.configurations()] == [
        ('0.00', 5), ('0.00', 10), ('1.00', 5), ('1.00', 10)]
    evidence['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='differs'):
        c16.record_gap(None, evidence, 'synthetic')


def test_source_gap_is_idempotent_null_performance_and_spends_no_final():
    evidence = result()
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            with Session(connection) as session:
                before = session.scalar(select(func.count()).select_from(FamilyHoldoutSpend))
                first = c16.record_gap(session, evidence, 'synthetic')
                again = c16.record_gap(session, deepcopy(evidence), 'later-commit')
                assert first.id == again.id and first.git_commit == 'synthetic'
                assert first.status == 'failed' and not first.final_holdout
                assert all(getattr(first, k) is None for k in (
                    'pnl', 'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value'))
                strategy = session.get(Strategy, first.strategy_id)
                assert strategy.allocation_usd == 0 and strategy.status == 'idea'
                assert strategy.config['research_family'] == 'c16'
                assert first.params['planned_configurations'] == c16.configurations()
                assert session.scalar(select(func.count()).select_from(Trial).where(
                    Trial.strategy_id == first.strategy_id,
                    Trial.params['source_audit_version'].astext == first.params['source_audit_version'])) == 1
                assert session.scalar(select(func.count()).select_from(FamilyHoldoutSpend)) == before
                assert session.scalar(select(func.count()).select_from(Order).where(Order.trial_id == first.id)) == 0
                assert session.scalar(select(func.count()).select_from(Fill).where(Fill.trial_id == first.id)) == 0
        finally:
            transaction.rollback()


def test_changed_price_source_cannot_be_admitted(tmp_path, monkeypatch):
    path = tmp_path/'source.json'
    path.write_text('{}')
    monkeypatch.setattr(c16, 'PRICE_SOURCE', path)
    with pytest.raises(ValueError, match='differs'):
        c16.audit()


def test_source_evidence_cannot_be_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(c16, 'ARCHIVE', tmp_path)
    evidence = result()
    digest = c16.write_once('audit.json', evidence)
    assert c16.write_once('audit.json', evidence) == digest
    evidence['status'] = 'SOURCE_PASS'
    with pytest.raises(ValueError, match='refuse replacement'):
        c16.write_once('audit.json', evidence)
