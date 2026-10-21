"""C06 source-bound replay through shared RiskEngine/Ledger and final guard."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, UTC
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import random
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, strategy_identity, register_split
from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy as StrategyRow, Trial, Incident
from tradingbot.db.session import session_scope
from tradingbot.research.c06_sources import ROOT, ARCHIVE, START, END, calendar_windows, sha
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityBacktester, EquityContext, EquityResearchLedger, ObservedStrategy
from tradingbot.research.turn_of_month import instrument_for, scenario_quote, finish_metrics, vars_trip
from tradingbot.strategy.c06_month_end import MonthEndUnderweight
from tradingbot.strategy.interface import MarketEvent

SOURCE_RECEIPT = 'a19e97a51fb2c2b762f4c8b154cdd36f1f06fb08798f088f57fce181ca3ccf0b'
THRESHOLDS = ('0.600', '0.595', '0.590')
COSTS = (5, 10)
ZERO = D(0)


def load_source():
    path = ARCHIVE / 'frozen-source-v1'
    receipt = json.loads((path / 'manifest.json').read_text())
    recorded = receipt.pop('receipt_sha256')
    if recorded != SOURCE_RECEIPT or sha(canonical(receipt).encode()) != recorded:
        raise ValueError('C06 source receipt changed')
    raw = (path / 'data.json').read_bytes()
    if sha(raw) != receipt['identity']['data_sha256']:
        raise ValueError('C06 frozen data checksum mismatch')
    if receipt['status'] != 'SOURCE_VALIDATED_NOT_STRATEGY_ADMITTED':
        raise ValueError('C06 source audit is not validated')
    for name, digest in receipt['source_code_sha256'].items():
        if sha((ROOT / name).read_bytes()) != digest:
            raise ValueError('source-audit dependency changed')
    receipt['receipt_sha256'] = recorded
    source = json.loads(raw)
    source['receipt'] = receipt
    return source


def dependencies():
    paths = ['research/c06_month_end.py', 'strategy/c06_month_end.py',
        'research/c06_sources.py', 'research/equity_runtime.py', 'research/equity_fees.py',
        'research/equity_data.py', 'research/turn_of_month.py', 'backtest/engine.py',
        'backtest/holdout.py', 'backtest/fills.py', 'ledger/ledger.py',
        'risk/engine.py', 'risk/limits.py', 'connectors/cash.py']
    return {p: sha((ROOT / 'src/tradingbot' / p).read_bytes()) for p in paths}


def split_for(source):
    declared = source['receipt']['split']
    split = HoldoutSplit(declared['dataset_key'], START, END)
    if split.metadata() != declared:
        raise ValueError('C06 split differs from preregistration')
    return split


def execution_sessions(source):
    """Cash helper's date becomes the explicitly frozen release-session date.

    Every replay event is at/after that session's open. Actual nominal and
    completed settlement dates stay separately identified in fill evidence.
    """
    result = {}
    for row in source['SPY']['prices']:
        day = date.fromisoformat(row['date'])
        release = datetime.fromisoformat(row['conservative_cash_release'])
        result[day] = MarketSession(day, release.astimezone(NEW_YORK).date(),
            datetime.fromisoformat(row['opens_at']), datetime.fromisoformat(row['closes_at']))
    return result


class C06Context(EquityContext):
    def marked_equity(self):
        return self.runtime.equity()


class C06ObservedStrategy(ObservedStrategy):
    def on_start(self, ctx):
        self.delegate.on_start(C06Context(ctx, self.runtime))

    def on_event(self, ctx, event):
        self.runtime.observe(event)
        return self.delegate.on_event(C06Context(ctx, self.runtime), event)

    def on_finish(self, ctx):
        self.delegate.on_finish(C06Context(ctx, self.runtime))


class C06Ledger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        day = fill.fill_ts.astimezone(NEW_YORK).date().isoformat()
        row = self.runtime.source_sessions[day]
        research = {**fill.metadata_['research'], 'source': 'c06_amended_yahoo_open_reference_scenario',
            'settlement_date': row['completed_settlement'], 'scheduled_t1': row['scheduled_t1'],
            'conservative_cash_release': row['conservative_cash_release'],
            'cash_is_counterfactual': True, 'source_receipt': SOURCE_RECEIPT,
            'terminal_liquidation': kwargs['order'].reason == 'C06 terminal liquidation'}
        fill.metadata_ = {**fill.metadata_, 'research': research}
        return fill


class C06Backtester(EquityBacktester):
    def __init__(self, session, *, strategy, strategy_id, source, fx):
        self.source_sessions = {r['date']: r for r in source['SPY']['prices']}
        super().__init__(session, strategy=strategy, strategy_id=strategy_id,
                         sessions=execution_sessions(source), fx=fx)
        self.strategy = C06ObservedStrategy(strategy, self)
        self.ledger = C06Ledger(session, self)


def strategy_params(source, spy, ief, threshold):
    if threshold not in THRESHOLDS:
        raise ValueError('threshold outside preregistered variants')
    return {'spy_id': spy, 'ief_id': ief, 'threshold': threshold,
        'windows': calendar_windows(source['SPY']['prices']), 'target_weight': '0.95',
        'slot_usd': '140', 'buy_fee_reserve_usd': '0.01', 'quantity_step': '0.000000001',
        'decision': 'penultimate regular-session close', 'entry': 'final regular-session open',
        'exit': 'next-month first regular-session open', 'source_receipt': SOURCE_RECEIPT,
        'signal': 'causal daily total-return factors from close and ex-date distribution',
        'partition_policy': 'flat start, partition-local warm-up, complete round trip, last-open liquidation'}


def events(source, params, bp, final, observed):
    """Lazy: the engine's durable final claim must precede this first yield."""
    if bp not in COSTS:
        raise ValueError('cost outside fixed training cases')
    split = split_for(source)
    rows = {r['date']: r for r in source['SPY']['prices']}
    ief = {r['date']: r for r in source['IEF']['prices']}
    div = {s: {r['ex_date']: D(r['amount']) for r in source[s]['distributions']} for s in ('SPY', 'IEF')}
    valid = set()
    for window in params['windows']:
        times = [rows[window[k]][field] for k, field in
                 [('base', 'closes_at'), ('decision', 'closes_at'), ('entry', 'opens_at'), ('exit', 'opens_at')]]
        if all(split.contains(datetime.fromisoformat(t), final_holdout=final) for t in times):
            valid.add(window['decision'])
    opens = [r['opens_at'] for r in rows.values() if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final)]
    if not opens:
        raise ValueError('selected partition has no reference opens')
    terminal = max(opens, key=datetime.fromisoformat)
    for day, row in rows.items():
        open_at, close_at = (datetime.fromisoformat(row[k]) for k in ('opens_at', 'closes_at'))
        if split.contains(open_at, final_holdout=final):
            event = scenario_quote(params['spy_id'], open_at, D(row['open']), bp,
                phase='open', source='frozen_c06_open_reference', terminal_open=row['opens_at'] == terminal)
            observed.append(event)
            yield event
        if split.contains(close_at, final_holdout=final):
            for symbol, iid, close in [('IEF', params['ief_id'], D(ief[day]['close'])),
                                        ('SPY', params['spy_id'], D(row['close']))]:
                event = MarketEvent.quote(iid, close_at, mid=close, meta={'phase': 'close',
                    'symbol': symbol, 'ex_date_distribution': str(div[symbol].get(day, ZERO)),
                    'window_complete_in_partition': day in valid, 'mark_only': True})
                observed.append(event)
                yield event


