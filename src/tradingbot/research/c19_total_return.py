"""C19 adjusted-total-return research with one durable, frozen final."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c11_total_return as shared
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityBacktester, EquityResearchLedger
from tradingbot.research.total_return_data import (ROOT, ARCHIVE as PRICE_ARCHIVE, sha, yahoo_prices,
    alpaca_prices, nasdaq_prices, dividend_adjusted_reference, cross_check)
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.c19_correlation import CorrelationHedge, SYMBOLS, VARIANTS
from tradingbot.connectors.cash import NEW_YORK

ARCHIVE = ROOT / 'data/research/c19-total-return'
PLAN = ROOT / 'docs/research/43-c19-correlation-hedge-plan.md'
START, END, COSTS, ZERO = shared.START, shared.END, (5, 10), D(0)


def write_once(name, value):
    path = ARCHIVE / name
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2)+'\n').encode()
    with CaptureDiskBudget(ROOT / 'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C19 source/outcome artifact')
        if not path.exists(): path.write_bytes(raw)
    return str(path.relative_to(ROOT)), sha(raw)


def freeze_source():
    primary, checks, quotes, secondary, inputs = {}, {}, {}, {}, set()
    for symbol in SYMBOLS:
        comparison_path = PRICE_ARCHIVE / (('comparison-' if symbol == 'GLD' else 'nasdaq-comparison-')+symbol+'.json')
        saved = json.loads(comparison_path.read_bytes())
        quotes[symbol], primary[symbol] = yahoo_prices(ROOT/'data/research/c03'/symbol, symbol, START.date(), END.date())
        inputs.update([comparison_path, ROOT/primary[symbol]['raw_path'], ROOT/'data/research/c03'/symbol/'manifest.json'])
        if symbol == 'GLD':
            other, meta = alpaca_prices(ROOT/saved['secondary']['path'])
            reference, metadata = other[symbol], [meta]
            secondary[symbol] = meta
        else:
            all_rows, am = alpaca_prices(ROOT/saved['secondary']['alpaca_all']['path'])
            split_rows, sm = alpaca_prices(ROOT/saved['secondary']['alpaca_split']['path'], adjustment='split')
            closes, nm = nasdaq_prices(symbol, START.date(), END.date()-timedelta(days=1))
            reference = dividend_adjusted_reference(closes, all_rows[symbol], split_rows[symbol])
            metadata = [am, sm, nm]
            secondary[symbol] = {'alpaca_all': am, 'alpaca_split': sm, 'nasdaq': nm}
        for meta in metadata:
            inputs.update(p for p in (ROOT/meta['path']).glob('*') if p.is_file())
        checks[symbol] = cross_check({d: r['close'] for d, r in quotes[symbol].items()}, reference)
        if not checks[symbol]['passed'] or checks[symbol] != saved['check'] or primary[symbol] != saved['primary']:
            raise ValueError('missing or contradictory prices for '+symbol)
    manifest, calendar_source = spy_source()
    calendar = calendar_source['prices']
    expected = {date.fromisoformat(r['date']) for r in calendar}
    if any(set(prices) != expected for prices in quotes.values()):
        raise ValueError('missing primary session or unequal universe coverage')
    inputs.update([ROOT/manifest['data_path'], ROOT/'docs/research/13-equity-data-repair-spy-amendment.json'])
    prices = [{k: row[k] for k in ('date', 'opens_at', 'closes_at', 'conservative_cash_release')} |
        {'quotes': {s: quotes[s][date.fromisoformat(row['date'])] for s in SYMBOLS}} for row in calendar]
    source = {'candidate': 'C19', 'primary': primary, 'secondary': secondary, 'crosscheck': checks,
        'inputs': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(inputs)},
        'prices': prices, 'model': 'total_return_equivalent; no dividend cash/blackout'}
    path, digest = write_once('source.json', source)
    print(json.dumps({'source': path, 'source_sha256': digest, 'sessions_per_fund': len(prices),
        'agreement_percent': {s: c['agreement_percent'] for s, c in checks.items()}}))


def load_source():
    raw = (ARCHIVE/'source.json').read_bytes()
    digest, source = sha(raw), json.loads(raw)
    if digest not in PLAN.read_text():
        raise ValueError('C19 source hash must be in plan before replay')
    if set(source['crosscheck']) != set(SYMBOLS) or not all(c['passed'] for c in source['crosscheck'].values()):
        raise ValueError('unaccepted source comparison')
    for name, expected in source['inputs'].items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise ValueError('C19 source input changed: '+name)
    return {**source, 'sha256': digest}


def split_for(source):
    return HoldoutSplit('c19-total-return:'+source['sha256'], START, END)


def strategy_params(source, ids, variant):
    if variant not in VARIANTS or set(ids) != set(SYMBOLS):
        raise ValueError('outside C19 variant/universe')
    rows, months = source['prices'], {}
    for row in rows: months.setdefault(row['date'][:7], []).append(row['date'])
    return {'symbols':list(SYMBOLS),'instrument_ids':ids,'variant':variant,
        'slot_usd':'140','target_weight':'.95','cash_reserve_weight':'.05','buy_fee_reserve_usd':'.01',
        'quantity_step':'.000000001','blackouts':[], 'month_ends':[v[-1] for v in months.values()],
        'next_session':{a['date']:b['date'] for a,b in zip(rows,rows[1:])}, 'source_sha256':source['sha256'],
        'execution':'next open reductions then settled-cash frozen gaps; adverse-price full target/slot cap',
        'partition':'flat and L+1 completed same-session closes inside partition; terminal open liquidation only'}


class C19Ledger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'c19_total_return_equivalent', 'source_sha256': self.runtime.source_hash,
            'separate_dividend_credit': False,
            'terminal_liquidation': kwargs['order'].reason == 'C19 terminal liquidation'}}
        return fill


class C19Backtester(shared.C11Backtester):
    """Reuse adjusted-unit fees/durable admission; mark all funds atomically."""
    def __init__(self, *args, strategy, **kwargs):
        self.instrument_ids = strategy.params['instrument_ids']
        super().__init__(*args, strategy=strategy, **kwargs)
        self.ledger = C19Ledger(self.session, self)

    def observe(self, event):
        marks = event.meta.get('batch_marks')
        if marks is not None:
            if set(map(int, marks)) != set(self.instrument_ids.values()):
                raise ValueError('incomplete simultaneous mark batch')
            for iid, price in marks.items():
                value = D(price)
                if not value.is_finite() or value <= 0:
                    raise ValueError('invalid simultaneous mark')
                self.marks[int(iid)], self.observed[int(iid)] = value, event.time
        self.factor = D(event.meta['factor'])
        if not self.factor.is_finite() or self.factor <= 0:
            raise ValueError('invalid total-return factor')
        EquityBacktester.observe(self, event)
        if event.meta['phase'] == 'close' and event.meta['batch_last']:
            owned = sum((q*self.marks[i] for i, (q, _) in self.positions.items()), ZERO)
            self.daily_exposure.append({'date': event.time.astimezone(NEW_YORK).date().isoformat(),
                                       'fraction': str(owned/self.equity())})


def events(source, params, bp, final, observed):
    split = split_for(source)
    by_day = {r['date']: r for r in source['prices']}
    terminal = max(r['opens_at'] for r in source['prices']
                   if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final))
    for row in source['prices']:
        opened, closed = datetime.fromisoformat(row['opens_at']), datetime.fromisoformat(row['closes_at'])
        if split.contains(opened, final_holdout=final):
            marks = {str(params['instrument_ids'][s]): row['quotes'][s]['open'] for s in SYMBOLS}
            for phase in ('observe_open', 'reduce', 'buy'):
                for index, symbol in enumerate(SYMBOLS):
                    event = shared.scenario(params['instrument_ids'][symbol], opened, row['quotes'][symbol], 'open', bp,
                        terminal_open=row['opens_at'] == terminal, symbol=symbol,
                        batch_last=index == len(SYMBOLS)-1,
                        batch_marks=marks if index == 0 and phase == 'observe_open' else None)
                    event = replace(event, meta={**event.meta, 'phase': phase})
                    observed.append(event); yield event
        if split.contains(closed, final_holdout=final):
            next_day = params['next_session'].get(row['date'])
            admitted = bool(next_day and split.contains(datetime.fromisoformat(by_day[next_day]['opens_at']), final_holdout=final)
                            and by_day[next_day]['opens_at'] != terminal)
            marks = {str(params['instrument_ids'][s]): row['quotes'][s]['close'] for s in SYMBOLS}
            for index, symbol in enumerate(SYMBOLS):
                event = shared.scenario(params['instrument_ids'][symbol], closed, row['quotes'][symbol], 'close', bp,
                    symbol=symbol, batch_last=index == len(SYMBOLS)-1, batch_marks=marks if index == 0 else None,
                    next_open_in_partition=admitted)
                observed.append(event); yield event


def diagnostics(bot, observed, trips, fills, runtime):
    month_ends = {}
    for stamp, value in runtime.curve:
        month_ends[stamp.astimezone(NEW_YORK).strftime('%Y-%m')] = value
    previous, monthly = D(140), {}
    for month, value in sorted(month_ends.items()):
        monthly[month], previous = value-previous, value
    closes = {}
    for event in observed:
        if event.meta['phase'] == 'close':
            closes.setdefault(event.time, {})[event.meta['symbol']] = event.mid
    bases, spy, bonds, gold = None, [], [], []
    for _, batch in sorted(closes.items()):
        if set(batch) != set(SYMBOLS): raise ValueError('incomplete benchmark close batch')
        if bases is None: bases = batch
        spy.append(D(140)*batch['SPY']/bases['SPY'])
        bonds.append(D(70)*(batch['SPY']/bases['SPY']+batch['IEF']/bases['IEF']))
        gold.append(D(70)*(batch['SPY']/bases['SPY']+batch['GLD']/bases['GLD']))
    def regime(low, high):
        selected = [t for t in trips if low <= t.exit_ts.astimezone(NEW_YORK).date().isoformat() < high]
        return {**shared.period(runtime.curve, low, high), 'round_trips_by_exit': len(selected),
                'execution_net_usd_by_exit': str(sum((t.net_pnl for t in selected), ZERO))}
    exit_months = len({t.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m') for t in trips})
    luck = shared.monthly_luck(monthly, exit_months)
    luck['exit_month_clusters'] = exit_months
    return {'hedge_months':{s or 'cash':sum(d['hedge']==s for d in bot.decisions) for s in ('IEF','GLD',None)},
        'hedge_switches':sum(a['hedge']!=b['hedge'] for a,b in zip(bot.decisions,bot.decisions[1:]) if a['hedge'] and b['hedge']),
        'monthly_decisions': bot.decisions, 'skips': bot.skips,
        'cash_delay_skips': [r for r in bot.skips if 'cash delay' in r['reason']],
        'max_marked_drawdown': shared.drawdown([D(140)]+[v for _, v in runtime.curve]),
        'monthly_marked_net_usd': json_value(monthly), 'luck': luck,
        'calendar_regimes': {name: regime(lo, hi) for name, lo, hi in (
            ('2006-2009', '2006-01-01', '2010-01-01'), ('2010-2019', '2010-01-01', '2020-01-01'),
            ('2020-2021', '2020-01-01', '2022-01-01'), ('2022', '2022-01-01', '2023-01-01'),
            ('2023-2026', '2023-01-01', '2027-01-01'))},
        'marked_calendar_years': {str(y): regime(f'{y}-01-01', f'{y+1}-01-01')
            for y in sorted({t.astimezone(NEW_YORK).year for t, _ in runtime.curve})},
        'benchmarks': {name: {'total_return': str(v[-1]/140-1) if v else None,
            'max_drawdown': shared.drawdown(v), 'basis': 'partition completed closes, fixed initial weights, no costs'}
            for name, v in [('SPY_buy_hold', spy), ('SPY_IEF_50_50_buy_hold', bonds), ('SPY_GLD_50_50_buy_hold', gold)]} | {'cash': {'total_return': '0'}},
        'fees_usd': str(sum((f.fee for f in fills), ZERO)),
        'turnover_usd': str(sum((f.price*f.size for f in fills), ZERO)),
        'gross_after_execution_costs_before_fees': str(sum((t.gross_pnl for t in trips), ZERO)),
        'adverse_cost_usd': str(sum((abs(f.price-D(f.metadata_['research']['execution']['reference']))*f.size
                                    for f in fills), ZERO)),
        'terminal_liquidation_fills': sum(f.metadata_['research']['terminal_liquidation'] for f in fills),
        'daily_exposure': runtime.daily_exposure,
        'average_exposure': str(sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO)/len(runtime.daily_exposure))
            if runtime.daily_exposure else None, 'promotion_eligible': False}


def dependencies():
    return {**shared.dependencies(), **{p: sha((ROOT/'src/tradingbot'/p).read_bytes()) for p in (
        'research/c19_total_return.py', 'strategy/c19_correlation.py', 'strategy/c05_commodity_trend.py')}}


def require_committed():
    paths = ['src/tradingbot/'+p for p in dependencies()] + [str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C19 plan and dependencies before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if variant not in VARIANTS or bp not in COSTS or final and bp != 10:
        raise ValueError('configuration outside frozen C19 family')
    key = f'c19-tr-{source["sha256"][:12]}-{variant}-{bp}-' + ('final' if final else 'train')
    prior = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if prior:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C19 final before feed construction',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': prior, 'source_sha256': source['sha256']}))
            session.commit()
        raise ValueError('C19 configuration already attempted; inspect stored evidence')
    CaptureDiskBudget(ROOT/'data').check()
    instruments = {s: shared.tr_instrument(session, s) for s in SYMBOLS}
    ids, venue = {s: v[0] for s, v in instruments.items()}, instruments['SPY'][1]
    params, fx = strategy_params(source, ids, variant), ReferenceFX(ROOT/'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': bp, 'dependencies': dependencies(), 'source_sha256': source['sha256'],
        'fx_source_sha256': fx.source_hash, 'model': 'total_return_equivalent_v1',
        'fee_policy': 'dated 2026-09-17 raw-share equivalent'}
    row = StrategyRow(key=key, name=f'C19 {variant} {bp}bp', venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C19', 'research_family': 'c19', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = CorrelationHedge(params)
        runtime = C19Backtester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed selected version')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C19 correlation-conditioned hedge, total-return equivalent, virtual cash and conservative settlement')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, observed, trips, fills, runtime))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'c19-total-return-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl, trial.max_drawdown = D(metrics['net_usd']), D(metrics['net_usd'])+runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']; trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'variant': variant, 'cost_bp': bp, 'final_holdout': final,
            'trial_id': trial.id, 'strategy_id': row.id, 'git_commit': commit, 'strategy_version': trial.strategy_version,
            'version_params': version, 'metrics': json_value(metrics), 'trades': json_value([vars_trip(t) for t in trips]),
            'curve': json_value(runtime.curve), 'fill_ids': [f.id for f in fills]}
    except BaseException as error:
        if not session.is_active: session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=row.id, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=split.data_start, data_end=split.data_end,
                strategy_version=calculated, params={'strategy': params, 'version_params': version,
                    'requested_final': final, 'final_feed_consumed': False, '_holdout': split.metadata()})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c19-total-return-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C19 failed; any consumed final and partial fills preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total, trial.pnl_after_fees = runtime.max_drawdown, runtime.charged, runtime.realized-runtime.charged
            trial.metrics = json_value({'complete_execution': False, 'partial_replay': True,
                'last_processed_at': runtime.now, 'fees_usd': runtime.charged,
                'ending_marked_equity_usd': runtime.equity(), 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception): raise
        return {'status': 'failed', 'variant': variant, 'cost_bp': bp, 'final_holdout': bool(trial.final_holdout),
            'requested_final': final, 'trial_id': trial.id, 'strategy_id': row.id, 'git_commit': commit,
            'error': str(error), 'strategy_version': trial.strategy_version, 'metrics': trial.metrics}


def train():
    source, results = load_source(), []
    for variant in VARIANTS:
        for bp in COSTS:
            with session_scope() as session: result = run_variant(session, source, variant, bp)
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
        'rule': 'highest positive complete 10bp training net; listed order ties', 'holdout_attempted': False}
    _, digest = write_once('selection.json', choice)
    print(json.dumps({'selected': choice['selected'], 'selection_sha256': digest}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE/'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('selection hash must be in committed plan before final')
    choice = json.loads(raw)
    if (choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies()
            or choice['split'] != split_for(source).metadata() or choice['selected'] not in VARIANTS):
        raise ValueError('invalid or absent frozen C19 winner')
    chosen = next(r for r in choice['training'] if r['trial_id'] == choice['selected_trial_id'])
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != choice['selected_strategy_version'] or trial.metrics != chosen['metrics']
                or D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
            raise ValueError('frozen selection differs from durable training')
        result = run_variant(session, source, choice['selected'], 10, final=True, expected_version=choice['selected_strategy_version'])
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
