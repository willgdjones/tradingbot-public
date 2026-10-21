"""C18 price-source audit only: fixed universe, no signal or holdout replay."""
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
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.total_return_data import (
    ROOT, sha, yahoo_prices, alpaca_prices, nasdaq_prices,
    dividend_adjusted_reference, cross_check, stooq_prices,
)

ARCHIVE = ROOT / 'data/research/c18-country-reversal'
PLAN = ROOT / 'docs/research/43-c18-country-reversal-plan.md'
START, END = datetime(2006, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
SYMBOLS = ('EWA', 'EWC', 'EWG', 'EWJ', 'EWS', 'EWU')
VARIANTS, COSTS = ('36', '60'), (5, 10)
KEY = 'sweep_c18_country_reversal_source_v1'
UNMEASURED = ('pnl', 'fees', 'trade_count', 'drawdown', 'regimes', 'luck_p_value', 'benchmarks', 'exposure', 'turnover',
              'settlement_delays', 'selection_counts')


def configurations():
    return [{'variant': v, 'cost_bp': bp, 'state': 'unattempted_source_gate_failed'}
            for v in VARIANTS for bp in COSTS]


def require_same(actual, saved):
    if actual != saved:
        raise ValueError('C18 archived comparison differs from revalidated prices')


def failed_symbols(checks):
    if set(checks) != set(SYMBOLS):
        raise ValueError('fixed six-country comparison universe required')
    return [s for s in SYMBOLS if not any(c.get('passed', False) for c in checks[s].values())]


def audit():
    references = ARCHIVE/'references'
    direct_path = references/'alpaca-comparison.json'
    direct = json.loads(direct_path.read_bytes())
    all_prices, all_meta = alpaca_prices(ROOT/direct['secondary']['path'])
    require_same(all_meta, direct['secondary'])
    calendar_manifest, calendar_source = spy_source()
    expected = {date.fromisoformat(r['date']) for r in calendar_source['prices']}
    inputs = {direct_path, ROOT/calendar_manifest['data_path'],
              ROOT/'docs/research/13-equity-data-repair-spy-amendment.json'}
    inputs.update(p for p in (ROOT/all_meta['path']).glob('*') if p.is_file())
    coverage, checks, primary = {}, {}, {}
    for symbol in SYMBOLS:
        folder = ARCHIVE/'primary'/symbol
        quotes, primary[symbol] = yahoo_prices(folder, symbol, START.date(), END.date())
        require_same(primary[symbol], direct['primary'][symbol])
        if set(quotes) != expected:
            raise ValueError('missing or extra primary session for '+symbol)
        coverage[symbol] = primary[symbol]['sessions']
        prices = {d: row['close'] for d, row in quotes.items()}
        checks[symbol] = {'alpaca_all': cross_check(prices, all_prices[symbol])}
        require_same(checks[symbol]['alpaca_all'], direct['checks'][symbol])
        inputs.update([folder/'raw.json', folder/'manifest.json'])

        if not checks[symbol]['alpaca_all']['passed']:
            path = references/f'nasdaq-comparison-{symbol}.json'
            saved = json.loads(path.read_bytes())
            require_same(primary[symbol], saved['primary'])
            require_same(all_meta, saved['secondary']['alpaca_all'])
            splits, sm = alpaca_prices(ROOT/saved['secondary']['alpaca_split']['path'], adjustment='split')
            require_same(sm, saved['secondary']['alpaca_split'])
            # Audit remains local; capture the reference before invoking it.
            if not (references/f'nasdaq-{symbol.lower()}'/'manifest.json').exists():
                raise ValueError('reference capture is missing')
            closes, nm = nasdaq_prices(symbol, START.date(), END.date()-timedelta(days=1), archive=references)
            require_same(nm, saved['secondary']['nasdaq'])
            checks[symbol]['nasdaq_alpaca_factors'] = cross_check(
                prices, dividend_adjusted_reference(closes, all_prices[symbol], splits[symbol]))
            require_same(checks[symbol]['nasdaq_alpaca_factors'], saved['check'])
            inputs.add(path)
            for meta in (all_meta, sm, nm):
                inputs.update(p for p in (ROOT/meta['path']).glob('*') if p.is_file())

        path = references/f'stooq-comparison-{symbol}.json'
        if path.exists():
            saved = json.loads(path.read_bytes())
            folder = references/f'stooq-{symbol.lower()}'
            raw, meta = (folder/'raw').read_bytes(), json.loads((folder/'manifest.json').read_bytes())
            require_same(meta, saved['source'])
            require_same(sha(raw), meta['sha256'])
            require_same(meta['params'], {'s': symbol.lower()+'.us', 'd1': '20060101',
                                         'd2': '20260930', 'i': 'd'})
            require_same(meta['url'], 'https://stooq.com/q/d/l/')
            try:
                comparison = cross_check(prices, stooq_prices(raw))
            except ValueError as error:
                require_same(str(error), saved.get('error'))
                comparison = {'passed': False, 'error': str(error)}
            else:
                require_same(comparison, saved['check'])
            checks[symbol]['stooq'] = comparison
            inputs.update([path, folder/'raw', folder/'manifest.json'])

    failed = failed_symbols(checks)
    identity = {'inputs': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(inputs)},
                'universe': list(SYMBOLS), 'variants': list(VARIANTS), 'costs_bp': list(COSTS),
                'source_start': START.isoformat(), 'source_end_exclusive': END.isoformat()}
    digest = sha(json.dumps(identity, sort_keys=True).encode())
    split = HoldoutSplit('c18-source:'+digest, START, END)
    return {'candidate': 'C18', 'status': 'DATA_FAIL' if failed else 'SOURCE_PASS',
        'identity': identity, 'split': split.metadata(), 'coverage': coverage, 'primary': primary,
        'crosschecks': checks, 'failed_symbols': failed, 'dataset_admitted': not failed,
        'planned_configurations': configurations(), 'strategy_outcomes_inspected': False,
        'training_cases_attempted': 0, 'final_holdout_attempts': 0, 'actual_allocation_usd': '0',
        **{k: None for k in UNMEASURED},
        'code_sha256': {p: sha((ROOT/p).read_bytes()) for p in (
            'src/tradingbot/research/c18_country_reversal.py', 'src/tradingbot/research/total_return_data.py',
            'src/tradingbot/data/free_history.py', 'src/tradingbot/research/c06_sources.py',
            'src/tradingbot/backtest/holdout.py')}}