def drawdown(values):
    peak = maximum = fraction = ZERO
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, peak - value)
        if peak:
            fraction = max(fraction, (peak - value) / peak)
    return {'dollars': str(maximum), 'fraction': str(fraction)}


def monthly_luck(monthly, round_trips):
    """Fixed 3-month circular-block, centered-null bootstrap; descriptive only."""
    values = [float(v) for v in monthly.values()]
    if len(values) < 30 or round_trips < 30 or not any(values):
        return {'p_value': None, 'reason': 'fewer than 30 completed trips/months or zero variation'}
    n = len(values)
    mean = sum(values) / n
    centered = [x - mean for x in values]
    rng = random.Random(6062026)
    exceed = 0
    for _ in range(10000):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(centered[(start + j) % n] for j in range(3))
        exceed += sum(sample[:n]) / n >= mean
    return {'p_value': (exceed + 1) / 10001, 'method': 'one-sided centered circular block bootstrap',
        'block_months': 3, 'draws': 10000, 'seed': 6062026, 'months': n,
        'descriptive_only': True, 'selection_adjusted': False}


def marked_period(curve, low, high):
    previous = D(140)
    selected = []
    for stamp, value in curve:
        year = stamp.astimezone(NEW_YORK).year
        if low <= year <= high:
            if not selected:
                selected.append(previous)
            selected.append(value)
        previous = value
    return {'covered': bool(selected), 'marked_net_usd': str(selected[-1] - selected[0]) if selected else None,
            'marked_drawdown': drawdown(selected) if selected else None}


