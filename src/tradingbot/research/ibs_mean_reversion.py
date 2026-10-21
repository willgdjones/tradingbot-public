"""IBS mean reversion (tradingbot-kyn): source freeze, training, one final per symbol.

QQQ is the primary test and SPY the replication; each symbol is its own
strategy version with exact thresholds (no tuning). Primary prices are Yahoo
split/dividend-adjusted OHLC for 2006-2026. The second source is the Nasdaq
split-adjusted close times the Alpaca all/split dividend factor (2016+), with
direct Alpaca all-adjusted closes as a fallback; pre-2016 is single-source and
disclosed. 10 bp per side plus fees, settled cash, next-open fills.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import archive_capture, load_capture
from tradingbot.db.models import Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c11_total_return as shared
from tradingbot.research.c06_month_end import drawdown
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityResearchLedger
from tradingbot.research.total_return_data import (ROOT, sha, yahoo_prices, capture_alpaca, alpaca_prices,
    nasdaq_prices, dividend_adjusted_reference, cross_check)
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.ibs import IBSReversion

ARCHIVE = ROOT/'data/research/ibs-mean-reversion'
PLAN = ROOT/'docs/research/50-ibs-mean-reversion-plan.md'
SYMBOLS = ('QQQ', 'SPY')
START, END, COST_BP, ZERO = shared.START, shared.END, 10, D(0)


def write_once(name, value):
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2)+'\n').encode()
    path = ARCHIVE/name
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of IBS artifact: '+name)
        if not path.exists():
            path.write_bytes(raw)
    return sha(raw)


def freeze_source():
    """Capture and cross-check prices without computing any IBS signal."""
    references = ARCHIVE/'references'
    calendar_manifest, calendar_source = spy_source()
    calendar = calendar_source['prices']
    expected = {date.fromisoformat(r['date']) for r in calendar}
    all_dir = capture_alpaca(SYMBOLS, START.date(), END.date(), archive=references)
    all_prices, all_meta = alpaca_prices(all_dir)
    split_dir = capture_alpaca(SYMBOLS, START.date(), END.date(), adjustment='split', archive=references)
    split_prices, split_meta = alpaca_prices(split_dir, adjustment='split')
    inputs = {ROOT/calendar_manifest['data_path'], ROOT/'docs/research/13-equity-data-repair-spy-amendment.json'}
    inputs.update(p for p in (*all_dir.glob('*'), *split_dir.glob('*')) if p.is_file())
    panels = {}
    for symbol in SYMBOLS:
        folder = references/'yahoo'/symbol
        if not (folder/'manifest.json').exists():
            with CaptureDiskBudget(ROOT/'data').reserve(8_000_000):
                archive_capture(symbol, START.date(), END.date(), references/'yahoo')
        rows, primary = yahoo_prices(folder, symbol, START.date(), END.date())
        by_day = {b.date: b for b in load_capture(folder)[1]}
        for day, row in rows.items():
            raw = by_day[day]
            # Order is checked on the exact raw bar. Adjusted close is Yahoo's
            # adj_close, so high*factor can miss it by Decimal rounding only.
            if raw.low > min(raw.open, raw.close) or raw.high < max(raw.open, raw.close):
                raise ValueError('contradictory OHLC '+symbol+' '+str(day))
            high, low = raw.high*row['factor'], raw.low*row['factor']
            row['high'], row['low'] = max(high, row['open'], row['close']), min(low, row['open'], row['close'])
            if max(row['high']-high, low-row['low']) > row['close']*D('1e-20'):
                raise ValueError('adjusted OHLC beyond rounding '+symbol+' '+str(day))
        closes = {d: r['close'] for d, r in rows.items()}
        checks, errors = {}, {}
        try:
            nasdaq, nasdaq_meta = nasdaq_prices(symbol, START.date(), END.date()-timedelta(days=1), archive=references)
            inputs.update(p for p in (ROOT/nasdaq_meta['path']).glob('*') if p.is_file())
            checks['nasdaq_alpaca'] = cross_check(closes, dividend_adjusted_reference(
                nasdaq, all_prices[symbol], split_prices[symbol]))
        except (ValueError, KeyError) as error:
            errors['nasdaq_alpaca'] = str(error)
        if not any(c['passed'] for c in checks.values()):
            checks['alpaca'] = cross_check(closes, all_prices.get(symbol, {}))
        inputs.update([folder/'raw.json', folder/'manifest.json'])
        panels[symbol] = {'primary': primary, 'checks': checks, 'errors': errors,
            'missing_sessions': sorted(str(d) for d in expected-rows.keys()),
            'extra_sessions': sorted(str(d) for d in rows.keys()-expected),
            'passed': set(rows) == expected and any(c['passed'] for c in checks.values()),
            'prices': [{k: r[k] for k in ('date', 'opens_at', 'closes_at', 'conservative_cash_release')} |
                       {'quote': rows[date.fromisoformat(r['date'])]} for r in calendar
                       if date.fromisoformat(r['date']) in rows]}
        print(json.dumps({'symbol': symbol, 'passed': panels[symbol]['passed'], 'errors': errors,
            'checks': {k: c['agreement_percent'] for k, c in checks.items()}}), flush=True)
    source = {'candidate': 'IBS', 'panels': panels, 'secondary': {'all': all_meta, 'split': split_meta},
              'inputs': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(inputs)},
              'interval': [START, END], 'model': 'total_return_equivalent; no separate dividend cash'}
    print(json.dumps({'source_sha256': write_once('source.json', source)}), flush=True)


def load_source():
    raw = (ARCHIVE/'source.json').read_bytes()
    digest = sha(raw)
    if digest not in PLAN.read_text():
        raise ValueError('commit source hash in plan before outcomes')
    source = json.loads(raw)
    for name, expected in source['inputs'].items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise ValueError('frozen input changed: '+name)
    return {**source, 'sha256': digest}


def split_for(source):
    return HoldoutSplit('ibs-mean-reversion:'+source['sha256'], START, END)


class IBSLedger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'ibs_total_return_equivalent', 'source_sha256': self.runtime.source_hash,
            'separate_dividend_credit': False}}
        return fill


class IBSBacktester(shared.C11Backtester):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = IBSLedger(self.session, self)


def events(source, symbol, iid, final, observed):
    split = split_for(source)
    rows = source['panels'][symbol]['prices']
    terminal = max(r['opens_at'] for r in rows
        if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final))
    for row in rows:
        for phase, key in (('open', 'opens_at'), ('close', 'closes_at')):
            stamp = datetime.fromisoformat(row[key])
            if split.contains(stamp, final_holdout=final):
                meta = {'terminal_open': phase == 'open' and row[key] == terminal}
                # The completed bar's high/low/close never travel on an open event.
                if phase == 'close':
                    meta['ohlc'] = {k: row['quote'][k] for k in ('open', 'high', 'low', 'close')}
                event = shared.scenario(iid, stamp, json_value(row['quote']), phase, COST_BP, **json_value(meta))
                observed.append(event)
                yield event


def comparison(observed, trips, fills, runtime):
    """Per-trade percentages (for the published claim) and buy-and-hold at equal exposure."""
    closes = [e.mid for e in observed if e.meta['phase'] == 'close']
    exposure = (sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO)/len(runtime.daily_exposure)
                if runtime.daily_exposure else ZERO)
    matched = D(1)
    for previous, current in zip(closes, closes[1:]):
        matched *= 1+exposure*(current/previous-1)
    buys = [f for f in fills if f.side == 'buy']
    percents, sessions = [], []
    for trip in trips:
        cost = sum((f.price*f.size for f in buys if trip.entry_ts <= f.fill_ts < trip.exit_ts), ZERO)
        percents.append(trip.net_pnl/cost)
        sessions.append(sum(1 for e in observed if e.meta['phase'] == 'open' and trip.entry_ts < e.time <= trip.exit_ts))
    return {'equal_exposure_buy_hold': {'exposure': str(exposure), 'total_return': str(matched-1),
            'usd_on_140': str(D(140)*(matched-1)), 'max_drawdown': drawdown(
                [D(140)*(1+exposure*(c/closes[0]-1)) for c in closes]) if closes else None,
            'basis': 'constant average-exposure fraction of the symbol, rest cash; adjusted closes, no costs'},
        'mean_net_percent_per_trade': str(sum(percents, ZERO)/len(percents)*100) if percents else None,
        'mean_sessions_held': str(D(sum(sessions))/len(sessions)) if sessions else None,
        'claimed': {'trades_per_10y': 164, 'win_rate': '.74', 'mean_percent_per_trade': '.9',
                    'exposure': '.36', 'apr': '.15', 'note': 'Wealth-Lab QQQ, costs and sample unstated'}}


def dependencies():
    return {**shared.dependencies(), **{p: sha((ROOT/'src/tradingbot'/p).read_bytes())
        for p in ('research/ibs_mean_reversion.py', 'strategy/ibs.py')}}


def require_committed():
    paths = ['src/tradingbot/'+p for p in dependencies()]+[str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit code and plan before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def disposition(session, source, symbol, reason):
    key = f'ibs-{symbol}-unattempted-v1'
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('disposition already logged')
    split = split_for(source)
    register_split(session, split)
    row = StrategyRow(key=key, name=f'IBS mean reversion {symbol}', status='backtest', allocation_usd=ZERO,
        config={'research_only': True, 'research_family': 'ibs_mean_reversion'})
    session.add(row); session.flush()
    trial = Trial(strategy_id=row.id, mode='backtest', status='failed', final_holdout=False,
        git_commit=require_committed(), code_version='ibs-v1', dataset_key=split.dataset_key,
        data_start=START, data_end=END, holdout_start=split.holdout_start, completed_ts=datetime.now(UTC),
        params={'symbol': symbol, 'source_sha256': source['sha256'], 'cost_bp': COST_BP},
        metrics={'disposition': 'DATA_FAIL', 'reason': reason, 'outcomes_attempted': False, 'promotion_eligible': False},
        notes=reason)
    session.add(trial); session.commit()
    return {'symbol': symbol, 'trial_id': trial.id, 'status': 'DATA_FAIL', 'reason': reason}


def run_variant(session, source, symbol, *, final=False, expected_version=None):
    commit = require_committed()
    if symbol not in SYMBOLS or not source['panels'][symbol]['passed']:
        raise ValueError('symbol or source not admitted')
    key = f'ibs-{symbol}-'+('final' if final else 'train')+'-v1'
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated IBS final before feed construction',
                details={'kind': 'holdout_reuse', 'symbol': symbol}))
            session.commit()
        raise ValueError('configuration already attempted; inspect durable trials')
    CaptureDiskBudget(ROOT/'data').check()
    iid, venue = shared.tr_instrument(session, symbol)
    params = {'symbol': symbol, 'instrument_id': iid, 'source_sha256': source['sha256'], 'slot_usd': '140',
              'ibs_low': '.10', 'ibs_high': '.90'}
    fx = ReferenceFX(ROOT/'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': COST_BP, 'dependencies': dependencies(), 'source_sha256': source['sha256'],
               'fx_sha256': fx.source_hash}
    row = StrategyRow(key=key, name=f'IBS mean reversion {symbol}', venue_id=venue, status='backtest',
        allocation_usd=D(140), config={'research_only': True, 'research_family': 'ibs_mean_reversion', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = IBSReversion(params)
        runtime = IBSBacktester(session, strategy=bot, strategy_id=row.id,
            source={'sha256': source['sha256'], 'prices': source['panels'][symbol]['prices']}, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from frozen training version')
        observed = []
        result = runtime.run(events(source, symbol, iid, final, observed), split=split, final_holdout=final,
            version_params=version, notes='IBS 0.10/0.90 crosses; long/flat, adjusted equivalents, settled cash, 10bp/side plus fees')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(shared.diagnostics(bot, observed, trips, fills, runtime))
        metrics.pop('weekday_expiry_structure_break')
        metrics['benchmarks'][symbol+'_buy_hold'] = metrics['benchmarks'].pop('SPY_buy_hold')
        metrics.update(comparison(observed, trips, fills, runtime))
        clusters = len({t.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m') for t in trips})
        metrics['luck'] = shared.monthly_luck({m: D(v) for m, v in metrics['monthly_marked_net_usd'].items()}, clusters)
        metrics['luck']['exit_month_clusters'] = clusters
        metrics['turnover_usd'] = str(sum((f.price*f.size for f in fills), ZERO))
        metrics['gross_after_execution_costs_before_fees'] = str(sum((t.gross_pnl for t in trips), ZERO))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0 and not runtime.halt_events
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'ibs-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl, trial.max_drawdown = D(metrics['net_usd']), D(metrics['net_usd'])+runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']; trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'symbol': symbol, 'final_holdout': final,
            'trial_id': trial.id, 'strategy_id': row.id, 'strategy_version': trial.strategy_version,
            'git_commit': commit, 'metrics': json_value(metrics), 'trades': json_value([vars_trip(t) for t in trips]),
            'curve': json_value(runtime.curve), 'fill_ids': [f.id for f in fills]}
    except BaseException as error:
        if not session.is_active: session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=row.id, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=START, data_end=END, strategy_version=calculated,
                params={'strategy': params, 'version_params': version, 'requested_final': final})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'ibs-v1'
        trial.completed_ts, trial.notes = datetime.now(UTC), f'Partial outcome preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total = runtime.max_drawdown, runtime.charged
            trial.pnl_after_fees = runtime.realized-runtime.charged
            trial.metrics = json_value({'partial_replay': True, 'complete_execution': False,
                'last_processed_at': runtime.now, 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception): raise
        return {'status': 'failed', 'symbol': symbol, 'trial_id': trial.id,
                'final_holdout': trial.final_holdout, 'error': str(error), 'metrics': trial.metrics}


def train():
    source, results = load_source(), []
    for symbol in SYMBOLS:
        with session_scope() as session:
            if source['panels'][symbol]['passed']:
                result = run_variant(session, source, symbol)
            else:
                result = disposition(session, source, symbol, 'Missing/contradictory adjusted daily prices; see frozen cross-check.')
        digest = write_once(f'train-{symbol}.json', result)
        results.append({k: v for k, v in result.items() if k not in ('curve', 'trades', 'fill_ids')} |
                       {'artifact_sha256': digest})
        print(json.dumps({k: result.get(k) for k in ('symbol', 'status', 'trial_id', 'error')} |
                         {'net_usd': result.get('metrics', {}).get('net_usd')}), flush=True)
    # No selection between symbols: each positive, complete training run gets its one final.
    finals = [r for r in results if r['status'] == 'complete'
              and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
    choice = {'source_sha256': source['sha256'], 'dependencies': dependencies(), 'split': split_for(source).metadata(),
              'training': results, 'finals': {r['symbol']: {'trial_id': r['trial_id'],
                  'strategy_version': r['strategy_version']} for r in finals}, 'holdout_attempted': False}
    print(json.dumps({'selection_sha256': write_once('selection.json', choice), 'finals': list(choice['finals'])}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE/'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('commit selection hash before final')
    choice = json.loads(raw)
    if choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies():
        raise ValueError('frozen selection identity changed')
    for symbol in SYMBOLS:
        chosen = choice['finals'].get(symbol)
        if chosen is None: continue
        trained = next(r for r in choice['training'] if r['symbol'] == symbol)
        with session_scope() as session:
            trial = session.get(Trial, chosen['trial_id'])
            if (trial is None or trial.status != 'complete' or trial.final_holdout
                    or trial.strategy_version != chosen['strategy_version'] or trial.metrics != trained['metrics']
                    or D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
                raise ValueError('selection differs from durable training')
            result = run_variant(session, source, symbol, final=True, expected_version=chosen['strategy_version'])
        digest = write_once(f'final-{symbol}.json', result)
        print(json.dumps({'symbol': symbol, 'trial_id': result['trial_id'], 'status': result['status'],
                          'net_usd': result.get('metrics', {}).get('net_usd'), 'sha256': digest}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'train', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
