"""C11 source-only failed admission; no strategy replay or final consumption."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c11_capture import ROOT, ARCHIVE, sha
from tradingbot.research.c11_sources import audit_sources

START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
KEY = 'batch2_c11_spy_monthly_expiration'
VARIANTS = [{'exit': 'standard_expiration_session_close'}, {'exit': 'next_session_open'}]
UNMEASURED = ('pnl', 'fees', 'slippage', 'drawdown', 'regime_results', 'luck_p_value',
              'exposure', 'turnover', 'round_trips', 'benchmark_results')
INPUTS = [
    'src/tradingbot/research/c11_capture.py', 'src/tradingbot/research/c11_sources.py',
    'src/tradingbot/research/c11_audit.py', 'src/tradingbot/research/c06_sources.py',
    'docs/research/31-c11-source-plan.md', 'docs/research/31-c11-evidence.json',
    'docs/research/25-candidate-shortlist.md', 'docs/research/21-corporate-action-blackout.md',
    'docs/research/batch2-sources/2026-10-01-candidate-index.json',
    'docs/research/batch2-sources/2026-10-01-sources.md',
]


def preregistration():
    index = json.loads((ROOT / 'docs/research/batch2-sources/2026-10-01-candidate-index.json').read_bytes())
    for name, field in [('specification', 'specification_sha256'), ('source_register', 'source_register_sha256')]:
        if sha((ROOT / index[name]).read_bytes()) != index[field]:
            raise ValueError('frozen batch-2 specification/source register changed')
    candidates = [r for r in index['candidates'] if r['candidate'] == 'C11']
    if len(candidates) != 1:
        raise ValueError('C11 preregistration missing or ambiguous')
    candidate = candidates[0]
    if (candidate['id'] != 'tradingbot-e76' or candidate['universe'] != ['SPY']
            or candidate['ordered_variants'] != VARIANTS
            or candidate['split'] != HoldoutSplit('batch2-c11-v1', START, END).metadata()
            or candidate['virtual_cash_usd'] != '140' or candidate['max_final_attempts'] != 1
            or candidate['selection_cost_case_index'] != 1
            or candidate['training_cost_cases'] != [{'adverse_bps_per_side': 5}, {'adverse_bps_per_side': 10}]):
        raise ValueError('C11 frozen rules/bounds changed')
    return candidate


def seal(result):
    result.pop('receipt_sha256', None)
    result['receipt_sha256'] = sha(canonical(result).encode())
    return result


def audit():
    candidate, sources = preregistration(), audit_sources()
    failures = [
        {'kind': 'calendar_provenance_incomplete', 'variants': VARIANTS,
         'reason': sources['calendar']['failure'],
         'repair_required': 'Original dated calendars/notices and revision chronology for the full frozen interval, '
             'including holidays and unexpected closures, all known before the original decisions.'},
        {'kind': 'share_action_inventory_incomplete', 'variants': VARIANTS,
         'reason': sources['spy']['actions']['limitation'],
         'repair_required': 'Independently supported full SPY noncash-action inventory, with primary '
             'advance notice and Amendment21 handling for any identified action.'},
        {'kind': 'fractional_close_execution_unproven', 'variants': [VARIANTS[0]],
         'reason': sources['execution']['reason'],
         'repair_required': 'Supported fractional close-order route and adequate causal execution evidence; '
             'a new endpoint/time/sizing rule would require a separately documented preregistration.'},
    ]
    configurations = [{**v, 'adverse_bps_per_side': cost, 'state': 'unattempted_source_gate_failed'}
                      for v in VARIANTS for cost in (5, 10)]
    identity = {'candidate': 'C11', 'preregistration': candidate,
                'source_code_sha256': {p: sha((ROOT / p).read_bytes()) for p in INPUTS},
                'source_evidence_sha256': sha(canonical(sources).encode())}
    return seal({'schema_version': 1, 'candidate': 'C11', 'bead': 'tradingbot-e76', 'status': 'DATA_FAIL',
        'identity': identity, 'split': candidate['split'], 'sources': sources,
        'failed_prerequisites': failures, 'planned_variants': VARIANTS,
        'planned_configurations': configurations, 'strategy_outcomes_inspected': False,
        'training_cases_attempted': 0, 'diagnostics_attempted': 0, 'final_holdout_attempts': 0,
        'selection': None, 'real_allocation_usd': '0', 'promotion': 'hold_at_source_gate',
        'unmeasured': {k: None for k in UNMEASURED},
        'not_completed_after_failed_gate': ['Full source admission and causal calendar extraction',
            'Strategy reactor and shared risk/ledger replay', 'Training, seven-day controls, benchmarks, '
            'winner selection, final and dependence-aware inference'],
        'prior_exposure': 'Existing SPY #5/#6/C01–C08 outcomes and published calendar hypotheses are known. '
            'Search previews exposed broad SPX weekday-return discussion. No C11 event-conditioned '
            'return or control calculated. The mechanical partition does not create pristine confirmation.',
        'scope': 'Source failure, not a measured rejection of profitability. All four training cases '
            'and final remain unattempted. No order, allocation, promotion, risk or accepted-risk change.'})


def validate_failure(result):
    original = dict(result)
    claimed = original.pop('receipt_sha256')
    if sha(canonical(original).encode()) != claimed:
        raise ValueError('C11 source receipt changed')
    expected = [{**v, 'adverse_bps_per_side': cost, 'state': 'unattempted_source_gate_failed'}
                for v in VARIANTS for cost in (5, 10)]
    if (result['candidate'] != 'C11' or result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']
            or result['strategy_outcomes_inspected'] or result['training_cases_attempted'] != 0
            or result['final_holdout_attempts'] != 0 or result['diagnostics_attempted'] != 0
            or result['selection'] is not None or set(result['unmeasured']) != set(UNMEASURED)
            or any(v is not None for v in result['unmeasured'].values())
            or result['split'] != HoldoutSplit('batch2-c11-v1', START, END).metadata()
            or result['planned_variants'] != VARIANTS or result['planned_configurations'] != expected
            or result['real_allocation_usd'] != '0' or result['promotion'] != 'hold_at_source_gate'):
        raise ValueError('C11 source-only recorder refuses outcomes or changed rules')


def record_failure(session, result, commit):
    validate_failure(result)
    version = sha(canonical(result['identity']).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(711111)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C11 SPY standard monthly option-expiration week', status='idea',
            config={'candidate': 'C11', 'research_family': 'c11', 'research_only': True, 'source_audit_only': True})
        session.add(strategy)
        session.flush()
    prior = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
        Trial.params['source_audit_version'].astext == version))
    if prior is not None:
        return prior.id
    split = HoldoutSplit('batch2-c11-v1', START, END)
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start, data_start=START, data_end=END,
        git_commit=commit, code_version='c11-source-audit-v1', completed_ts=datetime.now(UTC),
        params={'stage': 'data_quality_only_no_strategy_replay', 'candidate': 'C11',
                'source_audit_version': version, '_holdout': split.metadata(),
                'planned_variants': VARIANTS, 'planned_configurations': result['planned_configurations'],
                'identity': result['identity']},
        metrics={'audit_result': 'DATA_FAIL', 'source_receipt_sha256': result['receipt_sha256'],
                 'failures': result['failed_prerequisites'], 'training_cases_attempted': 0,
                 'final_holdout_attempts': 0, 'diagnostics_attempted': 0, **result['unmeasured']},
        notes='Calendar and full SPY action provenance unresolved; fractional close variant lacks execution '
              'support. Both variants and four training cases remain unattempted; no C11 returns, '
              'final, allocation or promotion. Decision: docs/research/31-c11-source-audit.md.')
    session.add(trial)
    session.flush()
    return trial.id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    report = ROOT / 'docs/research/31-c11-source-audit.json'
    # Preserve an already-recorded identity on a read-only rerun of this audit.
    if report.exists():
        saved = json.loads(report.read_bytes())
        ledger = saved.pop('ledger', None)
        if ledger and seal(saved) == result:
            result['ledger'] = ledger
            seal(result)
    if args.record_ledger:
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *INPUTS], cwd=ROOT).strip():
            raise ValueError('commit source audit inputs before ledger recording')
        # Ledger evidence itself is outside the preledger receipt.
        result.pop('ledger', None)
        seal(result)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial_id = record_failure(session, result, commit)
            recorded_commit = session.get(Trial, trial_id).git_commit
        result['ledger'] = {'source_failure_trial_id': trial_id, 'audit_git_commit': recorded_commit,
                            'preledger_receipt_sha256': result['receipt_sha256']}
        seal(result)
    encoded = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded) + 65536):
        target = ARCHIVE / ('audit-' + result['receipt_sha256'] + '.json')
        if target.exists() and target.read_bytes() != encoded:
            raise ValueError('refuse overwrite of immutable C11 audit')
        if not target.exists():
            target.write_bytes(encoded)
    report.write_bytes(encoded)
    print(json.dumps({'status': result['status'], 'failures': len(result['failed_prerequisites']),
        'source_failure_trial_id': result.get('ledger', {}).get('source_failure_trial_id'),
        'training_cases_attempted': 0, 'final_holdout_attempts': 0, 'receipt_sha256': result['receipt_sha256']}))


if __name__ == '__main__':
    main()