def diagnostics(bot, observed, trips, curve):
    opens = {e.time.astimezone(NEW_YORK).date().isoformat(): e.mid
             for e in observed if e.meta.get('phase') == 'open'}
    windows = []
    for decision in bot.decisions:
        entry, exit = decision['entry'], decision['exit']
        windows.append({**decision, 'market_open_to_open_return': str(opens[exit] / opens[entry] - 1)})
    def group(values):
        returns = [D(v['market_open_to_open_return']) for v in values]
        return {'windows': len(returns), 'mean_gross_window_return': str(sum(returns, ZERO) / len(returns)) if returns else None}
    complete = [(day, values) for day, values in sorted(bot._history.items())
                if bot.params['spy_id'] in values and bot.params['ief_id'] in values]
    benchmarks = {}
    for name in ('SPY', 'equal_weight_SPY_IEF', 'cash'):
        values = []
        for _, factors in complete:
            a, b = factors[bot.params['spy_id']], factors[bot.params['ief_id']]
            values.append(D(140) * (a if name == 'SPY' else (a + b) / 2 if name == 'equal_weight_SPY_IEF' else 1))
        benchmarks[name] = {'net_of_etf_expenses_not_trading_costs': True,
            'not_executable': True, 'start_close': complete[0][0] if complete else None,
            'end_close': complete[-1][0] if complete else None,
            'total_return': str(values[-1] / 140 - 1) if values else None,
            'max_drawdown': drawdown(values)}
    months = sorted({e.time.astimezone(NEW_YORK).strftime('%Y-%m') for e in observed})
    monthly = {month: ZERO for month in months}
    for trip in trips:
        monthly[trip.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m')] += trip.net_pnl
    regimes = {}
    for name, low, high in [('2006-2009', 2006, 2009), ('2010-2019', 2010, 2019),
                           ('2020-2021', 2020, 2021), ('2022', 2022, 2022), ('2023-2026', 2023, 2026)]:
        selected = [t for t in trips if low <= t.exit_ts.astimezone(NEW_YORK).year <= high]
        regimes[name] = {'trips': len(selected), 'net_usd': str(sum((t.net_pnl for t in selected), ZERO)),
            'fees_usd': str(sum((t.fees for t in selected), ZERO)), **marked_period(curve, low, high)}
    return {'flow_windows': windows,
        'window_comparison': {'all': group(windows), 'qualified': group([w for w in windows if w['qualified']]),
                              'not_qualified': group([w for w in windows if not w['qualified']])},
        'benchmarks': benchmarks, 'calendar_regimes': regimes, 'monthly_net_usd': json_value(monthly),
        'marked_calendar_years': {str(y): marked_period(curve, y, y)
            for y in sorted({t.astimezone(NEW_YORK).year for t, _ in curve})},
        'luck': monthly_luck(monthly, len(trips)), 'max_marked_drawdown': drawdown([D(140)] + [v for _, v in curve]),
        'skips': bot.skips, 'source_contamination': True, 'promotion_eligible': False}


def require_committed():
    paths = ['src/tradingbot/' + p for p in dependencies()]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit all replay dependencies before real-data strategy outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, threshold, bp, *, final=False, expected_version=None):
    commit = require_committed()
    key = f'c06-{source["receipt"]["identity"]["data_sha256"][:10]}-{threshold}-{bp}-' + ('final' if final else 'train')
    existing = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if existing:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C06 final invocation before feed consumption',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': existing,
                         'source_receipt': SOURCE_RECEIPT, 'strategy_version': expected_version}))
            session.commit()
        raise ValueError('C06 configuration already attempted; export stored results instead of replaying')
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check()
    spy, venue = instrument_for(session, 'SPY')
    ief, _ = instrument_for(session, 'IEF')
    params = strategy_params(source, spy, ief, threshold)
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'slippage_bp_per_side': bp, 'dependencies': dependencies(),
        'fx_source_sha256': fx.source_hash, 'source_receipt': SOURCE_RECEIPT,
        'fee_policy': 'alpaca_retail_2026_09_17_counterfactual'}
    row = StrategyRow(key=key, name=f'C06 threshold {threshold} cost {bp} bp ' + ('final' if final else 'training'),
        venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'source_contaminated': True, 'candidate': 'C06', 'params': params})
    session.add(row)
    session.commit()
    sid = row.id
    split = split_for(source)
    runtime = None
    try:
        bot = MonthEndUnderweight(params)
        runtime = C06Backtester(session, strategy=bot, strategy_id=sid, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and (not expected_version or calculated != expected_version):
            raise ValueError('final version differs from frozen training choice before data consumption')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C06 preregistered scenario; amended Yahoo opens, causal issuer distributions, conservative cash. '
                  'Prior inspected SPY history: diagnostic, no fresh-proof promotion.')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, observed, trips, runtime.curve))
        metrics['turnover_usd'] = sum((f.price * f.size for f in fills), ZERO)
        metrics['gross_usd'] = sum((t.gross_pnl for t in trips), ZERO)
        metrics['cash_delay_skips'] = [s for s in bot.skips if 'cash' in s['reason'] or 'reserve' in s['reason']]
        metrics['terminal_liquidation_fills'] = sum(f.metadata_['research']['terminal_liquidation'] for f in fills)
        metrics['qualified_months'] = sum(d['qualified'] for d in bot.decisions)
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'c06-replay-v1'
        trial.metrics = json_value(metrics)
        trial.max_drawdown = runtime.max_drawdown
        trial.luck_p_value = D(str(metrics['luck']['p_value'])) if metrics['luck']['p_value'] is not None else None
        budget.check()
        session.commit()
        return {'status': 'complete', 'threshold': threshold, 'cost_bp': bp, 'final_holdout': final,
            'trial_id': trial.id, 'strategy_id': sid, 'git_commit': commit, 'version_params': version,
            'strategy_version': trial.strategy_version, 'metrics': json_value(metrics),
            'trades': json_value([vars_trip(t) for t in trips]), 'curve': json_value(runtime.curve),
            'fill_ids': [f.id for f in fills]}
    except Exception as error:
        session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if final and runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=sid, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=split.data_start, data_end=split.data_end,
                strategy_version=locals().get('calculated'),
                params={'strategy': params, 'version_params': version, '_holdout': split.metadata(),
                        'requested_final': final, 'final_feed_consumed': False})
            session.add(trial)
        trial.status = 'failed'
        trial.git_commit = commit
        trial.code_version = 'c06-replay-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C06 replay failed; no retry of consumed final: {type(error).__name__}: {error}'
        session.commit()
        raise


