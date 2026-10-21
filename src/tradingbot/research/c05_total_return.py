"""C05 owner-authorized adjusted-total-return research revision (d267cf7)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
from pathlib import Path
import subprocess

import requests
from sqlalchemy import select

from tradingbot.backtest.holdout import json_value, strategy_identity
from tradingbot.data.alpaca_history import AlpacaHistoryAPI, NY
from tradingbot.data.archive import Request, canonical
from tradingbot.data.free_history import parse_yahoo
from tradingbot.db.models import Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c05_replay as prior
from tradingbot.research.c05_commodity_trend import load_source as yahoo_source
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.turn_of_month import instrument_for, vars_trip
from tradingbot.strategy.c05_commodity_trend import CommodityTrend

ROOT = prior.ROOT
ARCHIVE = ROOT / 'data/research/c05-total-return'
REVISION = 'total_return_d267cf7'
RESULTS = ROOT / 'docs/research/38-c05-total-return-results.md'


def write_once(path, value):
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2) + '\n').encode()
    with prior.CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(f'refusing to overwrite immutable artifact: {path.name}')
        if not path.exists():
            path.write_bytes(raw)
    return prior.sha(raw)


def compare_returns(primary, secondary):
    """Compare actual adjacent sessions, never bridge a missing reference day."""
    dates = sorted(primary)
    compared, disagreements, missing = 0, [], []
    if not secondary:
        raise ValueError('empty secondary prices')
    first, last = min(secondary), max(secondary)
    for a, b in zip(dates, dates[1:]):
        if a < first or b > last:
            continue
        if a not in secondary or b not in secondary:
            missing.append(str(b))
            continue
        values = (primary[a], primary[b], secondary[a], secondary[b])
        if any(not x.is_finite() or x <= 0 for x in values):
            raise ValueError('missing or invalid adjusted price')
        left, right = primary[b] / primary[a] - 1, secondary[b] / secondary[a] - 1
        compared += 1
        if abs(left - right) > D('.0005'):
            disagreements.append({'date': str(b), 'yahoo_return': str(left),
                'secondary_return': str(right), 'difference_bp': str(abs(left-right)*10000)})
    agreement = D(compared-len(disagreements)) / compared if compared else D(0)
    return {'comparisons': compared, 'agreement': str(agreement),
        'passed': compared > 0 and not missing and agreement >= D('.99'),
        'overlap_first': str(max(min(primary), min(secondary))),
        'overlap_last': str(min(max(primary), max(secondary))),
        'yahoo_sessions': len(primary), 'reference_sessions': len(secondary),
        'yahoo_sessions_outside_reference': sum(d not in secondary for d in primary),
        'missing_inside_overlap': missing, 'disagreements': disagreements}


def reference(symbol, adjustment='all'):
    if symbol not in prior.SYMBOLS or adjustment not in ('all', 'split'):
        raise ValueError('reference outside fixed source contract')
    prefix = 'alpaca' if adjustment == 'all' else 'alpaca-split'
    path = ARCHIVE / f'{prefix}-{symbol}.json'
    if path.exists():
        saved = json.loads(path.read_text())
        if saved['sha256'] != prior.sha(canonical(saved['pages']).encode()):
            raise ValueError('reference checksum changed')
        return saved
    api, pages = AlpacaHistoryAPI(), []
    params = {'symbols': symbol, 'timeframe': '1Day', 'start': '2008-01-01T00:00:00Z',
        'end': '2026-09-30T23:59:59Z', 'adjustment': adjustment, 'feed': 'sip',
        'limit': 10000, 'sort': 'asc', 'asof': '-'}
    request = Request('https://data.alpaca.markets/v2/stocks/bars', params)
    try:
        while True:
            body = api(request)
            doc = json.loads(body)
            pages.append({'request': json.loads(request.to_json()), 'raw': body,
                'retrieved_at': datetime.now(UTC).isoformat()})
            token = doc['next_page_token']
            if not token:
                break
            request = Request(request.url, {**params, 'page_token': token})
    finally:
        api.close()
    saved = {'pages': pages, 'sha256': prior.sha(canonical(pages).encode()),
        'free_existing_account': True, 'adjustment': adjustment, 'feed': 'sip'}
    write_once(path, saved)
    return saved


def nasdaq(symbol):
    """Public ten-year reference, no paid API, account or primary-series repair."""
    if symbol not in prior.SYMBOLS:
        raise ValueError('outside fixed source universe')
    path = ARCHIVE / f'nasdaq-{symbol}.json'
    if not path.exists():
        params = {'assetclass': 'etf', 'fromdate': '2008-01-01',
                  'todate': '2026-09-30', 'limit': 10000}
        response = requests.get(f'https://api.nasdaq.com/api/quote/{symbol}/historical',
            params=params, headers={'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json, text/plain, */*'}, timeout=(5, 25))
        write_once(path, {'url': response.url, 'status': response.status_code,
            'raw': response.text, 'retrieved_at': datetime.now(UTC).isoformat(),
            'sha256': prior.sha(response.content)})
    saved = json.loads(path.read_text())
    if saved['status'] != 200 or prior.sha(saved['raw'].encode()) != saved['sha256']:
        raise ValueError('Nasdaq response status or bytes changed')
    doc = json.loads(saved['raw'])['data']
    rows = doc['tradesTable']['rows']
    if doc['symbol'] != symbol or len(rows) != int(doc['totalRecords']):
        raise ValueError('missing Nasdaq rows or wrong symbol')
    prices = {}
    for row in rows:
        day = datetime.strptime(row['date'], '%m/%d/%Y').date()
        close = D(row['close'].replace('$', '').replace(',', ''))
        if day in prices or not close.is_finite() or close <= 0:
            raise ValueError('duplicate/invalid Nasdaq closing price')
        prices[day] = close
    if not prices:
        raise ValueError('empty Nasdaq prices')
    return saved, prices


def alpaca_closes(saved, symbol):
    prices = {}
    for page in saved['pages']:
        for bar in json.loads(page['raw'])['bars'].get(symbol, []):
            day = datetime.fromisoformat(bar['t'].replace('Z', '+00:00')).astimezone(NY).date()
            close = D(str(bar['c']))
            if day in prices or not close.is_finite() or close <= 0:
                raise ValueError('duplicate/invalid Alpaca price')
            prices[day] = close
    return prices


def dividend_adjusted_reference(nasdaq_closes, distributions):
    """Backward cash adjustment on split-adjusted Nasdaq closing prices.

    Ex-date cash amounts come from the already archived issuer/broker records.
    No Yahoo price/factor enters this independent reference, and cents-rounded
    Alpaca adjusted bars cannot add day-to-day adjustment rounding noise.
    """
    days = sorted(nasdaq_closes)
    if not days:
        raise ValueError('empty independent closes')
    dividends = {}
    for row in distributions:
        ex, amount = date.fromisoformat(row['ex_date']), D(row['amount'])
        if not amount.is_finite() or amount < 0 or ex in dividends:
            raise ValueError('invalid or duplicate reference dividend')
        if days[0] < ex <= days[-1]:
            if ex not in nasdaq_closes:
                raise ValueError('missing independent ex-date price')
            dividends[ex] = amount
    factor, result = D(1), {}
    for i in range(len(days)-1, -1, -1):
        day = days[i]
        result[day] = nasdaq_closes[day] * factor
        if day in dividends:
            previous = nasdaq_closes[days[i-1]]
            if not previous.is_finite() or previous <= dividends[day]:
                raise ValueError('invalid independent dividend adjustment')
            factor *= 1 - dividends[day] / previous
    return result


def prepare():
    source = prior.load_source()
    with ThreadPoolExecutor(max_workers=5) as pool:
        refs = dict(zip(prior.SYMBOLS, pool.map(reference, prior.SYMBOLS)))
        nasdaq_refs = dict(zip(prior.SYMBOLS, pool.map(nasdaq, prior.SYMBOLS)))
    yahoo, checks, inputs, sip_checks = {}, {}, {}, {}
    for symbol in prior.SYMBOLS:
        manifest, raw = yahoo_source(ROOT / 'data/research/c05' / symbol, symbol)
        meta, bars = parse_yahoo(raw.decode())
        if meta['null_rows']:
            raise ValueError('missing Yahoo prices')
        yahoo[symbol] = {str(b.date): b for b in bars}
        nasdaq_meta, nasdaq_prices = nasdaq_refs[symbol]
        secondary = dividend_adjusted_reference(nasdaq_prices,
            [r for r in source['distributions'] if r['symbol'] == symbol])
        checks[symbol] = compare_returns({b.date: b.adj_close for b in bars}, secondary)
        sip_checks[symbol] = compare_returns({b.date: b.adj_close for b in bars}, alpaca_closes(refs[symbol], symbol))
        inputs[symbol] = {'yahoo': manifest['sha256'], 'alpaca_all': refs[symbol]['sha256'],
            'nasdaq': nasdaq_meta['sha256']}
    if not (ARCHIVE / 'source-check.json').exists():
        write_once(ARCHIVE / 'source-check.json', sip_checks)
    write_once(ARCHIVE / 'nasdaq-total-return-source-check.json', checks)
    print(json.dumps({s: {k:v for k,v in r.items() if k not in {'disagreements'}} for s,r in checks.items()}), flush=True)
    if not all(r['passed'] for r in checks.values()):
        raise ValueError('contradictory adjusted prices: see nasdaq-total-return-source-check.json')
    for row in source['prices']:
        for symbol in prior.SYMBOLS:
            b = yahoo[symbol][row['date']]
            row['quotes'][symbol] = {'open': str(b.open*b.adj_close/b.close),
                'close': str(b.adj_close), 'adjusted_close': str(b.adj_close)}
    independent_distributions = source['distributions']
    source['blackouts'], source['distributions'] = [], []
    receipt = {'identity': {'inputs': inputs}, 'revision': REVISION,
        'split': prior.HoldoutSplit('c05-total-return-d267cf7', prior.START, prior.END).metadata(),
        'crosscheck': checks, 'price_basis': 'split/dividend-adjusted virtual total-return units'}
    receipt['reference_basis'] = 'Nasdaq split-adjusted closes; backward dividend adjustment using archived issuer/broker cash amounts and Nasdaq previous close'
    receipt['independent_distributions'] = independent_distributions
    receipt['distribution_source_receipt'] = prior.SOURCE_RECEIPT
    receipt['earlier_sip_diagnostic_sha256'] = prior.sha((ARCHIVE / 'source-check.json').read_bytes())
    receipt['identity']['data_sha256'] = prior.sha(canonical(source['prices']).encode())
    receipt['receipt_sha256'] = prior.sha(canonical(receipt).encode())
    source['receipt'] = receipt
    write_once(ARCHIVE / 'source.json', source)


def load_source():
    source = json.loads((ARCHIVE / 'source.json').read_text())
    receipt = dict(source['receipt'])
    digest = receipt.pop('receipt_sha256')
    if (prior.sha(canonical(receipt).encode()) != digest or
            prior.sha(canonical(source['prices']).encode()) != receipt['identity']['data_sha256'] or
            set(receipt['crosscheck']) != set(prior.SYMBOLS) or
            not all(r['passed'] and D(r['agreement']) >= D('.99') for r in receipt['crosscheck'].values()) or
            source['blackouts'] or source['distributions']):
        raise ValueError('total-return data or comparison changed')
    return source


class TotalReturnTrend(CommodityTrend):
    key = 'sweep_c05_commodity_trend_total_return_v1'


class TotalReturnLedger(prior.C05Ledger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'yahoo_adjusted_total_return_open_scenario',
            'units': 'virtual_total_return_equivalent', 'revision': REVISION}}
        return fill


class TotalReturnBacktester(prior.C05Backtester):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = TotalReturnLedger(self.session, self)


def events(source, params, bp, final, observed):
    scratch = []
    for event in prior.events(source, params, bp, final, scratch):
        converted = replace(event, meta={**event.meta,
            'source': ('spy_cash_dividend_total_return_benchmark' if event.meta['symbol'] == 'SPY'
                       else 'yahoo_adjusted_total_return_scenario'), 'research_revision': REVISION})
        scratch.clear()
        observed.append(converted)
        yield converted


def dependencies():
    return {**prior.dependencies(), 'research/c05_total_return.py': prior.sha(Path(__file__).read_bytes())}


def require_committed():
    paths = ['src/tradingbot/' + p for p in dependencies()]
    paths += ['docs/research/38-c05-total-return-plan.md']
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C05 plan and implementation before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if variant not in prior.VARIANTS or bp not in prior.COSTS or final and bp != 10:
        raise ValueError('case outside preregistration')
    key = f'c05-tr-d267cf7-{variant}-{bp}-' + ('final' if final else 'train')
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('case already attempted; read stored result')
    pairs = {s: instrument_for(session, s) for s in prior.SYMBOLS}
    spy, _ = instrument_for(session, 'SPY')
    params = prior.strategy_params(source, {s:p[0] for s,p in pairs.items()}, spy, variant)
    params.update({'dividends': 'embedded in adjusted prices, no separate cash credit',
        'blackout_reentry': 'disabled', 'research_revision': REVISION,
        'execution': 'adjusted-open total-return equivalent; reductions then pro-rata buys; settled cash'})
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp_per_side': bp, 'dependencies': dependencies(), 'fx_source_sha256': fx.source_hash,
        'source_receipt': source['receipt']['receipt_sha256'], 'research_revision': REVISION,
        'fee_policy': 'EquityFeeBook September 2026 on virtual adjusted units'}
    row = StrategyRow(key=key, name=f'C05 total-return {variant} {bp}bp', venue_id=pairs['GLD'][1],
        status='backtest', allocation_usd=D(140), config={'research_only': True, 'candidate': 'C05',
            'research_family': 'c05', 'research_revision': REVISION, 'params': params,
            'previous_final_trial': 3964, 'independent_confirmation': False})
    session.add(row); session.commit()
    runtime, calculated = None, None
    observed = []
    try:
        bot = TotalReturnTrend(params)
        runtime = TotalReturnBacktester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed training choice')
        result = runtime.run(events(source, params, bp, final, observed), split=prior.split_for(source),
            final_holdout=final, version_params=version,
            notes='Owner-authorized d267cf7 total-return equivalent revision; prior final3964 seen, not independent OOS.')
        metrics, trips, fills = prior.finish_metrics(session, result, runtime)
        metrics.update(prior.diagnostics(bot, source, observed, trips, fills, runtime, final))
        metrics.update({'complete_execution': not metrics['open_positions'] and result.orders_rejected == 0,
            'research_revision': REVISION, 'promotion_eligible': False,
            'promotion_reason': 'Prior C05 final inspected; repeated historical period is diagnostic',
            'source_price_basis': 'adjusted total-return equivalent; no separate dividends'})
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'c05-total-return-v1'
        trial.metrics, trial.pnl_after_fees = json_value(metrics), D(metrics['net_usd'])
        trial.pnl, trial.max_drawdown = D(metrics['net_usd']) + runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']
        trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status':'complete', 'variant':variant, 'cost_bp':bp, 'final_holdout':final,
            'trial_id':trial.id, 'strategy_id':row.id, 'git_commit':commit,
            'strategy_version':trial.strategy_version, 'metrics':json_value(metrics),
            'trades':json_value([vars_trip(t) for t in trips]), 'curve':json_value(runtime.curve),
            'fill_ids':[f.id for f in fills]}
    except BaseException as error:
        if not session.is_active:
            session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            split = prior.split_for(source)
            prior.register_split(session, split)
            trial = Trial(strategy_id=row.id, mode='backtest', final_holdout=False,
                dataset_key=split.dataset_key, holdout_start=split.holdout_start,
                strategy_version=calculated, params={'strategy':params, 'version_params':version,
                    'requested_final':final, 'final_feed_consumed':False, '_holdout':split.metadata()})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c05-total-return-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C05 total-return attempt failed; prior fills/final spend preserved: {type(error).__name__}: {error}'
        trial.metrics = json_value({'complete_execution':False, 'partial_replay':bool(observed),
            'last_processed_at':runtime.now if runtime else None, 'promotion_eligible':False,
            'open_positions':runtime.positions if runtime else {},
            'fees_usd':runtime.charged if runtime else None,
            'max_marked_drawdown_usd':runtime.max_drawdown if runtime else None})
        session.commit()
        if not isinstance(error, Exception):
            raise
        return {'status':'failed', 'variant':variant, 'cost_bp':bp, 'final_holdout':trial.final_holdout,
            'requested_final':final, 'trial_id':trial.id, 'strategy_id':row.id, 'error':str(error),
            'git_commit':commit, 'strategy_version':trial.strategy_version, 'metrics':trial.metrics}


def train():
    source, results = load_source(), []
    for variant in prior.VARIANTS:
        for bp in prior.COSTS:
            with session_scope() as session:
                result = run_variant(session, source, variant, bp)
            write_once(ARCHIVE / f'train-{variant}-{bp}.json', result)
            results.append(result)
            print(json.dumps({k:result[k] for k in ('trial_id','variant','cost_bp','status')}), flush=True)
    eligible = [r for r in results if r['status'] == 'complete' and r['cost_bp'] == 10 and r['metrics']['complete_execution']
                and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r:(D(r['metrics']['net_usd']), -prior.VARIANTS.index(r['variant']))) if eligible else None
    selection = {'selected': selected['variant'] if selected else None,
        'strategy_version': selected['strategy_version'] if selected else None,
        'trial_id': selected['trial_id'] if selected else None,
        'source_receipt':source['receipt']['receipt_sha256'], 'dependencies':dependencies()}
    digest = write_once(ARCHIVE / 'selection.json', selection)
    print(json.dumps({'selection':selection, 'sha256':digest}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE / 'selection.json').read_bytes()
    choice = json.loads(raw)
    doc = subprocess.check_output(['git','show',commit+':'+str(RESULTS.relative_to(ROOT))],cwd=ROOT).decode()
    if prior.sha(raw) not in doc or RESULTS.read_text() != doc:
        raise ValueError('commit training selection receipt in results before final')
    if choice['dependencies'] != dependencies() or choice['source_receipt'] != source['receipt']['receipt_sha256']:
        raise ValueError('selection inputs changed')
    with session_scope() as session:
        trial = session.get(Trial, choice['trial_id'])
        if (trial.status != 'complete' or trial.final_holdout or
                trial.strategy_version != choice['strategy_version'] or
                D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
            raise ValueError('invalid selected training case')
        result = run_variant(session, source, choice['selected'], 10, final=True,
            expected_version=choice['strategy_version'])
    write_once(ARCHIVE / 'final.json', result)
    print(json.dumps({k:result[k] for k in ('trial_id','variant','cost_bp','status')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare','train','final'])
    globals()[parser.parse_args().phase]()
