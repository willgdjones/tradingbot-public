"""C08 owner-authorized adjusted-total-return research revision (d267cf7)."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import json_value, strategy_identity
from tradingbot.data.archive import canonical
from tradingbot.data.free_history import parse_yahoo, YAHOO_CHART
from tradingbot.db.models import Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c08_inventory as prior
from tradingbot.research import c05_total_return as prices
from tradingbot.research.c08_source_audit import load_capture, uso_params
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.turn_of_month import instrument_for, vars_trip
from tradingbot.strategy.c08_inventory import InventoryScarcity

ROOT = prior.ROOT
ARCHIVE = ROOT / 'data/research/c08-total-return'
REVISION = 'total_return_d267cf7'
RESULTS = ROOT / 'docs/research/39-c08-total-return-results.md'
write_once = prices.write_once


def adjusted_source(source, bars):
    """Preserve every dated release/session; only convert the USO price basis."""
    by_day = {str(b.date): b for b in bars}
    if len(by_day) != len(bars) or set(by_day) != {r['date'] for r in source['prices']}:
        raise ValueError('missing, extra or duplicate primary price sessions')
    for row in source['prices']:
        b = by_day[row['date']]
        if any(not v.is_finite() or v <= 0 for v in (b.open, b.close, b.adj_close)):
            raise ValueError('invalid adjusted price')
        row.update(open=str(b.open * b.adj_close / b.close), close=str(b.adj_close),
                   uso_split_continuous_close=str(b.adj_close))
    source['blackouts'] = []
    return source


def prepare():
    source = prior.load_source()
    manifest, raw = load_capture(ROOT / 'data/research/c08/USO', 'USO',
                                 YAHOO_CHART.format(symbol='USO'))
    if manifest['status_code'] != 200 or manifest['params'] != uso_params():
        raise ValueError('primary capture differs from fixed interval/request')
    meta, bars = parse_yahoo(raw.decode())
    if meta['null_rows'] or meta['symbol'] != 'USO' or any(b.dividend for b in bars):
        raise ValueError('primary prices or no-distribution reference basis changed')
    # Require the existing free capture: this replay does not access any account.
    if not (prices.ARCHIVE / 'nasdaq-USO.json').exists():
        raise ValueError('missing captured independent prices')
    reference, secondary = prices.nasdaq('USO')
    secondary = {d: v for d, v in secondary.items() if prior.START.date() <= d < prior.END.date()}
    check = prices.compare_returns({b.date: b.adj_close for b in bars}, secondary)
    check['passed'] = check['passed'] and check['comparisons'] == len(bars) - 1 and not check['yahoo_sessions_outside_reference']
    write_once(ARCHIVE / 'source-check.json', check)
    if not check['passed']:
        raise ValueError('missing or contradictory adjusted prices: source-check.json')
    source = adjusted_source(source, bars)
    source.pop('receipt')
    receipt = {'identity': {'yahoo_sha256': manifest['sha256'], 'nasdaq_sha256': reference['sha256'],
        'data_sha256': prior.sha(canonical(source).encode())}, 'revision': REVISION,
        'split': prior.HoldoutSplit('c08-total-return-d267cf7', prior.START, prior.END).metadata(),
        'crosscheck': check, 'prior_source_receipt': prior.SOURCE_RECEIPT,
        'price_basis': 'Yahoo adjusted total-return virtual units; open times adjusted-close/close',
        'reference_basis': 'Nasdaq split-adjusted close; USO has no cash distributions in this interval'}
    receipt['receipt_sha256'] = prior.sha(canonical(receipt).encode())
    source['receipt'] = receipt
    write_once(ARCHIVE / 'source.json', source)
    print(json.dumps({'receipt': receipt['receipt_sha256'], 'crosscheck': check}), flush=True)


def load_source():
    source = json.loads((ARCHIVE / 'source.json').read_text())
    receipt = dict(source['receipt'])
    digest = receipt.pop('receipt_sha256')
    data = {k: v for k, v in source.items() if k != 'receipt'}
    check = receipt['crosscheck']
    if (prior.sha(canonical(receipt).encode()) != digest or
            prior.sha(canonical(data).encode()) != receipt['identity']['data_sha256'] or
            receipt['revision'] != REVISION or receipt['prior_source_receipt'] != prior.SOURCE_RECEIPT or
            not check['passed'] or D(check['agreement']) < D('.99') or
            check['comparisons'] != len(source['prices']) - 1 or
            check['yahoo_sessions_outside_reference'] or check['missing_inside_overlap'] or
            source['blackouts']):
        raise ValueError('total-return data or comparison changed')
    prior.split_for(source)
    return source


class TotalReturnInventory(InventoryScarcity):
    key = 'sweep_c08_inventory_total_return_v1'


class TotalReturnLedger(prior.C08Ledger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'yahoo_adjusted_total_return_open_scenario',
            'units': 'virtual_total_return_equivalent', 'revision': REVISION}}
        return fill


class TotalReturnBacktester(prior.C08Backtester):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = TotalReturnLedger(self.session, self)


def events(source, params, bp, final, observed):
    scratch = []
    for event in prior.events(source, params, bp, final, scratch):
        converted = replace(event, meta={**event.meta,
            'source': ('spy_cash_dividend_total_return_benchmark' if event.instrument_id == params['spy_benchmark_id']
                       else 'yahoo_adjusted_total_return_scenario'), 'research_revision': REVISION})
        scratch.clear()
        observed.append(converted)
        yield converted


def dependencies():
    extra = ('research/c08_total_return.py', 'research/c05_total_return.py',
             'research/c08_source_audit.py', 'data/free_history.py')
    return {**prior.dependencies(), **{p: prior.sha((ROOT / 'src/tradingbot' / p).read_bytes()) for p in extra}}


def require_committed():
    paths = ['src/tradingbot/' + p for p in dependencies()]
    paths += ['docs/research/39-c08-total-return-plan.md']
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C08 plan and implementation before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_threshold(session, source, threshold, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if threshold not in prior.THRESHOLDS or bp not in prior.COSTS or final and bp != 10:
        raise ValueError('case outside preregistration')
    key = f'c08-tr-d267cf7-{threshold}-{bp}-' + ('final' if final else 'train')
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('case already attempted; read stored result')
    uso, venue = instrument_for(session, 'USO')
    spy, _ = instrument_for(session, 'SPY')
    params = prior.strategy_params(source, uso, spy, threshold)
    params.update({'dividends': 'embedded in adjusted prices, no separate cash credit',
        'blackout_reentry': 'disabled', 'research_revision': REVISION,
        'execution': 'adjusted-open total-return equivalent; unchanged long retains units; settled cash'})
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp_per_side': bp, 'dependencies': dependencies(), 'fx_source_sha256': fx.source_hash,
        'source_receipt': source['receipt']['receipt_sha256'], 'research_revision': REVISION,
        'fee_policy': 'EquityFeeBook September 2026 on virtual adjusted units'}
    row = StrategyRow(key=key, name=f'C08 total-return {threshold} {bp}bp', venue_id=venue,
        status='backtest', allocation_usd=D(140), config={'research_only': True, 'candidate': 'C08',
            'research_family': 'c08', 'research_revision': REVISION, 'params': params,
            'previous_final_trial': 3910, 'independent_confirmation': False})
    session.add(row); session.commit()
    runtime, calculated = None, None
    observed = []
    try:
        bot = TotalReturnInventory(params)
        runtime = TotalReturnBacktester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed training choice')
        result = runtime.run(events(source, params, bp, final, observed), split=prior.split_for(source),
            final_holdout=final, version_params=version,
            notes='Owner-authorized d267cf7 total-return equivalent revision; prior final3910 seen, not independent OOS.')
        metrics, trips, fills = prior.finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(prior.diagnostics(bot, source, observed, trips, fills, runtime, final))
        metrics.update({'complete_execution': not metrics['open_positions'] and result.orders_rejected == 0,
            'all_fees_usd': runtime.charged, 'marked_net_usd': runtime.equity() - runtime.initial_cash,
            'research_revision': REVISION, 'promotion_eligible': False,
            'promotion_reason': 'Prior C08 final inspected; repeated historical period is diagnostic',
            'source_price_basis': 'adjusted total-return equivalent; no separate dividends'})
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'c08-total-return-v1'
        trial.metrics = json_value(metrics)
        trial.max_drawdown = runtime.max_drawdown
        p = metrics['luck']['p_value']
        trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status':'complete', 'threshold':threshold, 'cost_bp':bp, 'final_holdout':final,
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
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c08-total-return-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C08 total-return attempt failed; prior fills/final spend preserved: {type(error).__name__}: {error}'
        trial.metrics = json_value({'complete_execution':False, 'partial_replay':bool(observed),
            'last_processed_at':runtime.now if runtime else None, 'promotion_eligible':False,
            'open_positions':runtime.positions if runtime else {},
            'fees_usd':runtime.charged if runtime else None,
            'ending_marked_equity_usd':runtime.equity() if runtime else None,
            'realized_net_usd':runtime.realized-runtime.charged if runtime else None,
            'halt_events':runtime.halt_events if runtime else [],
            'curve':runtime.curve if runtime else [],
            'max_marked_drawdown_usd':runtime.max_drawdown if runtime else None})
        session.commit()
        if not isinstance(error, Exception):
            raise
        return {'status':'failed', 'threshold':threshold, 'cost_bp':bp, 'final_holdout':trial.final_holdout,
            'requested_final':final, 'trial_id':trial.id, 'strategy_id':row.id, 'error':str(error),
            'git_commit':commit, 'strategy_version':trial.strategy_version, 'metrics':trial.metrics}


def train():
    source, results = load_source(), []
    for threshold in prior.THRESHOLDS:
        for bp in prior.COSTS:
            with session_scope() as session:
                result = run_threshold(session, source, threshold, bp)
            write_once(ARCHIVE / f'train-{threshold}-{bp}.json', result)
            results.append(result)
            print(json.dumps({k:result[k] for k in ('trial_id','threshold','cost_bp','status')}), flush=True)
    eligible = [r for r in results if r['status'] == 'complete' and r['cost_bp'] == 10 and r['metrics']['complete_execution']
                and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r:(D(r['metrics']['net_usd']), -prior.THRESHOLDS.index(r['threshold']))) if eligible else None
    selection = {'selected': selected['threshold'] if selected else None,
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
        if (trial is None or trial.status != 'complete' or trial.final_holdout or
                trial.strategy_version != choice['strategy_version'] or
                D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
            raise ValueError('invalid selected training case')
        result = run_threshold(session, source, choice['selected'], 10, final=True,
            expected_version=choice['strategy_version'])
    write_once(ARCHIVE / 'final.json', result)
    print(json.dumps({k:result[k] for k in ('trial_id','threshold','cost_bp','status')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare','train','final'])
    globals()[parser.parse_args().phase]()