def immutable_artifact(name, body):
    encoded = (json.dumps(json_value(body), indent=2, sort_keys=True) + '\n').encode()
    path = ARCHIVE / 'runs' / name
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded) + 65536):
        path.parent.mkdir(exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise ValueError('refuse overwrite of C06 outcome artifact')
        else:
            path.write_bytes(encoded)
    return path, sha(encoded)


def train():
    source = load_source()
    results = []
    for threshold in THRESHOLDS:
        for bp in COSTS:
            with session_scope() as session:
                result = run_variant(session, source, threshold, bp)
            path, digest = immutable_artifact(f'train-{threshold}-{bp}.json', result)
            results.append({k: v for k, v in result.items() if k not in {'curve', 'trades', 'fill_ids'}} |
                           {'artifact': str(path.relative_to(ROOT)), 'artifact_sha256': digest})
            print(json.dumps({'threshold': threshold, 'cost_bp': bp, 'trial': result['trial_id'],
                'net_usd': result['metrics']['net_usd'], 'trips': result['metrics']['trades']}), flush=True)
    eligible = [r for r in results if r['cost_bp'] == 10 and r['metrics']['complete_execution']
                and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -THRESHOLDS.index(r['threshold']))) if eligible else None
    frozen = {'source_receipt': SOURCE_RECEIPT, 'dependencies': dependencies(), 'split': source['receipt']['split'],
        'training': results, 'selected': selected['threshold'] if selected else None,
        'selected_strategy_version': selected['strategy_version'] if selected else None,
        'holdout_attempted': False, 'rule': 'highest 10bp training net; threshold order breaks ties',
        'prior_inspection_contamination': True, 'promotion_eligible': False}
    path, digest = immutable_artifact('selection.json', frozen)
    (ROOT / 'docs/research/16-c06-selection.json').write_bytes(path.read_bytes())
    print(json.dumps({'selected': frozen['selected'], 'selection_sha256': digest, 'final_attempted': False}))