def write_once(name, result):
    raw = (json.dumps(json_value(result), sort_keys=True, indent=2)+'\n').encode()
    path = ARCHIVE/name
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C18 source evidence')
        if not path.exists(): path.write_bytes(raw)
    return sha(raw)


def record_failure(session, result, commit):
    if (result['status'] != 'DATA_FAIL' or not result['failed_symbols']
            or failed_symbols(result['crosschecks']) != result['failed_symbols']
            or result['dataset_admitted'] or result['strategy_outcomes_inspected']
            or result['training_cases_attempted'] != 0 or result['final_holdout_attempts'] != 0
            or result['planned_configurations'] != configurations()
            or result['actual_allocation_usd'] != '0'
            or any(result[k] is not None for k in UNMEASURED)):
        raise ValueError('only fixed-universe source failure with unmeasured performance may be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    require_same(split.metadata(), result['split'])
    version = sha(json.dumps(result, sort_keys=True).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703018)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C18 country-equity reversal source audit', status='idea',
            allocation_usd=Decimal(0), config={'research_only': True, 'source_audit_only': True,
                                             'candidate': 'C18', 'research_family': 'c18'})
        session.add(strategy); session.flush()
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
        Trial.params['source_audit_version'].astext == version))
    if old is not None: return old
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start, data_start=START, data_end=END,
        git_commit=commit, code_version='c18-source-audit-v1', completed_ts=datetime.now(UTC),
        params={'stage': 'price_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                'source_audit_version': version, 'identity': result['identity'],
                'code_sha256': result['code_sha256'], 'planned_configurations': configurations()},
        metrics={'audit_result': 'DATA_FAIL', 'failed_symbols': result['failed_symbols'],
                 'training_cases_attempted': 0, 'final_holdout_attempts': 0},
        notes='Adjusted-price comparisons fail the fixed 99%/5bp standard before ranking or replay. '
              'All four training configurations remain unattempted; performance is unmeasured. '
              'Decision and risk review: docs/research/43-c18-country-reversal-results.md.')
    session.add(trial); session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    digest = write_once('audit.json', result)
    output = {'status': result['status'], 'failed_symbols': result['failed_symbols'], 'audit_sha256': digest}
    if args.record_ledger:
        paths = list(result['code_sha256'])+[str(PLAN.relative_to(ROOT))]
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
            raise ValueError('commit C18 source audit and plan before ledger recording')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if digest not in PLAN.read_text():
            raise ValueError('pin source audit hash in the committed plan')
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            output.update({'trial_id': trial.id, 'strategy_id': trial.strategy_id, 'commit': trial.git_commit})
        write_once('ledger-receipt.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    main()
