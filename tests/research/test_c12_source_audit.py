from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import Trial
from tradingbot.db.session import get_engine
from tradingbot.research import c12_source_audit as c


def fixture_result():
    identity = {'synthetic_test': str(uuid4())}
    split = HoldoutSplit('c12-source-test:' + identity['synthetic_test'], c.START, c.END)
    return {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
        'code_sha256': {'synthetic': 'a' * 64}, 'failed_prerequisites': ['synthetic calendar gap'],
        'dataset_admitted': False, 'strategy_outcomes_inspected': False,
        'planned_configurations': c.configurations(), 'pnl': None, 'fees': None,
        'drawdown': None, 'regimes': None, 'trade_count': None, 'luck_p_value': None,
        'training_cases_attempted': 0, 'final_holdout_attempts': 0}


@pytest.mark.parametrize('field,value', [('status', 'PASS'), ('failed_prerequisites', []),
    ('dataset_admitted', True), ('strategy_outcomes_inspected', True), ('pnl', 0),
    ('trade_count', 0), ('training_cases_attempted', 1), ('final_holdout_attempts', 1),
    ('planned_configurations', [])])
def test_source_failure_cannot_conceal_results_or_changed_variants(field, value):
    result = fixture_result()
    result[field] = value
    with pytest.raises(ValueError, match='without performance'):
        c.record_failure(None, result, 'synthetic')


def test_source_failure_cannot_move_locked_cutoff():
    result = fixture_result()
    result['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='bounds'):
        c.record_failure(None, result, 'synthetic')


def test_null_source_trial_is_idempotent_without_consuming_final():
    engine = get_engine()
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    result = fixture_result()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                before = list(session.scalars(select(Trial.id).where(Trial.final_holdout)))
                trial = c.record_failure(session, result, 'synthetic-commit')
                params = deepcopy(trial.params)
                again = c.record_failure(session, result, 'later-wrapper')
                assert trial.id == again.id and trial.params == params
                assert trial.git_commit == 'synthetic-commit'
                assert trial.status == 'failed' and not trial.final_holdout
                assert all(getattr(trial, name) is None for name in (
                    'pnl_after_fees', 'fees_total', 'trade_count', 'max_drawdown', 'luck_p_value'))
                assert list(session.scalars(select(Trial.id).where(Trial.final_holdout))) == before
                assert session.scalar(select(Trial.id).where(
                    Trial.dataset_key == trial.dataset_key, Trial.final_holdout)) is None
        finally:
            transaction.rollback()
