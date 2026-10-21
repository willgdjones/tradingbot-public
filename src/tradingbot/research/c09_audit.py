"""Record C09 source admission failure without any strategy replay or final."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c09_capture import ROOT, ARCHIVE, digest
from tradingbot.research.c09_sources import ief_audit, treasury_audit

START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
KEY = 'sweep_c09_ief_auction_recovery'
UNMEASURED = ('pnl','fees','slippage','drawdown','regime_results','luck_p_value',
              'exposure','turnover','round_trips','benchmark_results')
OWNED_SOURCES = [
    'src/tradingbot/research/c09_capture.py',
    'src/tradingbot/research/c09_sources.py',
    'src/tradingbot/research/c09_audit.py',
    'docs/research/29-c09-source-plan.md',
    'docs/research/29-c09-special-notice-review.json',
    'docs/research/25-candidate-shortlist.md',
    'docs/research/batch2-sources/2026-10-01-candidate-index.json',
    'docs/research/batch2-sources/2026-10-01-sources.md',
]
DEPENDENCIES = [
    'src/tradingbot/research/c03_source_audit.py',
    'src/tradingbot/research/c03_c04_c03_audit.py',
    'src/tradingbot/research/c06_sources.py',
    'src/tradingbot/research/equity_data.py',
    'src/tradingbot/data/free_history.py',
]


def preregistration():
    path = ROOT/'docs/research/batch2-sources/2026-10-01-candidate-index.json'
    index = json.loads(path.read_text())
    for name, field in [('specification','specification_sha256'),('source_register','source_register_sha256')]:
        if digest((ROOT/index[name]).read_bytes()) != index[field]:
            raise ValueError('frozen batch-2 specification/source register changed')
    candidates = [r for r in index['candidates'] if r['candidate'] == 'C09']
    if len(candidates) != 1:
        raise ValueError('C09 preregistration missing or ambiguous')
    candidate = candidates[0]
    split = HoldoutSplit('batch2-c09-v1', START, END)
    if (candidate['id'] != 'tradingbot-b8y' or candidate['universe'] != ['IEF']
            or candidate['ordered_variants'] != [{'hold_sessions':5},{'hold_sessions':10}]
            or candidate['split'] != split.metadata() or candidate['virtual_cash_usd'] != '140'
            or candidate['max_final_attempts'] != 1 or candidate['selection_cost_case_index'] != 1
            or candidate['training_cost_cases'] != [{'adverse_bps_per_side':5},{'adverse_bps_per_side':10}]):
        raise ValueError('C09 frozen rules/bounds changed')
    return candidate


def audit():
    candidate = preregistration()
    treasury, ief = treasury_audit(), ief_audit()
    identity = {'candidate':'C09', 'preregistration':candidate,
                'source_code_sha256':{p:digest((ROOT/p).read_bytes()) for p in OWNED_SOURCES+DEPENDENCIES},
                'treasury_evidence_sha256':digest(canonical(treasury).encode()),
                'ief_evidence_sha256':digest(canonical(ief).encode())}
    failures = [{
        'kind':'incomplete_ief_share_action_inventory', 'symbol':'IEF',
        'required_interval':[START.isoformat(),END.isoformat()],
        'evidence':{'broker_request_start':'2006-01-01',
                    'first_returned_ief_cash_ex_date':ief['broker_actions']['first_ief_ex_date'],
                    'known_omitted_cash_dates':len(ief['broker_actions']['known_issuer_cash_dates_absent_from_broker_inventory']),
                    'omitted_inside_observed_span':ief['broker_actions']['known_missing_inside_observed_span'],
                    'yahoo_split_count':len(ief['coverage']['split_events'])},
        'reason':ief['limitation'],
        'repair_required':'Full-interval independently supported noncash-action inventory, with causal primary notices '
            'and Amendment21 safe exits for any identified events. Do not move bounds or treat an empty search as proof.'}]
    failures.extend({'kind':'treasury_notice_failure','evidence':r} for r in treasury['failures'])
    result = {'schema_version':1, 'candidate':'C09', 'bead':'tradingbot-b8y', 'status':'DATA_FAIL',
        'identity':identity, 'split':candidate['split'], 'treasury':treasury, 'ief':ief,
        'failed_prerequisites':failures, 'planned_variants':candidate['ordered_variants'],
        'strategy_outcomes_inspected':False, 'training_cases_attempted':0, 'diagnostics_attempted':0,
        'final_holdout_attempts':0, 'selection':None, 'real_allocation_usd':'0', 'promotion':'hold_at_source_gate',
        'unmeasured':{k:None for k in UNMEASURED},
        'scope':'Source-only failed prerequisite; strategy profitability is untested, not rejected.',
        'prior_exposure':'IEF/SPY history was familiar from C03/C06; issuer pages/search snippets expose general '
                         'IEF returns. No C09 event-conditioned outcomes computed. Treasury result metrics not used.'}
    result['receipt_sha256'] = digest(canonical(result).encode())
    return result


def validate_failure(result):
    original = dict(result)
    claimed = original.pop('receipt_sha256')
    if digest(canonical(original).encode()) != claimed:
        raise ValueError('source failure receipt changed')
    if (result['candidate'] != 'C09' or result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']
            or result['strategy_outcomes_inspected'] or result['training_cases_attempted'] != 0
            or result['final_holdout_attempts'] != 0 or result['diagnostics_attempted'] != 0
            or result['selection'] is not None or set(result['unmeasured']) != set(UNMEASURED)
            or any(v is not None for v in result['unmeasured'].values())
            or result['split'] != HoldoutSplit('batch2-c09-v1',START,END).metadata()
            or result['planned_variants'] != [{'hold_sessions':5},{'hold_sessions':10}]
            or result['real_allocation_usd'] != '0' or result['promotion'] != 'hold_at_source_gate'):
        raise ValueError('source-only recorder refuses outcomes or empty failures')


def record_failure(session, result, commit):
    validate_failure(result)
    version = digest(canonical(result['identity']).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(709091)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C09 IEF recovery after nominal ten-year auctions', status='idea',
            config={'candidate':'C09','research_family':'c09','research_only':True,'source_audit_only':True})
        session.add(strategy); session.flush()
    prior = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
        Trial.params['source_audit_version'].astext == version))
    if prior is not None:
        return prior.id
    split = HoldoutSplit('batch2-c09-v1', START, END)
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start, data_start=START, data_end=END,
        git_commit=commit, code_version='c09-source-audit-v1', completed_ts=datetime.now(UTC),
        params={'stage':'data_quality_only_no_strategy_replay','candidate':'C09','source_audit_version':version,
                '_holdout':split.metadata(),'planned_variants':result['planned_variants'],'identity':result['identity']},
        metrics={'audit_result':'DATA_FAIL','source_receipt_sha256':result['receipt_sha256'],
                 'failures':result['failed_prerequisites'],'training_cases_attempted':0,'final_holdout_attempts':0,
                 'diagnostics_attempted':0, **result['unmeasured']},
        notes='Full IEF share-action completeness unresolved. Dated Treasury source evidence retained. '
              'Both fixed hold variants and four cost cases remain unattempted; no signals, returns, '
              'benchmark, final holdout or promotion. Zero real allocation. PRD6 unchanged.')
    session.add(trial); session.flush()
    return trial.id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    if args.record_ledger:
        paths = OWNED_SOURCES + DEPENDENCIES
        if subprocess.check_output(['git','status','--porcelain','--',*paths],cwd=ROOT).strip():
            raise ValueError('commit all source audit inputs before the ledger receipt')
        commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        with session_scope() as session:
            trial_id = record_failure(session, result, commit)
            recorded_commit = session.get(Trial, trial_id).git_commit
        result['ledger'] = {'source_failure_trial_id':trial_id,'audit_git_commit':recorded_commit,
                            'preledger_receipt_sha256':result.pop('receipt_sha256')}
        result['receipt_sha256'] = digest(canonical(result).encode())
    encoded = (json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(encoded)+65536):
        target = ARCHIVE / ('audit-'+result['receipt_sha256']+'.json')
        if target.exists() and target.read_bytes() != encoded:
            raise ValueError('refuse overwrite of immutable source audit')
        if not target.exists(): target.write_bytes(encoded)
    (ROOT/'docs/research/29-c09-source-audit.json').write_bytes(encoded)
    print(json.dumps({'status':result['status'],'events':result['treasury']['events_enumerated'],
        'verified_events':result['treasury']['parsed_events'],'failures':len(result['failed_prerequisites']),
        'source_failure_trial_id':result.get('ledger',{}).get('source_failure_trial_id'),
        'training_cases_attempted':0,'final_holdout_attempts':0,'receipt_sha256':result['receipt_sha256']}))


if __name__ == '__main__': main()
