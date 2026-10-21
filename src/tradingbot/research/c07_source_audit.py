"""C07 immutable source admission failure; no ranks, returns or replay."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.xlf_action_amendment import checked_bytes, sha
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c03_source_audit import inspect_source
from tradingbot.research.c06_sources import spy_source

ROOT = Path(__file__).resolve().parents[3]
START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
UNIVERSE = ('XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY')
VARIANTS = ({'lookback_sessions': 5, 'top_n': 3},
            {'lookback_sessions': 10, 'top_n': 3},
            {'lookback_sessions': 5, 'top_n': 1})
KEY = 'sweep_c07_sector_loser_reversal'
POLICY = {
    'universe': list(UNIVERSE), 'reference': 'SPY', 'variants': list(VARIANTS),
    'signal': 'Last exchange close of each NY Monday-Sunday week; sector trailing total return minus SPY; lowest negative residuals only; alphabetical ties.',
    'weights': '95% divided by top_n; absent eligible names leave their slots cash; $140 initial simulated allocation, 5% reserve, floor venue quantities, skip sub-$1 orders.',
    'entry': 'Next week first eligible session open; freeze signal and dollar targets at decision time; existing settled cash only.',
    'exit': 'Following week first session open, even for repeated names; delayed entry keeps this exit and is skipped if entry reaches it.',
    'cash': 'T+1 current-account counterfactual, completed-settlement availability, no ex-date dividend cash. Original issuer/action evidence required.',
    'actions': 'XLF/XLRE must pass the explicit source admission; no fake XLF split, extra ranking asset, fabricated fractional cash, excluded symbol or shortened sample.',
    'costs_bp': [5, 10], 'fees': 'EquityFeeBook 2026-09-17, explicitly a current-fee historical counterfactual.',
    'selection': 'Highest training net dollar P&L at 10 bp; variant order breaks ties; only a profitable frozen selection may attempt one final at 10 bp.',
    'inference': 'Count weeks rather than simultaneous ETF legs; no post-outcome VIX filter.',
    'prior_inspection': 'SPY overlaps previously inspected #5/#6/C01/C06 history; source reuse does not create fresh evidence or restore any consumed holdout.',
}
PROOFS = {
    'docs/research/12-c02-source-audit.json': '4717fcb61790db11df235207f4f1f911b93eb7b83314e86d39393edf57ec3388',
    'docs/research/17-xlf-action-amendment.json': '7ccb321e66d9035cfb1e8a79b1482f1e7076d7560699ec4fbb0c7359109d9ce4',
    'docs/research/13-equity-data-repair-calendar.json': '11b791a4edf1af2ba3d1d78d37c9d1de4cdaa00116c755ce198674c1bdd693c7',
}


def load_sector(directory: Path, symbol: str, expected_sha: str):
    if symbol not in UNIVERSE:
        raise ValueError('symbol outside fixed C07 universe')
    manifest_bytes = (directory / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['symbol'] != symbol or manifest['sha256'] != expected_sha:
        raise ValueError('source identity differs from original C02 capture')
    if (manifest['requested_start'] != START.date().isoformat()
            or manifest['requested_end_exclusive'] != END.date().isoformat()):
        raise ValueError('source bounds differ from preregistration')
    raw = checked_bytes(directory / 'raw.json', expected_sha)
    return {**manifest, 'manifest_sha256': sha(manifest_bytes)}, raw


def xlf_failure(receipt: dict) -> list[str]:
    payload = {k: v for k, v in receipt.items() if k != 'receipt_sha256'}
    if (sha(canonical(payload).encode()) != receipt.get('receipt_sha256')
            or receipt.get('receipt_sha256') != 'd46c011cff88c39a9c50b830502ea9f1784a75d9b83d1676011beb2e4229367b'):
        raise ValueError('XLF source receipt changed; requires a new reviewed amendment')
    if receipt['status'] != 'UNRESOLVED_DATA_FAILURE' or receipt['dataset_admitted'] is not False:
        raise ValueError('unexpected XLF admission state')
    return ['XLF in-kind source gate: ' + item for item in receipt['missing_evidence']]


def audit(root: Path = ROOT):
    proofs = {path: json.loads(checked_bytes(root / path, digest)) for path, digest in PROOFS.items()}
    sector_proof = proofs['docs/research/12-c02-source-audit.json']
    xlf = proofs['docs/research/17-xlf-action-amendment.json']
    failures = xlf_failure(xlf)
    # Verify the raw primary bytes behind the unresolved action, not just its label.
    for source in xlf['sources'].values():
        checked_bytes(root / source['path'], source['sha256'])
    spy_manifest, spy_data = spy_source(root)
    sessions = {date.fromisoformat(p['date']): SimpleNamespace(closes_at=datetime.fromisoformat(p['closes_at']))
                for p in spy_data['prices']}
    if len(sessions) != 5218 or len(sessions) != len(spy_data['prices']):
        raise ValueError('frozen SPY source calendar changed')
    sources, coverage = {}, {}
    for symbol in UNIVERSE:
        directory = root / 'data/equities/c02/sources' / symbol
        receipt, raw = load_sector(directory, symbol, sector_proof['identity']['yahoo_sha256'][symbol])
        sources[symbol] = {**receipt, 'path': str((directory / 'raw.json').relative_to(root))}
        coverage[symbol] = inspect_source(raw, symbol, sessions)
        if not coverage[symbol]['coverage_ok']:
            failures.append(f'{symbol}: incomplete or invalid source sessions')
    code_paths = ('src/tradingbot/research/c07_source_audit.py',
                  'src/tradingbot/research/c03_source_audit.py',
                  'src/tradingbot/research/c06_sources.py',
                  'src/tradingbot/data/xlf_action_amendment.py',
                  'src/tradingbot/data/free_history.py')
    code = {p: sha((root / p).read_bytes()) for p in code_paths}
    identity = {
        'source_sha256': {s: sources[s]['sha256'] for s in UNIVERSE},
        'source_manifest_sha256': {s: sources[s]['manifest_sha256'] for s in UNIVERSE},
        'proof_files_sha256': PROOFS, 'spy_data_sha256': spy_manifest['identity']['data_sha256'],
        'spy_receipt_sha256': spy_manifest['receipt_sha256'],
        'policy': POLICY, 'data_start': START.isoformat(), 'data_end': END.isoformat(),
    }
    split = HoldoutSplit('sweep-c07-v1:' + sha(canonical(identity).encode()), START, END)
    return {
        'candidate': 'C07', 'bead': 'tradingbot-a9d', 'status': 'DATA_FAIL',
        'identity': identity, 'split': split.metadata(), 'sources': sources, 'coverage': coverage,
        'reference': {'symbol': 'SPY', 'sessions': len(sessions), 'status': spy_manifest['status'],
                      'scope': 'Reviewed open/close and issuer distributions; no C07 signals computed.'},
        'failed_prerequisites': failures,
        'resolved_shared_evidence': ['SPY source-only price/dividend amendment', 'T+1 counterfactual settlement schedule'],
        'not_completed_after_failed_gate': ['Nine-sector issuer distributions/payment-date reconciliation',
            'Nine-sector independent same-basis price validation and actual-share conversions',
            'C07 reactor, risk/ledger replay, benchmark outcomes, training selection and final admission'],
        'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0,
        'planned_variants': list(VARIANTS), 'planned_training_costs_bp': [5, 10],
        'pnl': None, 'fees': None, 'drawdown': None, 'regimes': None, 'trade_count': None,
        'luck_p_value': None, 'promotion': 'none', 'code_sha256': code,
        'audit_code_sha256': code['src/tradingbot/research/c07_source_audit.py'],
    }


def record_failure(session, result, commit):
    if (result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']
            or result['training_cases_attempted'] != 0 or result['final_holdout_attempts'] != 0):
        raise ValueError('only a failed source audit without replay can be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    if split.metadata() != result['split']:
        raise ValueError('fixed C07 bounds changed')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703071)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C07 weekly sector loser reversal', status='idea',
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
                  data_start=START, data_end=END, git_commit=commit, code_version='c07-source-audit-v1',
                  completed_ts=datetime.now(UTC),
                  params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                          'source_audit_version': version, 'policy': POLICY, 'identity': result['identity']},
                  metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                           'training_cases_attempted': 0, 'final_holdout_attempts': 0},
                  notes='Data gate failed before rankings or returns. All three variants and six training cases '
                        'remain unattempted; performance and weekly dependence-aware inference are unmeasured. '
                        'No promotion, allocation or holdout consumption. Decision/blow-up record: docs/research/18-c07-source-audit.md.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    report_path = ROOT / 'docs/research/18-c07-source-audit.json'
    ledger_fields = ('data_failure_trial_id', 'strategy_id', 'audit_git_commit')
    if report_path.exists():
        saved = json.loads(report_path.read_text())
        if {k: v for k, v in saved.items() if k not in ledger_fields} == result:
            result.update({k: saved[k] for k in ledger_fields if k in saved})
    if args.record_ledger:
        tracked = list(result['code_sha256']) + list(PROOFS)
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *tracked], cwd=ROOT).strip():
            raise ValueError('commit the source audit and evidence before recording its ledger receipt')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            result.update({'data_failure_trial_id': trial.id, 'strategy_id': trial.strategy_id,
                           'audit_git_commit': trial.git_commit})
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    archive = ROOT / 'data/research/c07'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded.encode()) + 65536):
        archive.mkdir(parents=True, exist_ok=True)
        (archive / 'audit.json').write_text(encoded)
    report_path.write_text(encoded)
    print(json.dumps({'status': result['status'], 'trial': result.get('data_failure_trial_id'),
                      'sessions_per_sector': {s: c['sessions'] for s, c in result['coverage'].items()},
                      'training_cases_attempted': 0, 'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
