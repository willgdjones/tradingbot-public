"""Frozen classic-TA research batch: source audit, shared replay, one final/rule."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.data.free_history import archive_capture, load_capture
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c11_total_return as shared
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityResearchLedger
from tradingbot.research.total_return_data import (
    ROOT, sha, yahoo_prices, capture_alpaca, alpaca_prices, nasdaq_prices,
    dividend_adjusted_reference, cross_check, capture_stooq, stooq_prices,
)
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.classic_ta import ClassicTA, RULES

ARCHIVE = ROOT/'data/research/classic-ta'
PLAN = ROOT/'docs/research/47-classic-ta-plan.md'
SYMBOLS = ('SPY', 'QQQ', 'AAPL', 'MSFT')
START, END = datetime(2016, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
ZERO = D(0)


def write_once(name, value):
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2)+'\n').encode()
    path = ARCHIVE/name
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of classic TA artifact: '+name)
        if not path.exists():
            path.write_bytes(raw)
    return sha(raw)


def freeze_source():
    """Capture prices and compare sources without constructing strategy signals."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    cm, calendar_source = spy_source()
    calendar = [r for r in calendar_source['prices'] if START.date() <= date.fromisoformat(r['date']) < END.date()]
    expected = {date.fromisoformat(r['date']) for r in calendar}
    inputs = {cm['data_path']: sha((ROOT/cm['data_path']).read_bytes())}
    all_dir = capture_alpaca(SYMBOLS, START.date(), END.date(), archive=ARCHIVE)
    all_prices, all_meta = alpaca_prices(all_dir)
    splits_dir = capture_alpaca(SYMBOLS, START.date(), END.date(), archive=ARCHIVE, adjustment='split')
    splits, split_meta = alpaca_prices(splits_dir, adjustment='split')
    for p in (*all_dir.glob('*'), *splits_dir.glob('*')):
        if p.is_file(): inputs[str(p.relative_to(ROOT))] = sha(p.read_bytes())
    panels = {}
    for symbol in SYMBOLS:
        folder = ARCHIVE/'yahoo'/symbol
        if not folder.exists():
            with CaptureDiskBudget(ROOT/'data').reserve(8_000_000):
                archive_capture(symbol, START.date(), END.date(), ARCHIVE/'yahoo')
        rows, primary = yahoo_prices(folder, symbol, START.date(), END.date())
        _, bars = load_capture(folder)
        by_day = {b.date: b for b in bars}
        for day, row in rows.items():
            row['high'], row['low'] = by_day[day].high*row['factor'], by_day[day].low*row['factor']
            # Source integrity only; do not run a signal here.
            if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']):
                raise ValueError('contradictory OHLC '+symbol+' '+str(day))
        primary_prices = {d: r['close'] for d, r in rows.items()}
        checks = {'alpaca': cross_check(primary_prices, all_prices.get(symbol, {}))}
        errors = {}
        if not checks['alpaca']['passed']:
            try:
                _, raw = capture_stooq(symbol, START.date(), END.date(), archive=ARCHIVE)
                checks['stooq'] = cross_check(primary_prices, stooq_prices(raw))
            except (ValueError, KeyError) as error:
                errors['stooq'] = str(error)
            if not any(c['passed'] for c in checks.values()):
                # Nasdaq's existing parser explicitly requests ETF data; use it
                # only for ETFs. Stocks retain the independently adjusted sources.
                if symbol in ('SPY', 'QQQ'):
                    try:
                        prices, _ = nasdaq_prices(symbol, START.date(), END.date()-timedelta(days=1), archive=ARCHIVE)
                        independent = dividend_adjusted_reference(prices, all_prices[symbol], splits[symbol])
                        checks['nasdaq_alpaca'] = cross_check(primary_prices, independent)
                    except (ValueError, KeyError) as error:
                        errors['nasdaq_alpaca'] = str(error)
        panels[symbol] = {'primary': primary, 'checks': checks, 'errors': errors,
            'missing_sessions': sorted(str(d) for d in expected-rows.keys()),
            'extra_sessions': sorted(str(d) for d in rows.keys()-expected),
            'passed': set(rows) == expected and any(c['passed'] for c in checks.values()),
            'prices': [{k: r[k] for k in ('date', 'opens_at', 'closes_at', 'conservative_cash_release')} |
                       {'quote': rows[date.fromisoformat(r['date'])]} for r in calendar if date.fromisoformat(r['date']) in rows]}
        print(json.dumps({'symbol': symbol, 'passed': panels[symbol]['passed'],
            'checks': {k: c['agreement_percent'] for k, c in checks.items()}, 'errors': errors}), flush=True)
    for p in ARCHIVE.rglob('*'):
        if p.is_file(): inputs[str(p.relative_to(ROOT))] = sha(p.read_bytes())
    with session_scope() as session:
        iex = [dict(r) for r in session.execute(text("""
            SELECT symbol, min(bar_start) AS first, max(bar_start) AS last,
              count(distinct (bar_start AT TIME ZONE 'America/New_York')::date) AS days
            FROM iex_minute_bars WHERE symbol IN ('SPY','QQQ','AAPL','MSFT')
              AND observed_at < '2026-10-04T00:00:00Z'
            GROUP BY symbol ORDER BY symbol
        """)).mappings()]
    source = {'panels': panels, 'inputs': inputs, 'secondary': {'all': all_meta, 'split': split_meta},
              'iex': iex, 'iex_cutoff': '2026-10-04T00:00:00Z', 'interval': [START, END]}
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
    return HoldoutSplit('classic-ta:'+source['sha256'], START, END)


