"""C16 source-only audit: accepted TLT prices, unavailable causal yield evidence."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.total_return_data import (
    ROOT, sha, alpaca_prices, nasdaq_prices, dividend_adjusted_reference, cross_check,
)

ARCHIVE = ROOT/'data/research/c16-yield-curve'
PLAN = ROOT/'docs/research/43-c16-yield-curve-plan.md'
PRICE_SOURCE = ROOT/'data/research/c10-total-return/source.json'
PRICE_SHA = '0580a449609e4a6597d6ac1d8988c349e60c87473e9c4aded6e50b16e4d7ddbd'
START, END = datetime(2006, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
VARIANTS, COSTS = ('0.00', '1.00'), (5, 10)
KEY = 'sweep_c16_yield_curve_source_v1'
UNMEASURED = ('pnl', 'fees', 'trade_count', 'drawdown', 'regimes', 'luck_p_value',
              'benchmarks', 'exposure', 'turnover', 'settlement_delays', 'slope_occupancy',
              'historical_stale_observation_decisions')


def configurations():
    return [{'threshold_percentage_points': v, 'cost_bp': bp,
             'state': 'unattempted_signal_evidence_gap'} for v in VARIANTS for bp in COSTS]


def require_same(actual, expected):
    if actual != expected:
        raise ValueError('C16 archived evidence differs from revalidated source')


def validate_gap(evidence):
    if (evidence.get('status') != 'SIGNAL_EVIDENCE_GAP'
            or evidence.get('required_series') != ['DGS10', 'DGS2']
            or evidence.get('vintage_records_archived') != 0
            or evidence.get('absence_of_valid_historical_observation_proven') is not False
            or evidence.get('current_revised_values_used') is not False
            or evidence.get('new_key_created') is not False
            or evidence.get('data_spend_usd') != '0'):
        raise ValueError('causal evidence gap cannot be revised-price substitution or historical cash absence')


def audit():
    raw = PRICE_SOURCE.read_bytes()
    require_same(sha(raw), PRICE_SHA)
    source = json.loads(raw)
    inputs = dict(source['inputs'])
    inputs[str(PRICE_SOURCE.relative_to(ROOT))] = PRICE_SHA
    for path, digest in inputs.items():
        require_same(sha((ROOT/path).read_bytes()), digest)
    prices = {date.fromisoformat(r['date']): Decimal(r['quote']['close']) for r in source['prices']}
    if (len(prices) != 5218 or len(source['prices']) != 5218
            or min(prices) != date(2006, 1, 3) or max(prices) != date(2026, 9, 30)):
        raise ValueError('C16 original full TLT coverage required')
    references = {}
    for adjustment in ('all', 'split'):
        meta = source['secondary']['alpaca_'+adjustment]
        rows, actual = alpaca_prices(ROOT/meta['path'], adjustment=adjustment)
        require_same(actual, meta)
        references[adjustment] = rows['TLT']
    # The immutable input map was checked above; this reads an existing capture.
    reference, meta = nasdaq_prices('TLT', START.date(), END.date()-timedelta(days=1),
                                   archive=PRICE_SOURCE.parent)
    require_same(meta, source['secondary']['nasdaq'])
    check = cross_check(prices, dividend_adjusted_reference(
        reference, references['all'], references['split']))
    require_same(check, source['crosscheck'])
    if not check['passed']:
        raise ValueError('C16 signal-gap audit requires independently accepted prices')
    evidence = json.loads((ARCHIVE/'investigation.json').read_bytes())
    validate_gap(evidence)
    attempts = json.loads((ARCHIVE/'additional-attempts.json').read_bytes())
    if (len(attempts) != 2 or {r['name'] for r in attempts} != {'dgs2-form', 'dgs10-graph-probe'}
            or any(r['status'] != 'request_failed' or r['response_bytes'] != 0 for r in attempts)):
        raise ValueError('unexpected archived macro request result; review evidence before recording a gap')
    for name in ('investigation.json', 'additional-attempts.json'):
        path = ARCHIVE/name
        inputs[str(path.relative_to(ROOT))] = sha(path.read_bytes())
    identity = {'inputs': inputs, 'universe': ['TLT'], 'signal_series': ['DGS10', 'DGS2'],
                'thresholds_percentage_points': list(VARIANTS), 'costs_bp': list(COSTS),
                'source_start': START.isoformat(), 'source_end_exclusive': END.isoformat()}
    digest = sha(json.dumps(identity, sort_keys=True).encode())
    return {'candidate': 'C16', 'status': 'SIGNAL_EVIDENCE_GAP', 'identity': identity,
        'split': HoldoutSplit('c16-source:'+digest, START, END).metadata(),
        'price_status': 'SOURCE_PASS', 'price_sessions': len(prices), 'price_crosscheck': check,
        'macro_evidence': evidence, 'additional_attempts': attempts,
        'dataset_admitted': False, 'planned_configurations': configurations(),
        'strategy_outcomes_inspected': False, 'training_cases_attempted': 0,
        'final_holdout_attempts': 0, 'actual_allocation_usd': '0',
        **{k: None for k in UNMEASURED},
        'code_sha256': {p: sha((ROOT/p).read_bytes()) for p in (
            'src/tradingbot/research/c16_yield_curve.py', 'src/tradingbot/research/total_return_data.py',
            'src/tradingbot/data/free_history.py', 'src/tradingbot/backtest/holdout.py')}}


def write_once(name, result):
    raw = (json.dumps(json_value(result), sort_keys=True, indent=2)+'\n').encode()
    path = ARCHIVE/name
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C16 source evidence')
        if not path.exists():
            path.write_bytes(raw)
    return sha(raw)


def record_gap(session, result, commit):
    validate_gap(result['macro_evidence'])
    if (result['status'] != 'SIGNAL_EVIDENCE_GAP' or result['price_status'] != 'SOURCE_PASS'
            or not result['price_crosscheck']['passed'] or result['dataset_admitted']
            or result['strategy_outcomes_inspected'] or result['training_cases_attempted'] != 0
            or result['final_holdout_attempts'] != 0 or result['planned_configurations'] != configurations()
            or result['actual_allocation_usd'] != '0'
            or any(result[k] is not None for k in UNMEASURED)):
        raise ValueError('only unmeasured signal-evidence gap with accepted prices may be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    require_same(split.metadata(), result['split'])
    version = sha(json.dumps(result, sort_keys=True).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703016)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C16 yield-curve causal source audit', status='idea',
            allocation_usd=Decimal(0), config={'research_only': True, 'source_audit_only': True,
                                             'candidate': 'C16', 'research_family': 'c16'})
        session.add(strategy)
        session.flush()
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
        Trial.params['source_audit_version'].astext == version))
    if old is not None:
        return old
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start, data_start=START, data_end=END,
        git_commit=commit, code_version='c16-source-audit-v1', completed_ts=datetime.now(UTC),
        params={'stage': 'causal_signal_evidence_only_no_strategy_replay', '_holdout': split.metadata(),
                'source_audit_version': version, 'identity': result['identity'],
                'code_sha256': result['code_sha256'], 'planned_configurations': configurations()},
        metrics={'audit_result': 'SIGNAL_EVIDENCE_GAP', 'price_status': 'SOURCE_PASS',
                 'training_cases_attempted': 0, 'final_holdout_attempts': 0},
        notes='TLT prices pass; historical ALFRED vintages were not obtained. No revised-value '
              'substitution or assumption of historical cash absence. All four training cases remain '
              'unattempted and performance is unmeasured. Decision and account-risk review: '
              'docs/research/43-c16-yield-curve-results.md.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    digest = write_once('audit.json', result)
    output = {'status': result['status'], 'price_status': result['price_status'], 'audit_sha256': digest}
    if args.record_ledger:
        paths = list(result['code_sha256'])+[str(PLAN.relative_to(ROOT))]
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
            raise ValueError('commit C16 source audit and plan before ledger recording')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if digest not in PLAN.read_text():
            raise ValueError('pin source audit hash in the committed plan')
        with session_scope() as session:
            trial = record_gap(session, result, commit)
            output.update({'trial_id': trial.id, 'strategy_id': trial.strategy_id, 'commit': trial.git_commit})
        write_once('ledger-receipt.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    main()