def final():
    source = load_source()
    path = ROOT / 'docs/research/16-c06-selection.json'
    commit = require_committed()
    committed = subprocess.check_output(['git', 'show', commit + ':docs/research/16-c06-selection.json'], cwd=ROOT)
    if path.read_bytes() != committed:
        raise ValueError('commit the frozen selection before final admission')
    choice = json.loads(committed)
    if (choice['source_receipt'] != SOURCE_RECEIPT or choice['dependencies'] != dependencies()
            or choice['split'] != source['receipt']['split'] or choice['selected'] not in THRESHOLDS):
        raise ValueError('no valid frozen profitable training choice')
    with session_scope() as session:
        training = next(r for r in choice['training'] if r['threshold'] == choice['selected'] and r['cost_bp'] == 10)
        original = session.get(Trial, training['trial_id'])
        if (original is None or original.final_holdout or original.status != 'complete'
                or original.strategy_version != choice['selected_strategy_version']
                or original.metrics != training['metrics'] or D(original.metrics['net_usd']) <= 0):
            raise ValueError('frozen training choice disagrees with durable trial evidence')
        result = run_variant(session, source, choice['selected'], 10, final=True,
                             expected_version=choice['selected_strategy_version'])
    if result['strategy_version'] != choice['selected_strategy_version']:
        raise ValueError('final version differs from frozen training version; consumed final requires audit')
    artifact, digest = immutable_artifact('final.json', result)
    receipt = {k: v for k, v in result.items() if k not in {'curve', 'trades', 'fill_ids'}}
    receipt.update({'artifact': str(artifact.relative_to(ROOT)), 'artifact_sha256': digest,
        'selection_sha256': sha(committed), 'historical_result_is_contaminated': True, 'promotion': 'none'})
    (ROOT / 'docs/research/16-c06-final.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'trial': result['trial_id'], 'net_usd': result['metrics']['net_usd'],
                     'trips': result['metrics']['trades'], 'promotion': 'none'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['train', 'final'])
    args = parser.parse_args()
    train() if args.phase == 'train' else final()


if __name__ == '__main__':
    main()