class ClassicLedger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'classic_ta_total_return_equivalent', 'source_sha256': self.runtime.source_hash,
            'separate_dividend_credit': False}}
        return fill


class ClassicBacktester(shared.C11Backtester):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = ClassicLedger(self.session, self)


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
                # The completed daily high/low/close never travel on an open event.
                if phase == 'close':
                    meta['ohlc'] = {k: row['quote'][k] for k in ('open', 'high', 'low', 'close')}
                event = shared.scenario(iid, stamp, json_value(row['quote']), phase, 10, **json_value(meta))
                observed.append(event)
                yield event


def dependencies():
    return {**shared.dependencies(), **{p: sha((ROOT/'src/tradingbot'/p).read_bytes())
        for p in ('research/classic_ta.py', 'strategy/classic_ta.py')}}


def require_committed():
    paths = ['src/tradingbot/'+p for p in dependencies()]+[str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit code and plan before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def disposition(session, source, rule, symbol, kind, reason):
    key = f'classic-ta-{rule}-{symbol}-unattempted-v1'
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('disposition already logged')
    split = split_for(source)
    register_split(session, split)
    row = StrategyRow(key=key, name=f'Classic TA {rule} {symbol}', status='backtest', allocation_usd=ZERO,
        config={'research_only': True, 'research_family': 'classic_ta_'+rule})
    session.add(row); session.flush()
    trial = Trial(strategy_id=row.id, mode='backtest', status='failed', final_holdout=False,
        git_commit=require_committed(), code_version='classic-ta-v1', dataset_key=split.dataset_key,
        data_start=START, data_end=END, holdout_start=split.holdout_start, completed_ts=datetime.now(UTC),
        params={'rule': rule, 'symbol': symbol, 'source_sha256': source['sha256'], 'cost_bp': 10},
        metrics={'disposition': kind, 'reason': reason, 'outcomes_attempted': False, 'promotion_eligible': False},
        notes=reason)
    session.add(trial); session.commit()
    return {'rule': rule, 'symbol': symbol, 'trial_id': trial.id, 'status': kind, 'reason': reason}


def run_variant(session, source, rule, symbol, *, final=False, expected_version=None):
    commit = require_committed()
    if rule not in RULES or symbol not in SYMBOLS or not source['panels'][symbol]['passed']:
        raise ValueError('configuration or source not admitted')
    key = f'classic-ta-{rule}-{symbol}-'+('final' if final else 'train')+'-v1'
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated classic TA final before feed construction',
                details={'kind': 'holdout_reuse', 'rule': rule, 'symbol': symbol}))
            session.commit()
        raise ValueError('configuration already attempted; inspect durable trials')
    CaptureDiskBudget(ROOT/'data').check()
    iid, venue = shared.tr_instrument(session, symbol)
    params = {'rule': rule, 'symbol': symbol, 'instrument_id': iid, 'source_sha256': source['sha256'], 'slot_usd': '140'}
    fx = ReferenceFX(ROOT/'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': 10, 'dependencies': dependencies(), 'source_sha256': source['sha256'], 'fx_sha256': fx.source_hash}
    row = StrategyRow(key=key, name=f'Classic TA {rule} {symbol}', venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'research_family': 'classic_ta_'+rule, 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = ClassicTA(params)
        runtime = ClassicBacktester(session, strategy=bot, strategy_id=row.id,
            source={'sha256': source['sha256'], 'prices': source['panels'][symbol]['prices']}, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from frozen training version')
        observed = []
        result = runtime.run(events(source, symbol, iid, final, observed), split=split, final_holdout=final,
            version_params=version, notes='Classic TA defaults; long/flat, adjusted equivalents, settled cash, 10bp/side plus fees')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(shared.diagnostics(bot, observed, trips, fills, runtime))
        metrics.pop('weekday_expiry_structure_break')
        metrics['calendar_regimes'].pop('2006-2009')
        metrics['calendar_regimes']['2016-2019'] = metrics['calendar_regimes'].pop('2010-2019')
        metrics['benchmarks'][symbol+'_buy_hold'] = metrics['benchmarks'].pop('SPY_buy_hold')
        clusters = len({t.exit_ts.strftime('%Y-%m') for t in trips})
        metrics['luck'] = shared.monthly_luck({m: D(v) for m, v in metrics['monthly_marked_net_usd'].items()}, clusters)
        metrics['luck']['exit_month_clusters'] = clusters
        metrics['turnover_usd'] = str(sum((f.price*f.size for f in fills), ZERO))
        metrics['gross_after_execution_costs_before_fees'] = str(sum((t.gross_pnl for t in trips), ZERO))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0 and not runtime.halt_events
        metrics['halt_events'] = runtime.halt_events
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'classic-ta-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl, trial.max_drawdown = D(metrics['net_usd']), D(metrics['net_usd'])+runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']; trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'rule': rule, 'symbol': symbol, 'final_holdout': final,
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
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'classic-ta-v1'
        trial.completed_ts, trial.notes = datetime.now(UTC), f'Partial outcome preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total = runtime.max_drawdown, runtime.charged
            trial.pnl_after_fees = runtime.realized-runtime.charged
            trial.metrics = json_value({'partial_replay': True, 'complete_execution': False,
                'last_processed_at': runtime.now, 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception): raise
        return {'status': 'failed', 'rule': rule, 'symbol': symbol, 'trial_id': trial.id,
                'final_holdout': trial.final_holdout, 'error': str(error), 'metrics': trial.metrics}


def train():
    source, results = load_source(), []
    for rule in (*RULES, 'macd', 'shooting_star', 'dual_thrust'):
        for symbol in SYMBOLS:
            with session_scope() as session:
                if rule == 'macd':
                    result = disposition(session, source, rule, symbol, 'SPEC_BLOCKED', 'Upstream interactive SMA periods have no default.')
                elif rule == 'shooting_star':
                    result = disposition(session, source, rule, symbol, 'NO_LONG_RULE', 'Only short-entry/cover; whole-sample and future-bar dependencies. No invented long rule.')
                elif rule == 'dual_thrust':
                    evidence = next((r for r in source['iex'] if r['symbol'] == symbol), {'days': 0})
                    if evidence['days'] >= 6:
                        raise ValueError('IEX coverage differs from reviewed source; require complete-session admission')
                    result = disposition(session, source, rule, symbol, 'DATA_FAIL', f"Only {evidence['days']} archived IEX session(s); five prior sessions plus replay required.")
                elif not source['panels'][symbol]['passed']:
                    result = disposition(session, source, rule, symbol, 'DATA_FAIL', 'Missing/contradictory adjusted daily prices; see frozen cross-check.')
                else:
                    result = run_variant(session, source, rule, symbol)
            digest = write_once(f'train-{rule}-{symbol}.json', result)
            results.append({k: v for k, v in result.items() if k not in ('curve', 'trades', 'fill_ids')} |
                           {'artifact_sha256': digest})
            print(json.dumps({k: result.get(k) for k in ('rule', 'symbol', 'status', 'trial_id', 'error')}), flush=True)
    selected = {}
    for rule in RULES:
        eligible = [r for r in results if r['rule'] == rule and r['status'] == 'complete'
                    and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
        selected[rule] = max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -SYMBOLS.index(r['symbol']))) if eligible else None
    choice = {'source_sha256': source['sha256'], 'dependencies': dependencies(), 'split': split_for(source).metadata(),
              'training': results, 'selected': selected}
    print(json.dumps({'selection_sha256': write_once('selection.json', choice),
                      'selected': {k: r['symbol'] if r else None for k, r in selected.items()}}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE/'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('commit selection hash before final')
    choice = json.loads(raw)
    if choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies():
        raise ValueError('frozen selection identity changed')
    for rule, chosen in choice['selected'].items():
        if chosen is None: continue
        with session_scope() as session:
            trial = session.get(Trial, chosen['trial_id'])
            if (trial is None or trial.status != 'complete' or trial.final_holdout
                    or trial.strategy_version != chosen['strategy_version'] or trial.metrics != chosen['metrics']
                    or D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
                raise ValueError('selection differs from durable training')
            result = run_variant(session, source, rule, chosen['symbol'], final=True, expected_version=chosen['strategy_version'])
        digest = write_once(f'final-{rule}.json', result)
        print(json.dumps({'rule': rule, 'trial_id': result['trial_id'], 'status': result['status'],
                          'net_usd': result.get('metrics', {}).get('net_usd'), 'sha256': digest}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'train', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
