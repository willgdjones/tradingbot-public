"""C14 historical-source and cash-collateral audit; never replays a strategy."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import get_engine, session_scope
from tradingbot.research import c13_source_audit as prior
from tradingbot.research.c13_capture import ROOT, ARCHIVE, sha

START, END = prior.START, prior.END
KEY = 'batch2_c14_cash_secured_put'
REPORT = 'docs/research/37-c14-source-audit.json'
REVIEW = 'docs/research/37-c14-source-review.json'
VARIANTS = ({'hold_sessions': 5}, {'hold_sessions': 10})
POLICY = {
    'universe': ['F', 'NOK', 'OPEN', 'PLUG', 'SNDL'],
    'ordered_variants': list(VARIANTS), 'adverse_per_share_usd': ['0.01', '0.02'],
    'virtual_slot_usd': '140', 'contract': 'One standard American USD put on exactly 100 shares',
    'signal': 'Weekly final regular close: positive 63-session and negative 5-session total return, within partition',
    'ranking': 'Lowest 5-session return then ticker; select once, no fallback',
    'selection': 'Expiry first: 21-35 days after S, nearest 28 days, earlier tie; then highest listed strike <=.95 * prior raw close',
    'entry': 'Next regular open S; full strike * 100 plus all fee/assignment/stock-exit reserves <=min(.95 * decision equity,140,settled cash) before premium',
    'execution': 'Historical first BBO at/after 09:30 ET by 09:35, <=30s old, adequate size; buy ask plus cost, sell bid less cost floored zero; adverse verified tick rounding',
    'exit': 'Original S+5 or S+10 session open, at least two sessions before expiry; cash/closure delay cannot extend exit',
    'assignment': 'Source-supported early assignment/notification model required; debit full strike obligation, book 100 shares, liquidate next eligible open with equity fees/costs and actual cash/entitlement rules',
    'actions': 'Amendment21 timely underlying/OCC notices and executable pre-action exit of options and assigned shares; no late restart',
    'cash': 'No borrowing, premium-funded collateral, fractional contracts, interest, wheel, covered call, roll, overlap or averaging down',
    'final': 'One eligible positive higher-cost training winner, ordered ties; sole higher-cost final, failed/interrupted consumed',
    'risk': 'Unchanged PRD6 and accepted PRD9; no activation, order, account, capital, permission or key change',
}
FAILURES = [
    'The approved bundle has no historical executable BBO, sizes or liquidation marks for F/NOK/OPEN/PLUG/SNDL.',
    'Current catalogs do not establish complete decision-time historical listings, delisted series, standard deliverables or per-series tick eligibility.',
    'The required historical early-assignment/notification and resulting stock/cash lifecycle model is not admitted; no-assignment cannot be assumed.',
]
METRICS = ('pnl', 'fees', 'drawdown', 'regimes', 'trade_count', 'luck_p_value')
CODE_PATHS = (*prior.CODE_PATHS, 'src/tradingbot/research/c14_source_audit.py')


def configurations():
    return [{**variant, 'adverse_per_share_usd': cost,
             'state': 'unattempted_source_gate_failed'}
            for variant in VARIANTS for cost in ('0.01', '0.02')]


def capital_bound(equity=D('140'), settled_cash=D('140')):
    """Necessary bound before UNKNOWN reserves; neither quote nor event screen."""
    if any(not value.is_finite() or value < 0 for value in (equity, settled_cash)):
        raise ValueError('finite nonnegative equity and settled cash required')
    budget = min(D('.95') * equity, D('140'), settled_cash)
    return {'collateral_budget_before_reserves_usd': str(budget),
            'strike_upper_bound_before_reserves_usd': str(budget / D('100')),
            'absolute_slot_strike_bound_before_reserves_usd': '1.40',
            'premium_credit_used_for_collateral': False,
            'required_reserve_usd': None, 'reserves_reduce_bound': True,
            'necessary_condition_only': True, 'affordable_event_count': None,
            'eligible_contract_count': None,
            'illustrative_1_50_strike_obligation_usd': '150',
            'illustrative_1_50_strike_fits_before_reserves': D('150') <= budget}


def verify_scope(root=ROOT):
    index = json.loads((root / prior.INDEX).read_bytes())
    for checksum, path in (('specification_sha256', 'specification'),
                           ('source_register_sha256', 'source_register')):
        if sha((root / index[path]).read_bytes()) != index[checksum]:
            raise ValueError('Original batch2 source/specification changed')
    candidate = next(c for c in index['candidates'] if c['candidate'] == 'C14')
    split = HoldoutSplit('batch2-c14-v1', START, END)
    if (candidate['universe'] != POLICY['universe']
            or candidate['ordered_variants'] != list(VARIANTS)
            or candidate['split'] != split.metadata()
            or candidate['training_cost_cases'] != [{'adverse_per_share_usd': c} for c in ('0.01', '0.02')]
            or candidate['virtual_cash_usd'] != '140' or candidate['real_allocation_usd'] != '0'
            or candidate['selection_cost_case_index'] != 1 or candidate['max_final_attempts'] != 1):
        raise ValueError('Original C14 bounds, sizing or cases changed')
    return candidate


def verify_reuse(root=ROOT, archive=ARCHIVE):
    review = json.loads((root / REVIEW).read_bytes())
    if (review['candidate'] != 'C14' or review['dataset_admitted'] is not False
            or review['assignment']['model_admitted'] is not False
            or review['fees']['model_admitted'] is not False):
        raise ValueError('C14 failed-source review changed')
    for name, expected_path in (('reused_audit', prior.REPORT), ('reused_source_review', prior.REVIEW)):
        if (review[name] != expected_path
                or sha((root / expected_path).read_bytes()) != review[name + '_sha256']):
            raise ValueError('Unreviewed reused source receipt')
    # This reads original raw bytes/manifests and capture-code snapshots, plus
    # every original option archive page. It makes no network or ledger call.
    observed = prior.audit(root, archive)
    saved = json.loads((root / prior.REPORT).read_bytes())
    for field in ('data_failure_trial_id', 'strategy_id', 'audit_git_commit'):
        saved.pop(field, None)
    if observed != saved:
        raise ValueError('Reused options evidence or dependencies changed')
    for field in ('assignment', 'fees'):
        item = review[field]
        if item['source_sha256'] != observed['sources'][item['source_key']]['sha256']:
            raise ValueError('C14 mechanics source changed')
    return observed, review


def audit(root=ROOT, archive=ARCHIVE):
    candidate = verify_scope(root)
    evidence, review = verify_reuse(root, archive)
    account = evidence['paper_capability']['fields']
    level1 = (account['status'] == 'ACTIVE' and account['currency'] == 'USD'
              and all(type(account[k]) is int and account[k] >= 1
                      for k in ('options_approved_level', 'options_trading_level'))
              and all(account[k] is False for k in
                      ('account_blocked', 'trading_blocked', 'trade_suspended_by_user')))
    proofs = (*evidence['identity']['proofs_sha256'], prior.REPORT,
              'docs/research/37-c14-source-plan.md', REVIEW)
    identity = {'policy': POLICY, 'candidate': candidate,
                'proofs_sha256': {p: sha((root / p).read_bytes()) for p in proofs},
                'reused_source_identity': evidence['identity']['sources'],
                'harness_files_sha256': evidence['identity']['harness_files_sha256']}
    split = HoldoutSplit('batch2-c14-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C14', 'bead': 'tradingbot-ddw', 'status': 'DATA_FAIL',
            'dataset_admitted': False, 'identity': identity, 'split': split.metadata(),
            'sources': evidence['sources'], 'harness_reaudit': evidence['harness_reaudit'],
            'source_reuse_review': review,
            'paper_capability': {'fields': account, 'level1_available_at_capture': level1,
                                 'retrieved_at': evidence['sources']['paper-capability']['retrieved_at'],
                                 'live_capability_checked': False, 'permission_change': False,
                                 'cash_adequacy_established': False},
            'capital': capital_bound(), 'failed_prerequisites': FAILURES,
            'not_completed_after_failed_gate': [
                'Five-name historical underlying raw/adjusted prices and full action/delisting inventory',
                'Causal OCC deliverable notices and executable Amendment21 exits',
                'Historical chains, tradability, BBO/size/liquidation marks and ticks',
                'Exact shared-account option/assignment/stock fees, reserves and completed cash settlement',
                'Source-supported early assignment/notification model and stock liquidation lifecycle',
                'Shared strategy reactor, signals, four training cases, winner selection and final'],
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
            or result['capital'] != capital_bound()
            or any(result[k] is not None for k in METRICS)):
        raise ValueError('only frozen failed source admission without performance can be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    if split.metadata() != result['split']:
        raise ValueError('fixed C14 bounds changed')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703141)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C14 conditional cash-secured cheap-stock put', status='idea',
                            allocation_usd=D('0'),
                            config={'research_only': True, 'source_audit_only': True, 'policy': POLICY})
        session.add(strategy)
        session.flush()
    if strategy.status != 'idea' or strategy.allocation_usd != 0:
        raise ValueError('source-only recording cannot alter an active or funded strategy')
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
                          Trial.params['source_audit_version'].astext == version))
    if old is not None:
        return old
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start,
        data_start=START, data_end=END, git_commit=commit, code_version='c14-source-audit-v1',
        completed_ts=datetime.now(UTC),
        params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                'source_audit_version': version, 'policy': POLICY, 'identity': result['identity'],
                'planned_configurations': result['planned_configurations'],
                'code_sha256': result['code_sha256']},
        metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                 'capital': result['capital'], 'training_cases_attempted': 0, 'final_holdout_attempts': 0},
        notes='Historical options BBO/chain/assignment admission failed. Four training cases unattempted; '
              'performance null, no final or promotion. Affordability is unknown, not zero. '
              'Decision/account-risk review: docs/research/37-c14-source-audit.md.')
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
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': result['status'], 'trial': result.get('data_failure_trial_id'),
                      'training_cases_attempted': 0, 'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
