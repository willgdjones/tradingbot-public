from copy import deepcopy
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c11_audit as c


def receipt():
    return c.seal({'candidate': 'C11', 'status': 'DATA_FAIL',
        'identity': {'synthetic_test': uuid.uuid4().hex},
        'failed_prerequisites': [{'kind': 'synthetic_calendar_gap'}],
        'strategy_outcomes_inspected': False, 'training_cases_attempted': 0,
        'final_holdout_attempts': 0, 'diagnostics_attempted': 0, 'selection': None,
        'unmeasured': {k: None for k in c.UNMEASURED},
        'split': HoldoutSplit('batch2-c11-v1', c.START, c.END).metadata(),
        'planned_variants': deepcopy(c.VARIANTS), 'real_allocation_usd': '0',
        'planned_configurations': [{**v, 'adverse_bps_per_side': bp,
            'state': 'unattempted_source_gate_failed'} for v in c.VARIANTS for bp in (5, 10)],
        'promotion': 'hold_at_source_gate'})


@pytest.mark.parametrize('change', [
    {'status': 'PASS'}, {'failed_prerequisites': []}, {'strategy_outcomes_inspected': True},
    {'training_cases_attempted': 1}, {'final_holdout_attempts': 1}, {'diagnostics_attempted': 1},
    {'selection': {'exit': 'next_session_open'}}, {'unmeasured': {'pnl': '0'}},
    {'planned_variants': [{'exit': 'different_close'}]}, {'planned_configurations': []},
    {'real_allocation_usd': '140'}, {'promotion': 'paper'},
])
def test_even_resealed_outcomes_or_changed_rules_are_refused(change):
    result = receipt(); result.update(change); c.seal(result)
    with pytest.raises(ValueError, match='refuses outcomes'):
        c.validate_failure(result)


def test_receipt_tampering_and_moving_the_boundary_are_refused():
    result = receipt(); result['candidate'] = 'C12'
    with pytest.raises(ValueError, match='receipt changed'):
        c.validate_failure(result)
    result = receipt(); result['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'; c.seal(result)
    with pytest.raises(ValueError, match='changed rules'):
        c.validate_failure(result)


def test_preregistration_retains_exact_family_and_variants():
    record = c.preregistration()
    assert record['ordered_variants'] == c.VARIANTS
    assert record['split']['holdout_start'] == '2020-07-10T14:24:00+00:00'
    assert record['max_final_attempts'] == 1


def test_failed_source_trial_is_idempotent_null_and_never_consumes_final():
    engine = get_engine()
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                before = session.scalar(select(func.count()).select_from(Trial).where(Trial.final_holdout))
                result = receipt()
                first = c.record_failure(session, result, 'synthetic-commit')
                assert c.record_failure(session, result, 'later-commit') == first
                trial = session.get(Trial, first)
                assert trial.status == 'failed' and not trial.final_holdout
                assert trial.git_commit == 'synthetic-commit'
                assert trial.pnl_after_fees is None and trial.pnl is None and trial.trade_count is None
                assert trial.max_drawdown is None and trial.luck_p_value is None
                assert trial.fees_total is None
                assert trial.metrics['round_trips'] is None
                assert session.scalar(select(func.count()).select_from(Trial).where(Trial.final_holdout)) == before
        finally:
            transaction.rollback()
