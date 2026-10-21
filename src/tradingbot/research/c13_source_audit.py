"""C13 source/capital audit; no signal, return calculation or order path."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.alpaca_options import audit as audit_options
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import get_engine, session_scope
from tradingbot.research.c13_capture import ROOT, ARCHIVE, SOURCES, ACCOUNT_FIELDS, load, sha

START = datetime(2024, 2, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
KEY = 'batch2_c13_earnings_straddle'
REPORT = 'docs/research/36-c13-source-audit.json'
REVIEW = 'docs/research/36-c13-source-review.json'
INDEX = 'docs/research/batch2-sources/2026-10-01-candidate-index.json'
HARNESS = 'docs/research/10-options-data-harness-results.json'
VARIANTS = ({'entry_sessions_before_earnings': 3}, {'entry_sessions_before_earnings': 5})
POLICY = {
    'universe': ['F', 'NOK', 'SNAP'], 'ordered_variants': list(VARIANTS),
    'adverse_per_share_usd': ['0.01', '0.02'], 'virtual_slot_usd': '140',
    'entry_cap': 'min(35% of decision equity,49) including entry/exit fee reserves and settled cash',
    'contract': 'One long call and one long put, same strike/expiry; standard American USD 100-share only',
    'selection': 'Original prior-close ATM rule and expiry selection; no cheaper strike/ticker fallback',
    'execution': 'Original regular-open BBO <=30s age, adequate size, legs <=1s apart; adverse verified tick rounding; partial second leg fails winner eligibility',
    'exit': 'First regular open strictly after frozen announced release time, >=2 sessions before expiry; no later extension',
    'source_gate': 'Full historical chain/BBO, earnings chronology, underlying/actions, ticks, fees and settlement required before outcomes',
    'actions': 'Amendment21 causal OCC/underlying notices, pre-action exit, no late restart',
    'final': 'One eligible positive higher-cost training winner, fixed ordered ties; sole higher-cost final, failed/interrupted consumed',
    'risk': 'Unchanged PRD6 and accepted PRD9; no activation, order, account, capital or key change',
}
FAILURES = [
    'The approved source bundle has no historical executable BBO, sizes or synchronized two-leg entry/exit/liquidation observations for F/NOK/SNAP.',
    'Current active/inactive catalogs do not establish decision-time historical listings, delisted series, deliverable changes or penny-program membership.',
]
METRICS = ('pnl', 'fees', 'drawdown', 'regimes', 'trade_count', 'luck_p_value')
CODE_PATHS = tuple('src/tradingbot/' + p for p in (
    'research/c13_source_audit.py', 'research/c13_capture.py', 'data/alpaca_options.py',
    'data/archive.py', 'data/disk_budget.py', 'data/alpaca_history.py', 'data/transport.py',
    'data/free_history.py', 'data/bulk_history.py', 'forward/c05_readiness.py',
    'backtest/holdout.py', 'db/models.py', 'db/session.py', 'risk/limits.py'))


def configurations():
    return [{**variant, 'adverse_per_share_usd': cost,
             'state': 'unattempted_source_gate_failed'}
            for variant in VARIANTS for cost in ('0.01', '0.02')]


def capital_bound(equity=D('140'), settled_cash=D('140')):
    """Necessary pre-fee bound only: no quote screening or affordability verdict."""
    if any(not v.is_finite() or v < 0 for v in (equity, settled_cash)):
        raise ValueError('finite nonnegative equity and settled cash required')
    cap = min(D('.35') * equity, D('49'), settled_cash)
    adverse = D('100') * D('2') * D('.02')
    return {'opening_budget_usd': str(cap), 'higher_cost_opening_adverse_usd': str(adverse),
            'combined_asks_upper_bound_before_fees_per_share': str(max(D(0), (cap-adverse)/D(100))),
            'positive_premiums_possible_before_fees': cap > adverse,
            'fees_and_adverse_tick_rounding_reduce_bound': True,
            'necessary_condition_only': True, 'affordable_event_count': None}


def verify_scope(root=ROOT):
    index = json.loads((root / INDEX).read_bytes())
    for key, path_key in (('specification_sha256', 'specification'),
                          ('source_register_sha256', 'source_register')):
        if sha((root / index[path_key]).read_bytes()) != index[key]:
            raise ValueError('Original batch2 source/specification changed')
    candidate = next(c for c in index['candidates'] if c['candidate'] == 'C13')
    split = HoldoutSplit('batch2-c13-v1', START, END)
    if (candidate['universe'] != POLICY['universe'] or candidate['ordered_variants'] != list(VARIANTS)
            or candidate['split'] != split.metadata()
            or candidate['training_cost_cases'] != [{'adverse_per_share_usd': n} for n in ('0.01', '0.02')]
            or candidate['virtual_cash_usd'] != '140' or candidate['real_allocation_usd'] != '0'
            or candidate['selection_cost_case_index'] != 1 or candidate['max_final_attempts'] != 1):
        raise ValueError('Original C13 bounds, sizing or cases changed')
    return candidate


def verify_harness(root=ROOT):
    prior = json.loads((root / HARNESS).read_bytes())
    if prior['strategy_evaluation'] is not False or len(prior['reports']) != 8:
        raise ValueError('Unexpected original options probe')
    summaries = []
    for expected in prior['reports']:
        directory = root / expected['directory']
        if not directory.resolve().is_relative_to((root / 'data/options').resolve()):
            raise ValueError('Options archive outside approved tree')
        observed = audit_options(directory)
        keys = ('dataset', 'request', 'complete', 'pages', 'records', 'response_set_sha256',
                'semantics', 'retrieved_first', 'retrieved_last', 'executable_fill_evidence',
                'historical_chain_membership', 'historical_bbo')
        if any(observed[k] != expected[k] for k in keys):
            raise ValueError('Original options evidence changed')
        if any(observed[k] for k in ('executable_fill_evidence', 'historical_chain_membership', 'historical_bbo')):
            raise ValueError('New execution evidence requires separate source review')
        files = [directory / 'manifest.json', *sorted(directory.glob('page-*.parquet'))]
        summaries.append({**{k: observed[k] for k in keys}, 'directory': expected['directory'],
                          'file_sha256': {str(p.relative_to(root)): sha(p.read_bytes()) for p in files}})
    if sum(p['pages'] for p in summaries) != 11 or sum(p['records'] for p in summaries) != 38823:
        raise ValueError('Original options archive scope changed')
    return summaries


def audit(root=ROOT, archive=ARCHIVE):
    candidate = verify_scope(root)
    review = json.loads((root / REVIEW).read_bytes())
    if set(review['sources']) != set(SOURCES) or review['dataset_admitted'] is not False:
        raise ValueError('Source review must cover exact failed-admission scope')
    sources = {}
    for key in SOURCES:
        meta, raw = load(key, archive)
        expected = review['sources'][key]
        manifest = archive / key / 'manifest.json'
        if (meta['status'] != expected['status'] or meta['sha256'] != expected['sha256']
                or sha(manifest.read_bytes()) != expected['manifest_sha256']):
            raise ValueError('Unreviewed source bytes or response metadata')
        sources[key] = {**meta, 'path': str((archive / key / 'raw').relative_to(root)),
                        'manifest_sha256': expected['manifest_sha256'], 'review': expected['review']}
    account = json.loads((archive / 'paper-capability/raw').read_bytes())
    if set(account) != set(ACCOUNT_FIELDS):
        raise ValueError('Account receipt exceeds capability whitelist')
    # Raw documentation remains the authority. This is a current-paper observation,
    # not a certified live entitlement or permission to submit an order.
    account_check = (account['status'] == 'ACTIVE' and account['currency'] == 'USD'
                     and type(account['options_approved_level']) is int
                     and type(account['options_trading_level']) is int
                     and account['options_approved_level'] >= 2
                     and account['options_trading_level'] >= 2
                     and all(account[k] is False for k in
                             ('account_blocked', 'trading_blocked', 'trade_suspended_by_user')))
    probes = verify_harness(root)
    proofs = ('docs/research/25-candidate-shortlist.md', INDEX, HARNESS,
              'docs/research/batch2-sources/2026-10-01-sources.md',
              'docs/research/36-c13-source-plan.md', REVIEW,
              'docs/research/21-corporate-action-blackout.md', 'PRD.md')
    identity = {'policy': POLICY, 'candidate': candidate,
                'proofs_sha256': {p: sha((root / p).read_bytes()) for p in proofs},
                'sources': {k: {f: v[f] for f in ('sha256', 'manifest_sha256', 'capture_code_sha256')}
                            for k, v in sources.items()},
                'harness_files_sha256': {p: h for probe in probes for p, h in probe['file_sha256'].items()}}
    split = HoldoutSplit('batch2-c13-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C13', 'bead': 'tradingbot-0cm', 'status': 'DATA_FAIL',
            'dataset_admitted': False, 'identity': identity, 'split': split.metadata(),
            'sources': sources, 'harness_reaudit': probes,
            'paper_capability': {'fields': account, 'level2_available_now': account_check,
                                 'live_capability_checked': False, 'permission_change': False},
            'capital': capital_bound(), 'fee_review': review['fee_review'],
            'failed_prerequisites': FAILURES,
            'not_completed_after_failed_gate': [
                'Complete F/NOK/SNAP decision-time earnings announcement/revision denominator',
                'Historical underlying price/action inventory and causal OCC notices/Amendment21 exits',
                'Contemporaneous standard deliverable, tick and contract tradability inventory',
                'Exact account fee/reserve model, exercise failure and completed-cash settlement model',
                'Pure shared reactor/execution implementation, four training cases, winner selection and final'],
            'planned_configurations': configurations(), 'strategy_outcomes_inspected': False,
            'training_cases_attempted': 0, 'final_holdout_attempts': 0,
            **{k: None for k in METRICS}, 'promotion': 'none',
            'code_sha256': {p: sha((root / p).read_bytes()) for p in CODE_PATHS}}


def record_failure(session, result, commit):
    if (result['status'] != 'DATA_FAIL' or result['failed_prerequisites'] != FAILURES
            or result['dataset_admitted'] or result['strategy_outcomes_inspected']
            or result['training_cases_attempted'] != 0 or result['final_holdout_attempts'] != 0
            or result['planned_configurations'] != configurations()
            or result['identity'].get('policy') != POLICY or result['promotion'] != 'none'
            or any(result[k] is not None for k in METRICS)):
        raise ValueError('only frozen failed source admission without performance can be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    if split.metadata() != result['split']:
        raise ValueError('fixed C13 bounds changed')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703131)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C13 earnings-uncertainty long straddle', status='idea',
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
        data_start=START, data_end=END, git_commit=commit, code_version='c13-source-audit-v1',
        completed_ts=datetime.now(UTC),
        params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                'source_audit_version': version, 'policy': POLICY, 'identity': result['identity'],
                'planned_configurations': result['planned_configurations'],
                'code_sha256': result['code_sha256']},
        metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                 'training_cases_attempted': 0, 'final_holdout_attempts': 0},
        notes='Historical options BBO/chain admission failed. Four training cases unattempted; '
              'performance null, no final or promotion. Affordability is unknown, not zero. '
              'Decision/account-risk review: docs/research/36-c13-source-audit.md.')
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
            raise ValueError('commit code and reviewed evidence before ledger recording')
        engine = get_engine()
        if engine.url.port != 5433 or engine.url.database != 'tradingbot':
            raise ValueError('source ledger requires designated local database')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            result.update(data_failure_trial_id=trial.id, strategy_id=trial.strategy_id,
                          audit_git_commit=trial.git_commit)
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded.encode()) + 65536):
        (ARCHIVE / 'audit.json').write_text(encoded)
    path.write_text(encoded)
    print(json.dumps({'status': result['status'], 'trial': result.get('data_failure_trial_id'),
                      'training_cases_attempted': 0, 'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
