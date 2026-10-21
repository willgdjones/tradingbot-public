"""Option-income ETFs (tradingbot-ae1): source freeze, training grid, one final for the family.

XYLD and QYLD cover the whole 2014-2026 window and are the only selectable
funds. JEPI, JEPQ and SPYI started later; they get descriptive `hold` training
runs on their own history and can never take the family's final. PUTW is
delisted (no free history, not on Alpaca) and is not substituted. SPY and QQQ
are benchmarks only. Prices: Yahoo split/dividend-adjusted. The decisive
second source is Nasdaq official closes with Alpaca cash-dividend records
(source v2): Alpaca's own adjusted closes are cent-rounded, which alone moves
a ~$10 high-payout fund's daily return by more than 5 bp. 10 bp per side plus
fees, settled cash, next-open fills.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
import math
import subprocess

import pyarrow.parquet as pq
from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.alpaca_history import AlpacaHistoryAPI, capture_actions
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import archive_capture
from tradingbot.db.models import Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c11_total_return as shared
from tradingbot.research.c06_month_end import drawdown, monthly_luck
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityResearchLedger
from tradingbot.forward.c05_readiness import ProbeBudget
from tradingbot.research.total_return_data import (ROOT, sha, positive, yahoo_prices, capture_alpaca, alpaca_prices,
    nasdaq_prices, dividend_adjusted_reference, cross_check)
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.option_income import VARIANTS, OptionIncomeHold

ARCHIVE = ROOT/'data/research/option-income'
# v1 (source.json) used the cent-rounded Alpaca factor as the decisive check; kept, not used.
SOURCE = 'source-v2.json'
PLAN = ROOT/'docs/research/52-option-income-plan.md'
ELIGIBLE = ('XYLD', 'QYLD')
DESCRIPTIVE = ('JEPI', 'JEPQ', 'SPYI')
BENCHMARKS = ('SPY', 'QQQ')
SYMBOLS = ELIGIBLE+DESCRIPTIVE+BENCHMARKS
START, END, COST_BP, ZERO = datetime(2014, 1, 1, tzinfo=UTC), shared.END, 10, D(0)
# Peak-to-trough SPY closes, fixed before outcomes; the last one is in the holdout.
STRESS = (('2018-q4', '2018-09-20', '2018-12-24'), ('covid-2020', '2020-02-19', '2020-03-23'),
          ('bear-2022', '2022-01-03', '2022-10-12'), ('tariff-2025', '2025-02-19', '2025-04-08'))


def write_once(name, value):
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2)+'\n').encode()
    path = ARCHIVE/name
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of option-income artifact: '+name)
        if not path.exists():
            path.write_bytes(raw)
    return sha(raw)


def capture_dividends(archive):
    api, budget = AlpacaHistoryAPI(ROOT/'.env'), ProbeBudget()
    try:
        return capture_actions(lambda request: budget.call(lambda: api(request)), archive, 'option-income-20261015',
            symbols=SYMBOLS, start=START.date().isoformat(), end=END.date().isoformat()).directory
    finally:
        api.close()


def alpaca_dividends(folder):
    """Cash dividends per symbol and ex-date from checksummed archive pages; other action types are counted."""
    dividends, seen, other = {}, set(), {}
    for index, path in enumerate(sorted(folder.glob('page-*.parquet'))):
        row = pq.read_table(path).to_pylist()[0]
        if path.name != f'page-{index:08d}.parquet' or sha(row['response_json'].encode()) != row['response_sha256']:
            raise ValueError('corporate action page sequence or checksum changed')
        for kind, items in json.loads(row['response_json'], parse_float=D)['corporate_actions'].items():
            for item in items:
                if kind != 'cash_dividends':
                    other[kind] = other.get(kind, 0)+1
                    continue
                if item['id'] in seen:
                    continue
                seen.add(item['id'])
                day = date.fromisoformat(item['ex_date'])
                target = dividends.setdefault(item['symbol'], {})
                target[day] = target.get(day, ZERO)+positive(item['rate'])
    if not dividends:
        raise ValueError('empty corporate action capture')
    return dividends, other


def dividend_reference(closes, dividends):
    """Total-return levels from official closes: close / (previous close - cash dividend going ex).

    This is the adjusted-close convention (factor 1 - dividend/previous close).
    Coverage starts at the first recorded ex-date; earlier absence is unknown, not zero.
    """
    if not dividends:
        return {}, []
    days = sorted(d for d in closes if d >= min(dividends))
    levels, previous = {}, None
    for day in days:
        levels[day] = D(1) if previous is None else levels[previous]*closes[day]/(closes[previous]-dividends.get(day, ZERO))
        previous = day
    return levels, sorted(str(d) for d in dividends if d not in closes and d >= days[0])


def freeze_source():
    """Capture and cross-check prices without computing any strategy outcome."""
    references = ARCHIVE/'references'
    calendar_manifest, calendar_source = spy_source()
    calendar = [r for r in calendar_source['prices'] if START.date() <= date.fromisoformat(r['date']) < END.date()]
    all_dir = capture_alpaca(SYMBOLS, START.date(), END.date(), archive=references)
    all_prices, all_meta = alpaca_prices(all_dir)
    split_dir = capture_alpaca(SYMBOLS, START.date(), END.date(), adjustment='split', archive=references)
    split_prices, split_meta = alpaca_prices(split_dir, adjustment='split')
    inputs = {ROOT/calendar_manifest['data_path'], ROOT/'docs/research/13-equity-data-repair-spy-amendment.json'}
    actions_dir = capture_dividends(references)
    dividends, other_actions = alpaca_dividends(actions_dir)
    inputs.update(p for p in (*all_dir.glob('*'), *split_dir.glob('*'), *actions_dir.glob('*')) if p.is_file())
    panels = {}
    for symbol in SYMBOLS:
        folder = references/'yahoo'/symbol
        if not (folder/'manifest.json').exists():
            with CaptureDiskBudget(ROOT/'data').reserve(8_000_000):
                archive_capture(symbol, START.date(), END.date(), references/'yahoo')
        rows, primary = yahoo_prices(folder, symbol, START.date(), END.date())
        first = min(rows)
        # Sessions before a fund's first trade are not missing; gaps after it are.
        expected = {date.fromisoformat(r['date']) for r in calendar if date.fromisoformat(r['date']) >= first}
        closes = {d: r['close'] for d, r in rows.items()}
        checks, errors, unmatched = {}, {}, []
        nasdaq, nasdaq_meta = nasdaq_prices(symbol, START.date(), END.date()-timedelta(days=1), archive=references)
        inputs.update(p for p in (ROOT/nasdaq_meta['path']).glob('*') if p.is_file())
        reference, unmatched = dividend_reference(nasdaq, dividends.get(symbol, {}))
        checks['nasdaq_dividends'] = cross_check(closes, reference)
        # v1 rounded-factor checks, diagnostic only.
        try:
            checks['nasdaq_alpaca_factor'] = cross_check(closes, dividend_adjusted_reference(
                nasdaq, all_prices[symbol], split_prices[symbol]))
        except (ValueError, KeyError) as error:
            errors['nasdaq_alpaca_factor'] = str(error)
        checks['alpaca_adjusted'] = cross_check(closes, all_prices.get(symbol, {}))
        inputs.update([folder/'raw.json', folder/'manifest.json'])
        panels[symbol] = {'primary': primary, 'checks': checks, 'errors': errors, 'first_session': str(first),
            'decisive_check': 'nasdaq_dividends', 'dividend_ex_dates': len(dividends.get(symbol, {})),
            'first_recorded_ex_date': str(min(dividends[symbol])) if symbol in dividends else None,
            'ex_dates_without_official_close': unmatched,
            'full_coverage': first == date.fromisoformat(calendar[0]['date']),
            'missing_sessions': sorted(str(d) for d in expected-rows.keys()),
            'extra_sessions': sorted(str(d) for d in rows.keys()-expected),
            'passed': set(rows) == expected and checks['nasdaq_dividends']['passed'],
            'prices': [{k: r[k] for k in ('date', 'opens_at', 'closes_at', 'conservative_cash_release')} |
                       {'quote': rows[date.fromisoformat(r['date'])]} for r in calendar
                       if date.fromisoformat(r['date']) in rows]}
        print(json.dumps({'symbol': symbol, 'first': str(first), 'passed': panels[symbol]['passed'],
            'errors': errors, 'checks': {k: c['agreement_percent'] for k, c in checks.items()}}), flush=True)
    source = {'candidate': 'option-income ETFs', 'panels': panels, 'secondary': {'all': all_meta, 'split': split_meta},
              'inputs': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(inputs)},
              'excluded': {'PUTW': 'delisted: Yahoo has no data and Alpaca has no asset; not substituted'},
              'other_corporate_actions': other_actions, 'superseded': {'source.json': 'v1: decisive check was the '
                  'cent-rounded Alpaca all/split factor, failed XYLD/QYLD on rounding; raw closes agreed'},
              'interval': [START, END], 'model': 'total_return_equivalent; distributions reinvested, no separate cash'}
    print(json.dumps({'source_sha256': write_once(SOURCE, source)}), flush=True)


def load_source():
    raw = (ARCHIVE/SOURCE).read_bytes()
    digest = sha(raw)
    if digest not in PLAN.read_text():
        raise ValueError('commit source hash in plan before outcomes')
    source = json.loads(raw)
    for name, expected in source['inputs'].items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise ValueError('frozen input changed: '+name)
    return {**source, 'sha256': digest}


def split_for(source):
    return HoldoutSplit('option-income:'+source['sha256'], START, END)


class IncomeLedger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'option_income_total_return_equivalent', 'source_sha256': self.runtime.source_hash,
            'separate_dividend_credit': False}}
        return fill


class IncomeBacktester(shared.C11Backtester):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = IncomeLedger(self.session, self)


def events(source, symbol, iid, final, observed):
    split = split_for(source)
    rows = source['panels'][symbol]['prices']
    terminal = max(r['opens_at'] for r in rows
        if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final))
    for row in rows:
        for phase, key in (('open', 'opens_at'), ('close', 'closes_at')):
            stamp = datetime.fromisoformat(row[key])
            if split.contains(stamp, final_holdout=final):
                event = shared.scenario(iid, stamp, json_value(row['quote']), phase, COST_BP,
                                        terminal_open=phase == 'open' and row[key] == terminal)
                observed.append(event)
                yield event


def annualised(values):
    """CAGR and volatility of a daily value series (252 sessions a year)."""
    returns = [b/a-1 for a, b in zip(values, values[1:])]
    if len(returns) < 2:
        return {'cagr': None, 'volatility': None, 'return_over_volatility': None}
    growth = float(values[-1]/values[0])**(252/len(returns))-1
    mean = sum(returns, ZERO)/len(returns)
    vol = math.sqrt(float(sum(((r-mean)**2 for r in returns), ZERO))/(len(returns)-1)*252)
    return {'cagr': growth, 'volatility': vol, 'return_over_volatility': growth/vol if vol else None}


def comparison(source, observed, runtime):
    """The fund against SPY and QQQ on the same sessions: equal exposure, risk, stress windows."""
    days = [e.time.astimezone(NEW_YORK).date().isoformat() for e in observed if e.meta['phase'] == 'close']
    marks = {}
    for stamp, value in runtime.curve:
        marks[stamp.astimezone(NEW_YORK).date().isoformat()] = value
    strategy = [marks[d] for d in days if d in marks]
    exposure = (sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO)/len(runtime.daily_exposure)
                if runtime.daily_exposure else ZERO)
    result = {'exposure': str(exposure), 'strategy': {**annualised(strategy), 'max_drawdown': drawdown(strategy)},
              'basis': 'benchmarks: adjusted closes on the same sessions, no costs; equal exposure = '
                       'the strategy average exposure fraction held constantly (daily), rest cash'}
    for symbol in BENCHMARKS:
        closes = {r['date']: D(str(r['quote']['close'])) for r in source['panels'][symbol]['prices']}
        series = [closes[d] for d in days]
        matched = [D(140)]
        for previous, current in zip(series, series[1:]):
            matched.append(matched[-1]*(1+exposure*(current/previous-1)))
        result[symbol] = {'full': {'total_return': str(series[-1]/series[0]-1), **annualised(series),
                                   'max_drawdown': drawdown(series)},
                          'equal_exposure': {'usd_on_140': str(matched[-1]-140), **annualised(matched),
                                             'max_drawdown': drawdown(matched)}}
    stress = {}
    for name, low, high in STRESS:
        if low not in days or high not in days or low not in marks:
            stress[name] = {'covered': False}
            continue
        window = {'covered': True, 'strategy_return': str(marks[high]/marks[low]-1)}
        for symbol in BENCHMARKS:
            closes = {r['date']: D(str(r['quote']['close'])) for r in source['panels'][symbol]['prices']}
            window[symbol+'_return'] = str(closes[high]/closes[low]-1)
        stress[name] = window
    result['stress'] = stress
    return result


def dependencies():
    return {**shared.dependencies(), **{p: sha((ROOT/'src/tradingbot'/p).read_bytes())
        for p in ('research/option_income.py', 'strategy/option_income.py')}}


def require_committed():
    paths = ['src/tradingbot/'+p for p in dependencies()]+[str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit code and plan before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def grid():
    """Training runs in listed order: the selectable grid, then descriptive holds."""
    return [(s, v, True) for s in ELIGIBLE for v in VARIANTS]+[(s, 'hold', False) for s in DESCRIPTIVE]


def disposition(session, source, symbol, variant, eligible):
    """Record a fund whose prices failed the frozen check: DATA_FAIL, no outcome computed."""
    key = f'option-income-{symbol}-{variant}-unattempted-v1'
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('disposition already logged')
    split = split_for(source)
    register_split(session, split)
    row = StrategyRow(key=key, name=f'Option income {symbol} {variant}', status='backtest', allocation_usd=ZERO,
        config={'research_only': True, 'research_family': 'option_income_etf'})
    session.add(row); session.flush()
    reason = 'Missing/contradictory adjusted daily prices; see frozen cross-check.'
    trial = Trial(strategy_id=row.id, mode='backtest', status='failed', final_holdout=False,
        git_commit=require_committed(), code_version='option-income-v1', dataset_key=split.dataset_key,
        data_start=START, data_end=END, holdout_start=split.holdout_start, completed_ts=datetime.now(UTC),
        params={'symbol': symbol, 'variant': variant, 'source_sha256': source['sha256'], 'cost_bp': COST_BP},
        metrics={'disposition': 'DATA_FAIL', 'reason': reason, 'outcomes_attempted': False, 'promotion_eligible': False},
        notes=reason)
    session.add(trial); session.commit()
    return {'status': 'DATA_FAIL', 'symbol': symbol, 'variant': variant, 'selectable': eligible,
            'trial_id': trial.id, 'reason': reason}


def run_variant(session, source, symbol, variant, *, eligible, final=False, expected_version=None):
    commit = require_committed()
    if (symbol, variant, eligible) not in grid() or not source['panels'][symbol]['passed']:
        raise ValueError('configuration outside the frozen grid or source not admitted')
    if eligible and not source['panels'][symbol]['full_coverage'] or final and not eligible:
        raise ValueError('only a full-coverage fund can be selected or take the final')
    key = f'option-income-{symbol}-{variant}-'+('final' if final else 'train')+'-v1'
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('configuration already attempted; inspect durable trials')
    CaptureDiskBudget(ROOT/'data').check()
    iid, venue = shared.tr_instrument(session, symbol)
    params = {'symbol': symbol, 'variant': variant, 'instrument_id': iid, 'source_sha256': source['sha256'],
              'slot_usd': '140', 'selectable': eligible}
    fx = ReferenceFX(ROOT/'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': COST_BP, 'dependencies': dependencies(), 'source_sha256': source['sha256'],
               'fx_sha256': fx.source_hash}
    row = StrategyRow(key=key, name=f'Option income {symbol} {variant}', venue_id=venue, status='backtest',
        allocation_usd=D(140), config={'research_only': True, 'research_family': 'option_income_etf', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = OptionIncomeHold(params)
        runtime = IncomeBacktester(session, strategy=bot, strategy_id=row.id,
            source={'sha256': source['sha256'], 'prices': source['panels'][symbol]['prices']}, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from frozen training version')
        observed = []
        result = runtime.run(events(source, symbol, iid, final, observed), split=split, final_holdout=final,
            version_params=version, notes=f'Option-income {variant}; adjusted equivalents, settled cash, 10bp/side plus fees')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(shared.diagnostics(bot, observed, trips, fills, runtime))
        metrics.pop('weekday_expiry_structure_break')
        metrics['benchmarks'][symbol+'_buy_hold'] = metrics['benchmarks'].pop('SPY_buy_hold')
        metrics['comparison'] = comparison(source, observed, runtime)
        # A held position is one long bet; its months, not its single round trip, are the observations.
        months = sum(1 for v in metrics['monthly_marked_net_usd'].values() if D(v))
        metrics['luck'] = {**monthly_luck({m: D(v) for m, v in metrics['monthly_marked_net_usd'].items()}, months),
                           'months_with_marked_change': months}
        metrics['turnover_usd'] = str(sum((f.price*f.size for f in fills), ZERO))
        metrics['gross_after_execution_costs_before_fees'] = str(sum((t.gross_pnl for t in trips), ZERO))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0 and not runtime.halt_events
        metrics['first_session'] = source['panels'][symbol]['first_session']
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'option-income-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl, trial.max_drawdown = D(metrics['net_usd']), D(metrics['net_usd'])+runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']; trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'symbol': symbol, 'variant': variant, 'selectable': eligible,
            'final_holdout': final, 'trial_id': trial.id, 'strategy_id': row.id, 'strategy_version': trial.strategy_version,
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
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'option-income-v1'
        trial.completed_ts, trial.notes = datetime.now(UTC), f'Partial outcome preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total = runtime.max_drawdown, runtime.charged
            trial.pnl_after_fees = runtime.realized-runtime.charged
            trial.metrics = json_value({'partial_replay': True, 'complete_execution': False,
                'last_processed_at': runtime.now, 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception): raise
        return {'status': 'failed', 'symbol': symbol, 'variant': variant, 'selectable': eligible,
                'trial_id': trial.id, 'final_holdout': trial.final_holdout, 'error': str(error), 'metrics': trial.metrics}


def select_winner(results):
    """Highest positive, complete 10 bp training net among selectable runs; listed order breaks ties."""
    order = grid()
    eligible = [r for r in results if r['selectable'] and r['status'] == 'complete'
                and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
    if not eligible:
        return None
    return max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -order.index((r['symbol'], r['variant'], True))))


def train():
    source, results = load_source(), []
    for symbol, variant, eligible in grid():
        with session_scope() as session:
            if source['panels'][symbol]['passed']:
                result = run_variant(session, source, symbol, variant, eligible=eligible)
            else:
                result = disposition(session, source, symbol, variant, eligible)
        digest = write_once(f'train-{symbol}-{variant}.json', result)
        results.append({k: v for k, v in result.items() if k not in ('curve', 'trades', 'fill_ids')} |
                       {'artifact_sha256': digest})
        print(json.dumps({k: result.get(k) for k in ('symbol', 'variant', 'status', 'trial_id', 'error')} |
                         {'net_usd': result.get('metrics', {}).get('net_usd')}), flush=True)
    winner = select_winner(results)
    choice = {'source_sha256': source['sha256'], 'dependencies': dependencies(), 'split': split_for(source).metadata(),
              'training': results, 'selected': None if winner is None else {k: winner[k] for k in
                  ('symbol', 'variant', 'trial_id', 'strategy_version')},
              'rule': 'highest positive complete 10bp training net among XYLD/QYLD x hold/trend200; listed order ties',
              'holdout_attempted': False}
    print(json.dumps({'selection_sha256': write_once('selection.json', choice), 'selected': choice['selected']}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE/'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('commit selection hash before final')
    choice = json.loads(raw)
    if choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies():
        raise ValueError('frozen selection identity changed')
    chosen = choice['selected']
    if chosen is None:
        raise ValueError('no positive selectable training run; the family has no final')
    trained = next(r for r in choice['training'] if r['trial_id'] == chosen['trial_id'])
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != chosen['strategy_version'] or trial.metrics != trained['metrics']):
            raise ValueError('selection differs from durable training')
        result = run_variant(session, source, chosen['symbol'], chosen['variant'], eligible=True, final=True,
                             expected_version=chosen['strategy_version'])
    digest = write_once('final.json', result)
    print(json.dumps({'symbol': chosen['symbol'], 'variant': chosen['variant'], 'trial_id': result['trial_id'],
                      'status': result['status'], 'net_usd': result.get('metrics', {}).get('net_usd'), 'sha256': digest}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'train', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
