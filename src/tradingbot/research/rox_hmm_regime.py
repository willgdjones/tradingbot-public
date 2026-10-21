"""C-ROX HMM regime filter on SPY: adjusted-total-return research runner.

Deterministic Gaussian-HMM regime filter (bead tradingbot-rox, plan
docs/research/48-rox-hmm-regime-plan.md). Reuses the single-asset total-return
backtester, fees, cross-checked SPY bundle and durable holdout machinery from
``c11_total_return`` — only the strategy (a regime overlay, decided every
month-end) and the four fixed HMM variants differ. One durable final at 10 bp,
or none when no training variant is positive after costs. No LLM/Jev call.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c06_month_end import drawdown, monthly_luck
from tradingbot.research.c11_total_return import C11Backtester, period, scenario, tr_instrument
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.total_return_data import ROOT, sha
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.rox_hmm_regime import HmmRegimeStrategy

ARCHIVE = ROOT / 'data/research/rox-hmm-regime'
PLAN = ROOT / 'docs/research/48-rox-hmm-regime-plan.md'
C11_SOURCE = ROOT / 'data/research/c11-total-return/source.json'
START, END = datetime(2006, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
VARIANT_PARAMS = {
    'k2_ret': {'n_states': 2, 'features': 'ret'},
    'k3_ret': {'n_states': 3, 'features': 'ret'},
    'k2_retvol': {'n_states': 2, 'features': 'retvol'},
    'k3_retvol': {'n_states': 3, 'features': 'retvol'},
}
VARIANTS = tuple(VARIANT_PARAMS)
COSTS = (5, 10)
HMM_FIXED = {'min_obs': 756, 'vol_window': 20, 'n_iter': 200, 'tol': 0.0001,
             'covariance_type': 'full', 'random_state': 0}
ZERO = D(0)


def write_once(name, value):
    path = ARCHIVE / name
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2) + '\n').encode()
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C-ROX source/outcome artifact')
        if not path.exists():
            path.write_bytes(raw)
    return str(path.relative_to(ROOT)), sha(raw)


def freeze_source():
    """Reuse the cross-checked SPY total-return bundle frozen by C11; re-verify
    its input hashes and re-emit under the C-ROX candidate with its own sha."""
    src = json.loads(C11_SOURCE.read_bytes())
    if not src['crosscheck']['passed']:
        raise ValueError('reused SPY bundle must have a passing cross-check')
    for name, expected in src['inputs'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('reused SPY source input changed: ' + name)
    source = {'candidate': 'C-ROX', 'symbol': 'SPY',
        'derived_from': {'path': str(C11_SOURCE.relative_to(ROOT)), 'sha256': sha(C11_SOURCE.read_bytes())},
        'primary': src['primary'], 'crosscheck': src['crosscheck'], 'secondary': src['secondary'],
        'inputs': src['inputs'], 'prices': src['prices'],
        'model': 'daily adjusted total-return equivalent; no separate dividend cash'}
    path, digest = write_once('source.json', source)
    print(json.dumps({'source': path, 'source_sha256': digest, 'sessions': len(source['prices'])}))


def load_source():
    raw = (ARCHIVE / 'source.json').read_bytes()
    digest = sha(raw)
    if digest not in PLAN.read_text():
        raise ValueError('C-ROX source hash must be recorded in the plan before replay')
    source = json.loads(raw)
    if not source['crosscheck']['passed']:
        raise ValueError('unaccepted source comparison')
    for name, expected in source['inputs'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('C-ROX source input changed: ' + name)
    source['sha256'] = digest
    return source


def split_for(source):
    return HoldoutSplit('rox-hmm-regime:' + source['sha256'], START, END)


def month_ends(prices):
    last_of_month = {}
    for row in prices:  # prices are in ascending calendar order
        last_of_month[row['date'][:7]] = row['date']
    return [last_of_month[month] for month in sorted(last_of_month)]


def strategy_params(source, iid, variant):
    if variant not in VARIANTS:
        raise ValueError('outside C-ROX variant set')
    params = {'instrument_id': iid, 'symbol_id': iid, 'variant': variant, 'slot_usd': '140',
              'target_weight': '0.95', 'cash_reserve_weight': '0.05', 'buy_fee_reserve_usd': '0.01',
              'quantity_step': '0.000000001', 'month_ends': month_ends(source['prices']),
              'source_sha256': source['sha256']}
    params.update(HMM_FIXED)
    params.update(VARIANT_PARAMS[variant])
    return params


def events(source, params, bp, final, observed):
    """Open then close per session, within the partition. A month-end close is
    tagged next_open_in_partition when the following session's open is in the
    same partition and is not the terminal open (where only liquidation runs)."""
    split = split_for(source)
    rows = source['prices']
    in_part = [r for r in rows if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final)]
    terminal = max((r['opens_at'] for r in in_part), default=None)
    month_end_days = set(params['month_ends'])
    for index, row in enumerate(rows):
        for phase, key in (('open', 'opens_at'), ('close', 'closes_at')):
            stamp = datetime.fromisoformat(row[key])
            if not split.contains(stamp, final_holdout=final):
                continue
            extra = {}
            if phase == 'open':
                extra['terminal_open'] = row[key] == terminal
            else:
                nxt = rows[index + 1] if index + 1 < len(rows) else None
                extra['next_open_in_partition'] = bool(
                    row['date'] in month_end_days and nxt is not None
                    and split.contains(datetime.fromisoformat(nxt['opens_at']), final_holdout=final)
                    and nxt['opens_at'] != terminal)
            event = scenario(params['instrument_id'], stamp, row['quote'], phase, bp, **extra)
            observed.append(event)
            yield event


def diagnostics(bot, observed, trips, fills, runtime):
    month_ends_curve = {}
    for stamp, value in runtime.curve:
        month_ends_curve[stamp.astimezone(NEW_YORK).strftime('%Y-%m')] = value
    previous, monthly = D(140), {}
    for month, value in sorted(month_ends_curve.items()):
        monthly[month], previous = value - previous, value
    closes = [e.mid for e in observed if e.meta['phase'] == 'close']
    long_targets = [d for d in bot.decisions if D(d['target_weight']) > 0]
    switches = sum(1 for a, b in zip(bot.decisions, bot.decisions[1:])
                   if (D(a['target_weight']) > 0) != (D(b['target_weight']) > 0))

    def regime(low, high):
        selected = [t for t in trips if low <= t.exit_ts.astimezone(NEW_YORK).date().isoformat() < high]
        return {**period(runtime.curve, low, high), 'trades': len(selected),
                'net_usd': str(sum((t.net_pnl for t in selected), ZERO))}

    spy_total_return = str(closes[-1] / closes[0] - 1) if closes else None
    return {'decisions': bot.decisions, 'skips': bot.skips,
        'n_month_decisions': len(bot.decisions), 'n_long_decisions': len(long_targets),
        'n_regime_switches': switches,
        'max_marked_drawdown': drawdown([D(140)] + [v for _, v in runtime.curve]),
        'monthly_marked_net_usd': json_value(monthly), 'luck': monthly_luck(monthly, len(trips)),
        'calendar_regimes': {name: regime(lo, hi) for name, lo, hi in (
            ('2006-2009', '2006-01-01', '2010-01-01'), ('2010-2019', '2010-01-01', '2020-01-01'),
            ('2020-2021', '2020-01-01', '2022-01-01'), ('2022', '2022-01-01', '2023-01-01'),
            ('2023-2026', '2023-01-01', '2027-01-01'))},
        'marked_calendar_years': {str(y): regime(f'{y}-01-01', f'{y + 1}-01-01')
            for y in sorted({t.astimezone(NEW_YORK).year for t, _ in runtime.curve})},
        'benchmarks': {'cash': {'total_return': '0'}, 'SPY_always_long': {
            'total_return': spy_total_return, 'max_drawdown': drawdown(closes),
            'basis': 'same-partition adjusted completed closes, no costs, full exposure (the overlay baseline)'}},
        'fees_usd': str(sum((f.fee for f in fills), ZERO)),
        'adverse_cost_usd': str(sum((abs(f.price - D(f.metadata_['research']['execution']['reference'])) * f.size
                                     for f in fills), ZERO)),
        'daily_exposure': runtime.daily_exposure,
        'average_exposure': str(sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO) / len(runtime.daily_exposure))
            if runtime.daily_exposure else None, 'promotion_eligible': False}


def dependencies():
    names = ['research/rox_hmm_regime.py', 'strategy/rox_hmm_regime.py',
        'research/c11_total_return.py', 'research/total_return_data.py', 'research/c06_sources.py',
        'research/c06_month_end.py', 'research/turn_of_month.py', 'research/equity_runtime.py',
        'research/equity_fees.py', 'research/equity_data.py', 'backtest/engine.py', 'backtest/holdout.py',
        'backtest/fills.py', 'connectors/cash.py', 'strategy/interface.py', 'ledger/ledger.py',
        'ledger/accounting.py', 'risk/engine.py', 'risk/limits.py']
    return {p: sha((ROOT / 'src/tradingbot' / p).read_bytes()) for p in names}


def require_committed():
    paths = ['src/tradingbot/' + p for p in dependencies()] + [str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C-ROX plan and dependencies before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if variant not in VARIANTS or bp not in COSTS or (final and bp != 10):
        raise ValueError('configuration outside frozen C-ROX family')
    key = f'rox-hmm-{source["sha256"][:12]}-{variant}-{bp}-' + ('final' if final else 'train')
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('C-ROX configuration already attempted; use stored evidence')
    CaptureDiskBudget(ROOT / 'data').check()
    iid, venue = tr_instrument(session, 'SPY')
    params = strategy_params(source, iid, variant)
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': bp, 'variant': variant, 'dependencies': dependencies(),
               'source_sha256': source['sha256'], 'fx_source_sha256': fx.source_hash,
               'model': 'total_return_equivalent_v1', 'fee_policy': 'dated 2026-09-17 raw-share equivalent'}
    row = StrategyRow(key=key, name=f'C-ROX {variant} {bp}bp', venue_id=venue, status='backtest',
        allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C-ROX', 'research_family': 'c-rox', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = HmmRegimeStrategy(params)
        runtime = C11Backtester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed selected version')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C-ROX HMM regime filter, total-return equivalent, virtual cash, dated fees and conservative settlement')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, observed, trips, fills, runtime))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'c-rox-hmm-regime-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl = D(metrics['net_usd']), D(metrics['net_usd']) + runtime.charged
        trial.max_drawdown = runtime.max_drawdown
        p = metrics['luck']['p_value']
        trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'variant': variant, 'cost_bp': bp, 'final_holdout': final,
            'trial_id': trial.id, 'strategy_id': row.id, 'git_commit': commit,
            'strategy_version': trial.strategy_version, 'version_params': version, 'metrics': json_value(metrics),
            'trades': json_value([vars_trip(t) for t in trips]), 'curve': json_value(runtime.curve),
            'fill_ids': [f.id for f in fills]}
    except BaseException as error:
        if not session.is_active:
            session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=row.id, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=split.data_start, data_end=split.data_end,
                strategy_version=calculated, params={'strategy': params, 'version_params': version,
                    'requested_final': final, 'final_feed_consumed': False, '_holdout': split.metadata()})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c-rox-hmm-regime-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C-ROX failed; any consumed final and partial fills preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total = runtime.max_drawdown, runtime.charged
            trial.pnl_after_fees = runtime.realized - runtime.charged
            trial.metrics = json_value({'complete_execution': False, 'partial_replay': True,
                'last_processed_at': runtime.now, 'fees_usd': runtime.charged,
                'ending_marked_equity_usd': runtime.equity(), 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception):
            raise
        return {'status': 'failed', 'variant': variant, 'cost_bp': bp,
            'final_holdout': bool(trial.final_holdout), 'requested_final': final, 'trial_id': trial.id,
            'strategy_id': row.id, 'git_commit': commit, 'error': str(error),
            'strategy_version': trial.strategy_version, 'metrics': trial.metrics}


def train():
    source, results = load_source(), []
    for variant in VARIANTS:
        for bp in COSTS:
            with session_scope() as session:
                result = run_variant(session, source, variant, bp)
            path, digest = write_once(f'train-{variant}-{bp}.json', result)
            results.append({k: v for k, v in result.items() if k not in ('curve', 'trades', 'fill_ids')} |
                           {'artifact': path, 'artifact_sha256': digest})
            print(json.dumps({k: result.get(k) for k in ('variant', 'cost_bp', 'status', 'trial_id', 'error')}), flush=True)
    eligible = [r for r in results if r['status'] == 'complete' and r['cost_bp'] == 10
                and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -VARIANTS.index(r['variant']))) if eligible else None
    choice = {'source_sha256': source['sha256'], 'dependencies': dependencies(), 'split': split_for(source).metadata(),
        'training': results, 'selected': selected['variant'] if selected else None,
        'selected_trial_id': selected['trial_id'] if selected else None,
        'selected_strategy_version': selected['strategy_version'] if selected else None,
        'rule': 'highest positive complete 10bp training net; listed variant order breaks ties',
        'holdout_attempted': False}
    _, digest = write_once('selection.json', choice)
    print(json.dumps({'selected': choice['selected'], 'selection_sha256': digest}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE / 'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit + ':' + str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('selection hash must be in committed plan before final')
    choice = json.loads(raw)
    if (choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies()
            or choice['split'] != split_for(source).metadata() or choice['selected'] not in VARIANTS):
        raise ValueError('invalid or absent frozen C-ROX winner')
    chosen = next(r for r in choice['training'] if r['trial_id'] == choice['selected_trial_id'])
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != choice['selected_strategy_version'] or trial.metrics != chosen['metrics']
                or D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
            raise ValueError('frozen selection differs from durable training')
        result = run_variant(session, source, choice['selected'], 10, final=True,
                             expected_version=choice['selected_strategy_version'])
    _, digest = write_once('final.json', result)
    print(json.dumps({'trial_id': result['trial_id'], 'status': result['status'],
                      'net_usd': result.get('metrics', {}).get('net_usd'), 'artifact_sha256': digest}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'train', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
