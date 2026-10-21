"""Source-bound C08 replay, durable trials, and one frozen final attempt."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c08_blackout import ARCHIVE, END, ROOT, START, sha
from tradingbot.research.c06_month_end import drawdown, monthly_luck
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityBacktester, EquityContext, EquityResearchLedger, ObservedStrategy
from tradingbot.research.turn_of_month import finish_metrics, instrument_for, scenario_quote, vars_trip
from tradingbot.strategy.c08_inventory import InventoryScarcity
from tradingbot.strategy.interface import MarketEvent

SOURCE_RECEIPT = '63c4d561929099ae039a8a67a0deace1991b08d6e3dacef55c6c2de481b99ca5'
THRESHOLDS = ('0', '-0.05')
COSTS = (5, 10)
ZERO = D(0)


def load_source():
    path = ARCHIVE / 'frozen-source-v1'
    manifest = json.loads((path / 'manifest.json').read_text())
    digest = manifest.pop('receipt_sha256')
    if SOURCE_RECEIPT == 'PENDING_SOURCE_ADMISSION' or digest != SOURCE_RECEIPT or sha(canonical(manifest).encode()) != digest:
        raise ValueError('C08 source admission is absent or changed')
    if manifest['status'] != 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES':
        raise ValueError('C08 source audit is not admitted')
    raw = (path / 'data.json').read_bytes()
    if sha(raw) != manifest['identity']['data_sha256']:
        raise ValueError('C08 frozen data checksum mismatch')
    for name, expected in manifest['source_code_sha256'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('C08 source-audit dependency changed')
    manifest['receipt_sha256'] = digest
    return {**json.loads(raw), 'receipt': manifest}


def dependencies():
    paths = ['research/c08_inventory.py', 'strategy/c08_inventory.py', 'research/c08_blackout.py',
             'research/c06_month_end.py', 'research/equity_runtime.py', 'research/equity_fees.py',
             'research/equity_data.py', 'research/turn_of_month.py', 'backtest/engine.py',
             'backtest/holdout.py', 'backtest/fills.py', 'ledger/ledger.py', 'risk/engine.py',
             'risk/limits.py', 'connectors/cash.py', 'strategy/interface.py']
    return {name: sha((ROOT / 'src/tradingbot' / name).read_bytes()) for name in paths}


def split_for(source):
    declared = source['receipt']['split']
    split = HoldoutSplit(declared['dataset_key'], START, END)
    if split.metadata() != declared:
        raise ValueError('C08 source split differs from fixed preregistration')
    return split


def execution_sessions(source):
    return {date.fromisoformat(r['date']): MarketSession(date.fromisoformat(r['date']),
        datetime.fromisoformat(r['conservative_cash_release']).astimezone(NEW_YORK).date(),
        datetime.fromisoformat(r['opens_at']), datetime.fromisoformat(r['closes_at'])) for r in source['prices']}


class C08Context(EquityContext):
    def marked_equity(self):
        return self.runtime.equity()


class C08ObservedStrategy(ObservedStrategy):
    def on_start(self, ctx):
        self.delegate.on_start(C08Context(ctx, self.runtime))

    def on_event(self, ctx, event):
        self.runtime.observe(event)
        return self.delegate.on_event(C08Context(ctx, self.runtime), event)

    def on_finish(self, ctx):
        self.delegate.on_finish(C08Context(ctx, self.runtime))


class C08Ledger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        row = self.runtime.source_sessions[fill.fill_ts.astimezone(NEW_YORK).date().isoformat()]
        reason = kwargs['order'].reason
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'c08_actual_share_yahoo_open_reference_scenario',
            'source_receipt': self.runtime.source_receipt,
            'settlement_date': row['completed_settlement'], 'scheduled_t1': row['scheduled_t1'],
            'conservative_cash_release': row['conservative_cash_release'], 'cash_is_counterfactual': True,
            'terminal_liquidation': reason == 'C08 terminal liquidation',
            'forced_blackout_exit': reason == 'C08 forced blackout exit',
            'blackout_reentry': reason == 'C08 blackout reentry'}}
        return fill


class C08Backtester(EquityBacktester):
    def __init__(self, session, *, strategy, strategy_id, source, fx):
        self.source_sessions = {r['date']: r for r in source['prices']}
        self.source_receipt = source['receipt']['receipt_sha256']
        super().__init__(session, strategy=strategy, strategy_id=strategy_id,
                         sessions=execution_sessions(source), fx=fx)
        self.strategy = C08ObservedStrategy(strategy, self)
        self.ledger = C08Ledger(session, self)

    def run(self, events, **kwargs):
        def admitted_events():
            # The shared engine creates/claims the trial before first iteration.
            # Commit training too, so an interruption cannot erase an attempt.
            trial = self.session.get(Trial, self.last_trial_id)
            if trial is None or trial.status != 'running':
                raise ValueError('C08 feed requires a running admitted trial')
            self.session.commit()
            yield from events
        return super().run(admitted_events(), **kwargs)


def strategy_params(source, uso, spy, threshold):
    if threshold not in THRESHOLDS:
        raise ValueError('threshold outside preregistered C08 variants')
    return {'uso_id': uso, 'spy_benchmark_id': spy, 'threshold': threshold,
            'target_weight': '.95', 'slot_usd': '140', 'buy_fee_reserve_usd': '.01',
            'quantity_step': '.000000001', 'blackouts': source['blackouts'],
            'source_receipt': source['receipt']['receipt_sha256'],
            'signal': 'dated commercial stocks excluding SPR / same-release comparable year ago - 1',
            'publication': 'date-only available next calendar midnight NY; next regular open; newest observation wins',
            'staleness': 'local execution date more than 14 calendar days after last usable publication',
            'state': 'cash-to-long sizes; long-to-cash all; unchanged long retains quantities',
            'partition': 'flat start; publication availability inside partition; last-open liquidation, no entry',
            'cash': 'conservative first regular open after documented current-T+1 settlement completion'}


def events(source, params, bp, final, observed):
    """Source-derived event construction remains lazy until durable admission."""
    if bp not in COSTS:
        raise ValueError('cost outside fixed C08 cases')
    split = split_for(source)
    eligible = sorted((r for r in source['releases']
        if split.contains(datetime.fromisoformat(r['available_at']), final_holdout=final)),
        key=lambda r: (r['available_at'], r['observation_date']))
    cursor = 0
    opens = [r['opens_at'] for r in source['prices']
             if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final)]
    if not opens:
        raise ValueError('C08 selected partition has no execution session')
    terminal = max(opens, key=datetime.fromisoformat)
    for row in source['prices']:
        opened, closed = (datetime.fromisoformat(row[k]) for k in ('opens_at', 'closes_at'))
        if split.contains(opened, final_holdout=final):
            releases = []
            while cursor < len(eligible) and datetime.fromisoformat(eligible[cursor]['available_at']) <= opened:
                releases.append(eligible[cursor]); cursor += 1
            event = scenario_quote(params['uso_id'], opened, D(row['open']), bp, phase='open',
                source='frozen_c08_open_reference', reference_open=row['open'],
                releases=releases, terminal_open=row['opens_at'] == terminal)
            observed.append(event)
            yield event
        if split.contains(closed, final_holdout=final):
            for iid, price, metadata in (
                (params['spy_benchmark_id'], row['spy_close'], {'symbol': 'SPY', 'distribution': row['spy_distribution']}),
                (params['uso_id'], row['close'], {'symbol': 'USO', 'benchmark_close': row['uso_split_continuous_close']})):
                event = MarketEvent.quote(iid, closed, mid=D(price), meta={'phase': 'close', 'mark_only': True, **metadata})
                observed.append(event)
                yield event


def marked_period(curve, first, exclusive_last):
    previous, values = D(140), []
    for stamp, value in curve:
        day = stamp.astimezone(NEW_YORK).date().isoformat()
        if first <= day < exclusive_last:
            if not values:
                values.append(previous)
            values.append(value)
        previous = value
    return {'covered': bool(values), 'marked_net_usd': str(values[-1] - values[0]) if values else None,
            'marked_drawdown': drawdown(values) if values else None}


def diagnostics(bot, source, observed, trips, fills, runtime, final):
    split = split_for(source)
    curve = runtime.curve
    # Calendar-month marked changes include months with no closed trip and do
    # not move a multi-month position's entire outcome into its exit month.
    month_ends = {}
    for stamp, value in curve:
        month_ends[stamp.astimezone(NEW_YORK).strftime('%Y-%m')] = value
    previous, monthly = D(140), {}
    for month, equity in sorted(month_ends.items()):
        monthly[month] = equity - previous
        previous = equity
    def regime(first, last):
        completed = [t for t in trips if first <= t.exit_ts.astimezone(NEW_YORK).date().isoformat() < last]
        executed = [f for f in fills if first <= f.fill_ts.astimezone(NEW_YORK).date().isoformat() < last]
        return {**marked_period(curve, first, last), 'round_trips_by_exit': len(completed),
            'net_usd_by_exit': str(sum((t.net_pnl for t in completed), ZERO)), 'fills': len(executed),
            'fees_usd_by_fill_date': str(sum((f.fee for f in executed), ZERO)),
            'turnover_usd': str(sum((f.price * f.size for f in executed), ZERO))}
    calendar_regimes = {}
    for name, lo, hi in [('2006-2009', '2006', '2010'), ('2010-2019', '2010', '2020'),
                          ('2020-2021', '2020', '2022'), ('2022', '2022', '2023'), ('2023-2026', '2023', '2027')]:
        calendar_regimes[name] = regime(lo + '-01-01', hi + '-01-01')
    exposure_regimes = {r['name']: {**r, **regime(r['start'], r['end'])} for r in source['exposure_regimes']}
    benchmark_values = {'SPY': [], 'USO': []}
    previous_spy = first_uso = None
    spy_factor = D(1)
    for event in observed:
        if event.meta.get('phase') != 'close':
            continue
        if event.meta.get('symbol') == 'SPY':
            if previous_spy is not None:
                spy_factor *= (event.mid + D(event.meta['distribution'])) / previous_spy
            previous_spy = event.mid
            benchmark_values['SPY'].append(D(140) * spy_factor)
        elif event.meta.get('symbol') == 'USO':
            close = D(event.meta['benchmark_close'])
            first_uso = close if first_uso is None else first_uso
            benchmark_values['USO'].append(D(140) * close / first_uso)
    benchmarks = {name: {'total_return': str(values[-1] / 140 - 1) if values else None,
        'max_drawdown': drawdown(values), 'not_executable': True,
        'basis': 'same replay close observations; expenses embedded, no trading costs; USO split-continuous benchmark only'}
        for name, values in benchmark_values.items()}
    benchmarks['cash'] = {'total_return': '0', 'not_executable': True}
    forced = [f for f in fills if f.metadata_['research']['forced_blackout_exit']]
    reentry = [f for f in fills if f.metadata_['research']['blackout_reentry']]
    def leg_cost(rows):
        return {'fills': len(rows), 'fees_usd': str(sum((f.fee for f in rows), ZERO)),
            'adverse_reference_cost_usd': str(sum((abs(f.price - D(f.metadata_['research']['execution']['reference_open'])) * f.size
                for f in rows), ZERO))}
    blackout_dates = [row['date'] for row in source['prices']
        if split.contains(datetime.fromisoformat(row['opens_at']), final_holdout=final)
        and any(p['exit'] <= row['date'] < p['reentry'] for p in source['blackouts'])]
    close_times = {e.time for e in observed if e.meta.get('phase') == 'close'}
    close_equity = {t: value for t, value in curve if t in close_times}
    return {'inventory_decisions': bot.decisions, 'skips': bot.skips,
        'cash_delay_skips': [s for s in bot.skips if 'cash' in s['reason']],
        'monthly_marked_net_usd': json_value(monthly), 'luck': monthly_luck(monthly, len(trips)),
        'calendar_regimes': calendar_regimes, 'uso_exposure_regimes': exposure_regimes,
        'marked_calendar_years': {str(year): regime(f'{year}-01-01', f'{year+1}-01-01')
            for year in sorted({t.astimezone(NEW_YORK).year for t, _ in curve})},
        'max_marked_drawdown': drawdown([D(140)] + [v for _, v in curve]),
        'max_daily_close_drawdown': drawdown([D(140)] + list(close_equity.values())),
        'turnover_usd': str(sum((f.price * f.size for f in fills), ZERO)),
        'gross_usd': str(sum((t.gross_pnl for t in trips), ZERO)),
        'terminal_liquidation_fills': sum(f.metadata_['research']['terminal_liquidation'] for f in fills),
        'blackout': {'sessions': blackout_dates, 'count': len(blackout_dates),
                     'forced_exit_cost': leg_cost(forced), 'reentry_cost': leg_cost(reentry)},
        'benchmarks': benchmarks, 'promotion_eligible': False,
        'promotion_reason': 'Amendment21 research counterfactual; separate actual-action, cash and execution evidence required before forward promotion'}


def require_committed():
    paths = ['src/tradingbot/' + name for name in dependencies()]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C08 dependencies before real strategy outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, threshold, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if final:
        consumed = session.scalar(select(Trial).join(StrategyRow, Trial.strategy_id == StrategyRow.id).where(
            Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C08-amendment21').order_by(Trial.id))
        if consumed is not None:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused C08 family final reuse despite source/run/version identity changes',
                details={'kind': 'holdout_reuse', 'first_trial_id': consumed.id,
                         'candidate': 'C08-amendment21', 'requested_source_receipt': SOURCE_RECEIPT}))
            session.commit()
            raise ValueError('C08 Amendment21 family final already consumed; read stored evidence')
    key = f'c08-a21-{source["receipt"]["identity"]["data_sha256"][:12]}-{threshold}-{bp}-' + ('final' if final else 'train')
    prior = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if prior:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C08 final invocation before feed construction',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': prior, 'source_receipt': SOURCE_RECEIPT}))
            session.commit()
        raise ValueError('C08 configuration already attempted; read stored results, never replay')
    if threshold not in THRESHOLDS or bp not in COSTS or final and bp != 10:
        raise ValueError('C08 configuration outside frozen variant/cost family')
    CaptureDiskBudget(ROOT / 'data').check()
    uso, venue = instrument_for(session, 'USO')
    spy, _ = instrument_for(session, 'SPY')
    params = strategy_params(source, uso, spy, threshold)
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp_per_side': bp, 'dependencies': dependencies(),
               'fx_source_sha256': fx.source_hash, 'source_receipt': source['receipt']['receipt_sha256'],
               'fee_policy': 'EquityFeeBook 2026-09-17 current-account counterfactual'}
    row = StrategyRow(key=key, name=f'C08 inventory {threshold} / {bp}bp ' + ('final' if final else 'training'),
        venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C08-amendment21', 'params': params})
    session.add(row); session.commit()
    sid, split = row.id, split_for(source)
    runtime = None
    calculated = None
    try:
        bot = InventoryScarcity(params)
        runtime = C08Backtester(session, strategy=bot, strategy_id=sid, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and (not expected_version or calculated != expected_version):
            raise ValueError('C08 final version differs from frozen choice before feed construction')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C08 fixed inventory scarcity/Amendment21; dated original EIA tables, actual-share prices, conservative T+1 cash.')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, source, observed, trips, fills, runtime, final))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'c08-amendment21-v1'
        trial.metrics = json_value(metrics)
        trial.max_drawdown = runtime.max_drawdown
        p = metrics['luck']['p_value']
        trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'threshold': threshold, 'cost_bp': bp, 'final_holdout': final,
            'trial_id': trial.id, 'strategy_id': sid, 'git_commit': commit, 'version_params': version,
            'strategy_version': trial.strategy_version, 'metrics': json_value(metrics),
            'trades': json_value([vars_trip(t) for t in trips]), 'curve': json_value(runtime.curve),
            'fill_ids': [f.id for f in fills]}
    except BaseException as error:
        if not session.is_active:
            session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=sid, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=split.data_start, data_end=split.data_end,
                strategy_version=calculated, params={'strategy': params, 'version_params': version,
                    'requested_final': final, 'final_feed_consumed': False, '_holdout': split.metadata()})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c08-amendment21-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C08 attempt failed; existing fills and consumed final preserved: {type(error).__name__}: {error}'
        if runtime is not None:
            trial.max_drawdown = runtime.max_drawdown
            trial.fees_total = runtime.charged
            trial.pnl_after_fees = runtime.realized - runtime.charged
            trial.metrics = json_value({'complete_execution': False, 'partial_replay': True,
                'last_processed_at': runtime.now, 'fees_usd': runtime.charged,
                'realized_net_usd': runtime.realized - runtime.charged,
                'ending_marked_equity_usd': runtime.equity(), 'max_marked_drawdown_usd': runtime.max_drawdown,
                'open_positions': runtime.positions, 'halt_events': runtime.halt_events,
                'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception):
            raise
        return {'status': 'failed', 'threshold': threshold, 'cost_bp': bp, 'final_holdout': bool(trial.final_holdout),
                'requested_final': final, 'trial_id': trial.id, 'strategy_id': sid,
                'git_commit': commit, 'error': str(error), 'strategy_version': trial.strategy_version,
                'metrics': trial.metrics}


def immutable_artifact(name, body):
    raw = (json.dumps(json_value(body), indent=2, sort_keys=True) + '\n').encode()
    path = ARCHIVE / 'runs' / name
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C08 outcome artifact')
        if not path.exists():
            path.write_bytes(raw)
    return path, sha(raw)


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
            print(json.dumps({k: result.get(k) for k in ('threshold', 'cost_bp', 'trial_id', 'status', 'error')}), flush=True)
    eligible = [r for r in results if r['status'] == 'complete' and r['cost_bp'] == 10
                and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -THRESHOLDS.index(r['threshold']))) if eligible else None
    choice = {'source_receipt': SOURCE_RECEIPT, 'dependencies': dependencies(), 'split': source['receipt']['split'],
              'training': results, 'selected': selected['threshold'] if selected else None,
              'selected_strategy_version': selected['strategy_version'] if selected else None,
              'rule': 'highest positive complete 10bp training net; listed threshold order breaks ties',
              'holdout_attempted': False, 'promotion_eligible': False}
    path, digest = immutable_artifact('selection.json', choice)
    (ROOT / 'docs/research/22-c08-selection.json').write_bytes(path.read_bytes())
    print(json.dumps({'selected': choice['selected'], 'selection_sha256': digest, 'final_attempted': False}))


def final():
    source = load_source()
    commit = require_committed()
    name = 'docs/research/22-c08-selection.json'
    committed = subprocess.check_output(['git', 'show', commit + ':' + name], cwd=ROOT)
    if (ROOT / name).read_bytes() != committed:
        raise ValueError('C08 selection must be committed before final')
    choice = json.loads(committed)
    if (choice['source_receipt'] != SOURCE_RECEIPT or choice['dependencies'] != dependencies()
            or choice['split'] != source['receipt']['split'] or choice['selected'] not in THRESHOLDS):
        raise ValueError('no valid frozen profitable C08 choice')
    chosen = next(r for r in choice['training'] if r['threshold'] == choice['selected'] and r['cost_bp'] == 10)
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != choice['selected_strategy_version']
                or trial.metrics != chosen['metrics'] or D(trial.metrics['net_usd']) <= 0
                or not trial.metrics['complete_execution']):
            raise ValueError('C08 frozen choice disagrees with durable training evidence')
        result = run_variant(session, source, choice['selected'], 10, final=True,
                             expected_version=choice['selected_strategy_version'])
    path, digest = immutable_artifact('final.json', result)
    receipt = {k: v for k, v in result.items() if k not in {'curve', 'trades', 'fill_ids'}}
    receipt.update({'artifact': str(path.relative_to(ROOT)), 'artifact_sha256': digest,
                    'selection_sha256': sha(committed), 'promotion': 'none'})
    (ROOT / 'docs/research/22-c08-final.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'trial_id': result['trial_id'], 'status': result['status'],
                     'net_usd': result.get('metrics', {}).get('net_usd'), 'promotion': 'none'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('train', 'final'))
    args = parser.parse_args()
    train() if args.phase == 'train' else final()


if __name__ == '__main__':
    main()
