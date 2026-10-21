"""A source-failure receipt cannot smuggle measured outcomes into the ledger."""
import copy

import pytest

from tradingbot.data.archive import canonical
from tradingbot.research.c09_audit import preregistration, validate_failure, UNMEASURED, START, END
from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.research.c09_capture import digest


def receipt():
    result = {'candidate':'C09','status':'DATA_FAIL',
        'failed_prerequisites':[{'kind':'incomplete_ief_share_action_inventory'}],
        'strategy_outcomes_inspected':False,'training_cases_attempted':0,
        'final_holdout_attempts':0,'diagnostics_attempted':0,'selection':None,
        'unmeasured':{k:None for k in UNMEASURED},
        'split':HoldoutSplit('batch2-c09-v1',START,END).metadata(),
        'planned_variants':[{'hold_sessions':5},{'hold_sessions':10}],
        'real_allocation_usd':'0','promotion':'hold_at_source_gate'}
    seal(result)
    return result


def seal(result):
    result.pop('receipt_sha256',None)
    result['receipt_sha256'] = digest(canonical(result).encode())


def test_failure_receipt_rejects_byte_tampering():
    result = receipt(); validate_failure(result)
    result['candidate'] = 'C10'
    with pytest.raises(ValueError,match='receipt changed'): validate_failure(result)


@pytest.mark.parametrize('change', [
    {'status':'PASS'}, {'failed_prerequisites':[]}, {'strategy_outcomes_inspected':True},
    {'training_cases_attempted':1}, {'final_holdout_attempts':1}, {'diagnostics_attempted':1},
    {'selection':{'hold_sessions':5}}, {'unmeasured':{'pnl':'0','drawdown':None}},
    {'unmeasured':{}}, {'planned_variants':[{'hold_sessions':7}]}, {'real_allocation_usd':'140'},
])
def test_even_resealed_outcome_claim_is_not_a_source_failure(change):
    result = receipt(); result.update(copy.deepcopy(change)); seal(result)
    with pytest.raises(ValueError,match='refuses outcomes'): validate_failure(result)


def test_committed_preregistration_bounds_and_variants_remain_frozen():
    r=preregistration()
    assert r['ordered_variants'] == [{'hold_sessions':5},{'hold_sessions':10}]
    assert r['split']['holdout_start'] == '2020-07-10T14:24:00+00:00'
    assert r['max_final_attempts'] == 1


def test_source_ledger_is_idempotent_unmeasured_and_never_spends_a_final():
    import uuid
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from tradingbot.db.models import Trial
    from tradingbot.db.session import get_engine
    from tradingbot.research.c09_audit import record_failure
    result = receipt(); result['identity'] = {'test':uuid.uuid4().hex}; seal(result)
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                before = session.scalar(select(func.count()).select_from(Trial).where(Trial.final_holdout))
                first = record_failure(session,result,'synthetic-source-check')
                assert record_failure(session,result,'second-commit') == first
                row = session.get(Trial,first)
                assert row.git_commit == 'synthetic-source-check'
                assert row.status == 'failed' and row.final_holdout is False
                assert row.pnl_after_fees is row.trade_count is row.luck_p_value is row.max_drawdown is None
                assert row.fees_total is None
                assert row.metrics['training_cases_attempted'] == row.metrics['final_holdout_attempts'] == 0
                assert session.scalar(select(func.count()).select_from(Trial).where(Trial.final_holdout)) == before
        finally:
            transaction.rollback()
