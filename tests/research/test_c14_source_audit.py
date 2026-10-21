from copy import deepcopy
from decimal import Decimal as D
import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c14_source_audit as c


def fixture_result():
    identity = {'synthetic_test': str(uuid4()), 'policy': deepcopy(c.POLICY)}
    split = HoldoutSplit('c14-source-test:' + identity['synthetic_test'], c.START, c.END)
    return {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
            'code_sha256': {'synthetic': 'a' * 64}, 'failed_prerequisites': c.FAILURES,
            'dataset_admitted': False, 'strategy_outcomes_inspected': False,
            'planned_configurations': c.configurations(), 'promotion': 'none',
            'capital': c.capital_bound(), **{k: None for k in c.METRICS},
            'training_cases_attempted': 0, 'final_holdout_attempts': 0}


@pytest.mark.parametrize('field,value', [
    ('status', 'PASS'), ('failed_prerequisites', []), ('dataset_admitted', True),
    ('strategy_outcomes_inspected', True), ('pnl', 0), ('trade_count', 0),
    ('training_cases_attempted', 1), ('final_holdout_attempts', 1),
    ('planned_configurations', []), ('promotion', 'paper')])
def test_source_failure_cannot_hide_performance_or_promotion(field, value):
    result = fixture_result()
    result[field] = value
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')


def test_frozen_rules_cutoff_and_unknown_affordability_are_enforced():
    result = fixture_result()
    result['identity']['policy']['universe'] = ['PLUG']
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')
    result = fixture_result()
    result['split']['holdout_start'] = '2026-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='bounds'):
        c.record_failure(None, result, 'synthetic')
    result = fixture_result()
    result['capital']['affordable_event_count'] = 0
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')


@pytest.mark.parametrize('equity,cash,budget,bound', [
    ('140', '140', '133', '1.33'), ('1000', '1000', '140', '1.4'),
    ('140', '75', '75', '.75'), ('0', '140', '0', '0')])
def test_full_obligation_precedes_premium_and_is_limited_by_cash(equity, cash, budget, bound):
    result = c.capital_bound(D(equity), D(cash))
    assert D(result['collateral_budget_before_reserves_usd']) == D(budget)
    assert D(result['strike_upper_bound_before_reserves_usd']) == D(bound)
    assert not result['illustrative_1_50_strike_fits_before_reserves']
    assert not result['premium_credit_used_for_collateral']
    assert result['required_reserve_usd'] is None
    assert result['affordable_event_count'] is None
    assert result['eligible_contract_count'] is None


def test_invalid_capital_is_not_silently_clipped():
    for bad in ('-1', 'NaN', 'Infinity'):
        for values in ((D(bad), D(140)), (D(140), D(bad))):
            with pytest.raises(ValueError):
                c.capital_bound(*values)


def test_scope_rejects_changed_cost_case_even_when_source_files_match(tmp_path):
    index = json.loads((c.ROOT / c.prior.INDEX).read_bytes())
    for path in (index['specification'], index['source_register']):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((c.ROOT / path).read_bytes())
    target = tmp_path / c.prior.INDEX
    target.write_text(json.dumps(index))
    assert c.verify_scope(tmp_path)['split']['holdout_start'] == '2025-12-13T02:24:00+00:00'
    candidate = next(row for row in index['candidates'] if row['candidate'] == 'C14')
    candidate['training_cost_cases'][1]['adverse_per_share_usd'] = '0.005'
    target.write_text(json.dumps(index))
    with pytest.raises(ValueError, match='bounds, sizing or cases'):
        c.verify_scope(tmp_path)


def test_reuse_cannot_accept_changed_receipt_or_relabel_existing_evidence(tmp_path, monkeypatch):
    for path in (c.REVIEW, c.prior.REPORT, c.prior.REVIEW):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((c.ROOT / path).read_bytes())
    saved = json.loads((tmp_path / c.prior.REPORT).read_bytes())
    for field in ('data_failure_trial_id', 'strategy_id', 'audit_git_commit'):
        saved.pop(field, None)
    monkeypatch.setattr(c.prior, 'audit', lambda *_: deepcopy(saved))
    assert c.verify_reuse(tmp_path)[1]['dataset_admitted'] is False
    original = (tmp_path / c.prior.REPORT).read_bytes()
    (tmp_path / c.prior.REPORT).write_bytes(original + b' ')
    with pytest.raises(ValueError, match='Unreviewed reused'):
        c.verify_reuse(tmp_path)
    (tmp_path / c.prior.REPORT).write_bytes(original)
    saved['harness_reaudit'][0]['historical_bbo'] = True
    with pytest.raises(ValueError, match='evidence or dependencies changed'):
        c.verify_reuse(tmp_path)


def test_failure_is_idempotent_null_and_never_consumes_a_final():
    engine = get_engine()
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    result = fixture_result()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                finals = list(session.scalars(select(Trial.id).where(Trial.final_holdout).order_by(Trial.id)))
                trial = c.record_failure(session, result, 'synthetic-commit')
                params = deepcopy(trial.params)
                again = c.record_failure(session, result, 'later-wrapper')
                assert trial.id == again.id and trial.params == params
                assert trial.git_commit == 'synthetic-commit'
                assert trial.status == 'failed' and not trial.final_holdout
                assert all(getattr(trial, name) is None for name in (
                    'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value',
                    'sharpe', 'win_rate', 'pnl'))
                assert list(session.scalars(select(Trial.id).where(Trial.final_holdout).order_by(Trial.id))) == finals
                strategy = session.get(Strategy, trial.strategy_id)
                assert strategy.status == 'idea' and strategy.allocation_usd == 0
                strategy.allocation_usd = D('140')
                session.flush()
                with pytest.raises(ValueError, match='active or funded'):
                    c.record_failure(session, result, 'cannot-reset-funded-strategy')
        finally:
            transaction.rollback()
