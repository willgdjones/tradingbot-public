"""C12 failed source admission and null ledger receipt; never a strategy run."""
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
from tradingbot.db.session import get_engine, session_scope
from tradingbot.research.c12_capture import ROOT, ARCHIVE, sha
from tradingbot.research.c12_sources import audit_sources

START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
KEY = 'batch2_c12_spy_scheduled_macro'
VARIANTS = ({'release': 'BLS_Employment_Situation'}, {'release': 'BLS_CPI'})
REPORT = 'docs/research/32-c12-source-audit.json'
POLICY = {
    'universe': ['SPY'], 'ordered_variants': list(VARIANTS), 'costs_bp_per_side': [5, 10],
    'decision': 'Announced date D must be an equity session. Decide at close two sessions before D; enter preceding open; exit first open after D.',
    'revisions': 'Only notices known before decision supersede/cancel. After decision preserve original exit. One entry per family/reference month; skip held overlaps. Missing/contradictory provenance fails.',
    'exclusions': 'Exclude holding windows intersecting scheduled FOMC decision session or its preceding equity session, from advance Fed notices known by decision.',
    'controls': 'Training only: shift both open endpoints exactly seven calendar days earlier; both must be sessions, same interval count and wholly in partition. Exclude either BLS family and same FOMC windows; never roll/search. Diagnostics only.',
    'sizing': '140 virtual USD; min(95% decision equity, 140) frozen target; common 5% reserve and .01 fee reserve. Clip total exposure at rounded adverse limit to target, settled cash and slot; floor 1e-9 quantities; minimum $1.',
    'cash_actions': 'Pre-ex ordinary entitlements are receivables until first open after documented payable. Sales after completed published T+1 settlement. Amendment 21 requires complete inventory and primary advance notice; pre-action exit, flat through payable, cancel event with no late restart.',
    'selection': 'Largest positive complete 10bp training net dollars, ordered ties; freeze before sole higher-cost final in canonical c12 family. Failed/interrupted final consumed.',
    'fees_risk': 'EquityFeeBook 2026-09-17 current-account counterfactual; unchanged shared risk engine and PRD6.',
}
FAILURES = [
    'Full BLS decision-time announcement/revision chronology is not established, including 2013/2025 shutdown suspensions and the same-day February 2026 Employment revision.',
    'Current and January 2026 retrospective calendars cannot establish earlier cancellation/replacement publication times; missing October 2025 issues cannot remove the original event denominator.',
]


def configurations():
    return [{**variant, 'costs_bp_per_side': cost, 'state': 'unattempted_source_gate_failed'}
            for variant in VARIANTS for cost in (5, 10)]


def audit(root=ROOT, archive=ARCHIVE):
    evidence = audit_sources(root, archive)
    code_paths = ('src/tradingbot/research/c12_source_audit.py', 'src/tradingbot/research/c12_sources.py',
                  'src/tradingbot/research/c12_capture.py', 'src/tradingbot/research/c06_sources.py')
    proofs = ('docs/research/25-candidate-shortlist.md', 'docs/research/32-c12-source-plan.md',
              'docs/research/32-c12-evidence.json', 'docs/research/21-corporate-action-blackout.md')
    code = {p: sha((root / p).read_bytes()) for p in code_paths}
    discovery = {p: sha((archive / p).read_bytes()) for p in (
        'web-exception-discovery.txt', 'web-late-calendar-discovery.txt', 'web-late-calendar-excerpt.txt')}
    identity = {'source_sha256': {k: v['sha256'] for k, v in evidence['public_sources'].items()},
                'source_manifest_sha256': {k: v['manifest_sha256'] for k, v in evidence['public_sources'].items()},
                'spy_receipt_sha256': evidence['spy']['receipt_sha256'],
                'spy_data_sha256': evidence['spy']['data_sha256'],
                'proofs_sha256': {p: sha((root / p).read_bytes()) for p in proofs},
                'discovery_text_sha256': discovery,
                'discovery_text_admitted_as_original_raw_html': False,
                'policy': POLICY, 'data_start': START.isoformat(), 'data_end': END.isoformat()}
    split = HoldoutSplit('batch2-c12-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C12', 'bead': 'tradingbot-lna', 'status': 'DATA_FAIL',
        'dataset_admitted': False, 'identity': identity, 'split': split.metadata(),
        'evidence': evidence, 'failed_prerequisites': FAILURES,
        'not_completed_after_failed_gate': ['Full BLS monthly announcement/revision reconciliation',
            'Complete as-of Fed exclusion reconciliation', 'Full SPY share-action inventory/admission',
            'Pure strategy and shared replay/risk/ledger implementation',
            'Four training cases, shifted controls, winner selection, final and inference'],
        'planned_configurations': configurations(), 'strategy_outcomes_inspected': False,
        'training_cases_attempted': 0, 'final_holdout_attempts': 0,
        'pnl': None, 'fees': None, 'drawdown': None, 'regimes': None, 'trade_count': None,
        'luck_p_value': None, 'promotion': 'none', 'code_sha256': code}


def record_failure(session, result, commit):
    if (result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']
            or result['dataset_admitted'] or result['strategy_outcomes_inspected']
            or result['training_cases_attempted'] != 0 or result['final_holdout_attempts'] != 0
            or result['planned_configurations'] != configurations()
            or any(result[k] is not None for k in ('pnl', 'fees', 'drawdown', 'regimes', 'trade_count', 'luck_p_value'))):
        raise ValueError('only failed source admission without performance can be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    if split.metadata() != result['split']:
        raise ValueError('fixed C12 bounds changed')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703121)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C12 SPY scheduled macro announcement risk', status='idea',
                            config={'research_only': True, 'source_audit_only': True, 'policy': POLICY})
        session.add(strategy)
        session.flush()
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
                          Trial.params['source_audit_version'].astext == version))
    if old is not None:
        return old
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start,
        data_start=START, data_end=END, git_commit=commit, code_version='c12-source-audit-v1',
        completed_ts=datetime.now(UTC),
        params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                'source_audit_version': version, 'policy': POLICY, 'identity': result['identity'],
                'planned_configurations': result['planned_configurations']},
        metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                 'training_cases_attempted': 0, 'final_holdout_attempts': 0},
        notes='Causal release-calendar admission failed. Both variants and four training cases remain '
              'unattempted; return metrics null, no final consumption or promotion. '
              'Decision and account-risk review: docs/research/32-c12-source-audit.md.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    path = ROOT / REPORT
    ledger_fields = ('data_failure_trial_id', 'strategy_id', 'audit_git_commit')
    if path.exists():
        saved = json.loads(path.read_bytes())
        if {k: v for k, v in saved.items() if k not in ledger_fields} == result:
            result.update({k: saved[k] for k in ledger_fields if k in saved})
    if args.record_ledger:
        tracked = list(result['code_sha256']) + list(result['identity']['proofs_sha256'])
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *tracked], cwd=ROOT).strip():
            raise ValueError('commit code and evidence before ledger recording')
        engine = get_engine()
        if engine.url.port != 5433 or engine.url.database != 'tradingbot':
            raise ValueError('source ledger requires designated local database')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            result.update(data_failure_trial_id=trial.id, strategy_id=trial.strategy_id, audit_git_commit=trial.git_commit)
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded.encode()) + 65536):
        (ARCHIVE / 'audit.json').write_text(encoded)
    path.write_text(encoded)
    print(json.dumps({'status': result['status'], 'trial': result.get('data_failure_trial_id'),
                      'training_cases_attempted': 0, 'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
