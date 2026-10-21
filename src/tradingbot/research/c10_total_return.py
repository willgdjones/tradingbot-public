"""C10 TLT month-end demand in adjusted units with one frozen final."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research import c11_total_return as shared
from tradingbot.research.c10_capture import ARCHIVE as OLD_ARCHIVE, PUBLIC, read
from tradingbot.research.c06_sources import spy_source
from tradingbot.data.free_history import parse_yahoo
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityResearchLedger
from tradingbot.research.total_return_data import (ROOT, sha, positive, alpaca_prices, nasdaq_prices,
    dividend_adjusted_reference, cross_check)
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.c10_month_end import TreasuryMonthEnd

ARCHIVE = ROOT/'data/research/c10-total-return'
PLAN = ROOT/'docs/research/42-c10-total-return-plan.md'
RESULTS = ROOT/'docs/research/42-c10-total-return-results.md'
START,END,ZERO = shared.START,shared.END,D(0)
VARIANTS,COSTS = ('3','5'),(5,10)
YAHOO_SHA = 'afe749c182e8f7dcd1502e7bb51c62e88b9210e3c813618cd5bfa3d176130526'
PRIOR_RECEIPT_SHA = '0edf7ebf456af1e9b3abe44cf7819e7da662616c6026f3382c91b96eb2a294a0'
AUCTION_SOURCE_SHA = '821b7e0c3a948090de55c7f35f588b4f96c0996144742ce9d35286922bf9d57f'
UNEXPECTED_CLOSURES = ('2007-01-02', '2012-10-29', '2012-10-30', '2018-12-05', '2025-01-09')


def write_once(name,value):
    path=ARCHIVE/name
    raw=(json.dumps(json_value(value),sort_keys=True,indent=2)+'\n').encode()
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=raw: raise ValueError('refuse replacement of C10 artifact')
        if not path.exists(): path.write_bytes(raw)
    return str(path.relative_to(ROOT)),sha(raw)


def freeze_source():
    meta, raw = read(OLD_ARCHIVE/'yahoo-tlt', *PUBLIC['yahoo-tlt'])
    if meta['status'] != 200 or sha(raw) != YAHOO_SHA:
        raise ValueError('original TLT source changed')
    info, bars = parse_yahoo(raw.decode())
    if info.get('symbol') != 'TLT' or info['null_rows'] or len({b.date for b in bars}) != len(bars):
        raise ValueError('invalid primary symbol/session coverage')
    quotes = {}
    for bar in bars:
        if not START.date() <= bar.date < END.date():
            raise ValueError('primary price outside registered interval')
        factor = positive(bar.adj_close)/positive(bar.close)
        quotes[bar.date] = {'open': positive(bar.open)*factor, 'close': positive(bar.adj_close),
            'raw_open': positive(bar.open), 'raw_close': positive(bar.close), 'factor': factor}
    calendar_manifest, calendar = spy_source()
    if set(quotes) != {date.fromisoformat(r['date']) for r in calendar['prices']}:
        raise ValueError('missing or extra primary session price')
    prices = [{k: r[k] for k in ('date','opens_at','closes_at','conservative_cash_release')} |
              {'quote': quotes[date.fromisoformat(r['date'])]} for r in calendar['prices']]
    secondary = {}
    captures = {}
    for adjustment in ('all', 'split'):
        candidates = list((ARCHIVE/f'raw/alpaca/bars_1Day_{adjustment}_sip').glob('*/*/manifest.json'))
        if len(candidates) != 1:
            raise ValueError('missing or ambiguous TLT reference capture')
        rows, evidence = alpaca_prices(candidates[0].parent, adjustment=adjustment)
        if set(rows) != {'TLT'} or evidence['request']['params']['symbols'] != 'TLT':
            raise ValueError('reference symbol differs from TLT')
        secondary['alpaca_'+adjustment], captures[adjustment] = evidence, rows['TLT']
    reference, secondary['nasdaq'] = nasdaq_prices('TLT',START.date(),END.date()-timedelta(days=1),archive=ARCHIVE)
    check = cross_check({d:q['close'] for d,q in quotes.items()},
        dividend_adjusted_reference(reference,captures['all'],captures['split']))
    if not check['passed']:
        raise ValueError('missing or contradictory TLT adjusted-price comparison')
    prior_path = ROOT/'docs/research/30-c10-source-audit.json'
    if sha(prior_path.read_bytes()) != PRIOR_RECEIPT_SHA:
        raise ValueError('prior C10 receipt changed')
    auction_path = ROOT/'data/research/c09-total-return/source.json'
    auction_raw = auction_path.read_bytes()
    if sha(auction_raw) != AUCTION_SOURCE_SHA:
        raise ValueError('original C09 calendar source changed')
    auctions = json.loads(auction_raw)['auctions']
    files = [prior_path, auction_path, ROOT/calendar_manifest['data_path'],
        ROOT/'docs/research/13-equity-data-repair-spy-amendment.json']
    for key in ('yahoo-tlt','tlt-issuer','nasdaq-sandy-oct29','nasdaq-sandy-oct30','nasdaq-sandy-reopen'):
        files.extend((OLD_ARCHIVE/key).glob('*'))
    for evidence in secondary.values():
        files.extend(p for p in (ROOT/evidence['path']).glob('*') if p.is_file())
    source = {'candidate':'C10', 'prices':prices, 'inputs':{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in files},
        'primary':{**meta,'path':str((OLD_ARCHIVE/'yahoo-tlt').relative_to(ROOT)),'sessions':len(prices)},
        'secondary':secondary,'crosscheck':check,'prior_source_trial':4584,'prior_receipt_sha256':PRIOR_RECEIPT_SHA,
        'unexpected_closures':list(UNEXPECTED_CLOSURES),'auctions_for_overlap_only':auctions,
        'calendar_model':'validated actual sessions plus restored known unexpected closures; not full advance-notice proof',
        'known_yahoo_event_omission':{'ex_date':'2012-11-01','issuer_amount':'0.269553','record_date':'2012-11-05','payable_date':'2012-11-07','price_or_cash_repair':False},
        'model':'total_return_equivalent; no separate dividend cash or corporate-action blackout'}
    source['window_audit'] = {variant: {'windows':len(windows(source,variant)[0]),'skips':windows(source,variant)[1]}
                              for variant in VARIANTS}
    path,digest = write_once('source.json',source)
    print(json.dumps({'source':path,'source_sha256':digest,'sessions':len(prices),
        'agreement_percent':check['agreement_percent'],'window_counts':{k:v['windows'] for k,v in source['window_audit'].items()}}))


def load_source():
    raw=(ARCHIVE/'source.json').read_bytes();digest=sha(raw)
    if digest not in PLAN.read_text(): raise ValueError('commit source hash in C10 plan before replay')
    source=json.loads(raw)
    if not source['crosscheck']['passed']: raise ValueError('TLT cross-check is not accepted')
    for name,expected in source['inputs'].items():
        if sha((ROOT/name).read_bytes())!=expected: raise ValueError('C10 source input changed: '+name)
    return {**source,'sha256':digest}


def split_for(source):
    return HoldoutSplit('c10-total-return:'+source['sha256'],START,END)


def windows(source, variant):
    if variant not in VARIANTS:
        raise ValueError('outside C10 month-end variants')
    days = [date.fromisoformat(r['date']) for r in source['prices']]
    if not days or days != sorted(set(days)):
        raise ValueError('calendar ordering, duplicates or empty source')
    restored = {date.fromisoformat(d) for d in source.get('unexpected_closures', UNEXPECTED_CLOSURES)
                if days[0] <= date.fromisoformat(d) <= days[-1]}
    if restored.intersection(days):
        raise ValueError('unexpected closure is present as a real price session')
    planned = sorted(set(days) | restored)
    months = {}
    for day in planned:
        months.setdefault(day.strftime('%Y-%m'), []).append(day)
    groups, result, skips = list(months.items()), [], []
    for i, (month, sessions) in enumerate(groups):
        identity = 'month:'+month
        if i+1 == len(groups):
            skips.append({'id':identity,'reason':'next-month source exit unavailable'})
            continue
        if len(sessions) < int(variant):
            skips.append({'id':identity,'reason':'incomplete source entry month'})
            continue
        next_first = sessions[-1].replace(day=1)+timedelta(days=32)
        if groups[i+1][0] != next_first.strftime('%Y-%m'):
            raise ValueError('missing full exchange month')
        planned_entry, planned_exit = sessions[-int(variant)], groups[i+1][1][0]
        entry_index, exit_index = bisect_left(days, planned_entry), bisect_left(days, planned_exit)
        if entry_index == 0 or entry_index >= len(days) or exit_index >= len(days):
            skips.append({'id':identity,'reason':'decision/entry/exit outside source'})
            continue
        if entry_index >= exit_index:
            skips.append({'id':identity,'reason':'entry cannot precede fixed exit'})
            continue
        result.append({'id':identity,'month':month,'decision':str(days[entry_index-1]),
            'planned_entry':str(planned_entry),'planned_exit':str(planned_exit),
            'entry':str(days[entry_index]),'exit':str(days[exit_index]),'exit_phase':'open',
            'entry_sessions_from_month_end':int(variant),
            'closure_entry_delay':days[entry_index]!=planned_entry,'closure_exit_delay':days[exit_index]!=planned_exit})
    return result, skips


class C10Ledger(EquityResearchLedger):
    def record_fill(self,**kwargs):
        fill=super().record_fill(**kwargs)
        fill.metadata_={**fill.metadata_,'research':{**fill.metadata_['research'],
            'source':'c10_total_return_equivalent','source_sha256':self.runtime.source_hash,
            'month_window_id':self.runtime.version_strategy.active_id,'separate_dividend_credit':False,
            'terminal_liquidation':kwargs['order'].reason=='C10 terminal liquidation'}}
        return fill


class C10Backtester(shared.C11Backtester):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.ledger=C10Ledger(self.session,self)
        self.c10_source = kwargs["source"]


def events(source,params,bp,final,observed):
    split=split_for(source);by_day={r['date']:r for r in source['prices']}
    admitted={w['id'] for w in params['windows'] if shared.complete_window(w,by_day,split,final)}
    terminal=max(r['opens_at'] for r in source['prices']
                 if split.contains(datetime.fromisoformat(r['opens_at']),final_holdout=final))
    for row in source['prices']:
        for phase,key in [('open','opens_at'),('close','closes_at')]:
            stamp=datetime.fromisoformat(row[key])
            if split.contains(stamp,final_holdout=final):
                event=shared.scenario(params['instrument_id'],stamp,row['quote'],phase,bp,
                    terminal_open=phase=='open' and row[key]==terminal,
                    admitted_windows=[w['id'] for w in params['windows'] if w['decision']==row['date'] and w['id'] in admitted])
                observed.append(event);yield event


def diagnostics(bot,observed,trips,fills,runtime):
    result=shared.diagnostics(bot,observed,trips,fills,runtime)
    result.pop('weekday_expiry_structure_break')
    closes=[e.mid for e in observed if e.meta['phase']=='close']
    values=[D(140)*p/closes[0] for p in closes] if closes else []
    result['benchmarks']={'cash':{'total_return':'0'},'TLT_buy_hold':{
        'total_return':str(values[-1]/140-1) if values else None,'max_drawdown':shared.drawdown(values),
        'basis':'same-partition adjusted completed closes, no costs, full exposure'}}
    result['turnover_usd']=str(sum((f.price*f.size for f in fills),ZERO))
    result['terminal_liquidation_fills']=sum(f.metadata_['research']['terminal_liquidation'] for f in fills)
    result['cash_delay_skips']=[s for s in bot.skips if 'cash delay' in s['reason']]
    result['overlap_skips']=[s for s in bot.skips if 'overlap' in s['reason']]
    result['late_entries']=[s for s in bot.skips if 'late entry' in s['reason']]
    clusters = len({t.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m') for t in trips})
    result['luck'] = shared.monthly_luck({m: D(v) for m, v in result['monthly_marked_net_usd'].items()}, clusters)
    result['luck']['exit_month_clusters'] = clusters
    result['max_drawdown_fraction_initial_allocation'] = str(D(result['max_marked_drawdown']['dollars'])/140)
    result['closure_delays'] = [w for w in bot.decisions if w['closure_entry_delay'] or w['closure_exit_delay']]
    result['calendar_overlap'] = calendar_overlap(runtime.sessions, trips, runtime.c10_source.get('auctions_for_overlap_only', []))
    result['daily_tlt_beta'] = market_beta(observed, runtime.curve)
    return result


def calendar_overlap(sessions, trips, auctions):
    """Compare completed C10 holds with other planned clocks, never their returns."""
    days = sorted(sessions)
    months = {}
    for day in days:
        months.setdefault(day.strftime('%Y-%m'), []).append(sessions[day])
    groups = list(months.values())
    clocks = {'strategy6': [], 'c06_potential': [], 'c09_five_session': [], 'c09_ten_session': []}
    for left, right in zip(groups, groups[1:]):
        if len(left) >= 4 and len(right) >= 3:
            clocks['strategy6'].append((left[-4].closes_at, right[2].closes_at))
        clocks['c06_potential'].append((left[-1].opens_at, right[0].opens_at))
    for auction in auctions:
        decision = bisect_left(days, date.fromisoformat(auction['auction_date']))
        entry = decision+1
        for horizon, key in ((5, 'c09_five_session'), (10, 'c09_ten_session')):
            if entry+horizon < len(days):
                clocks[key].append((sessions[days[entry]].opens_at, sessions[days[entry+horizon]].opens_at))
    return {'basis':'actual completed C10 holding interval intersects another registered calendar window; C06 ignores its signal filter, C09 ignores actual fills; not return correlation',
        'round_trips':len(trips), **{name:sum(any(max(t.entry_ts,a)<min(t.exit_ts,b) for a,b in windows) for t in trips)
                                   for name,windows in clocks.items()}}


def market_beta(observed, curve):
    """Descriptive daily close-to-close beta against the traded TLT series."""
    equity = dict(curve)
    closes = [(e.mid,equity[e.time]) for e in observed if e.meta['phase']=='close']
    pairs = [(b/a-1, q/p-1) for (a,p),(b,q) in zip(closes,closes[1:]) if p>0]
    result = {'basis':'daily marked strategy returns versus same-partition TLT adjusted close returns, including flat days',
              'observations':len(pairs),'beta':None,'correlation':None}
    if len(pairs)<2:
        return result
    mx, my = (sum((r[i] for r in pairs),ZERO)/len(pairs) for i in (0,1))
    covariance = sum(((x-mx)*(y-my) for x,y in pairs),ZERO)
    variance_x = sum(((x-mx)**2 for x,_ in pairs),ZERO)
    variance_y = sum(((y-my)**2 for _,y in pairs),ZERO)
    if variance_x:
        result['beta'] = str(covariance/variance_x)
    if variance_x and variance_y:
        result['correlation'] = str(covariance/(variance_x*variance_y).sqrt())
    return result


def dependencies():
    return {**shared.dependencies(), **{p: sha((ROOT/'src/tradingbot'/p).read_bytes()) for p in (
        'research/c10_total_return.py', 'strategy/c10_month_end.py', 'research/c10_capture.py', 'data/free_history.py')}}


def require_committed():
    paths = ['src/tradingbot/'+p for p in dependencies()] + [str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C10 plan and dependencies before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if variant not in VARIANTS or bp not in COSTS or final and bp != 10:
        raise ValueError('configuration outside frozen C10 family')
    key = f'c10-tr-{source["sha256"][:12]}-{variant}-{bp}-' + ('final' if final else 'train')
    prior = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if prior:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C10 final before feed construction',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': prior, 'source_sha256': source['sha256']}))
            session.commit()
        raise ValueError('C10 configuration already attempted; inspect stored evidence')
    CaptureDiskBudget(ROOT/'data').check()
    iid, venue = shared.tr_instrument(session, 'TLT')
    plans, source_skips = windows(source, variant)
    params = {'instrument_id': iid, 'slot_usd': '140', 'entry_sessions_from_month_end': int(variant),
        'windows': plans, 'source_sha256': source['sha256']}
    fx = ReferenceFX(ROOT/'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': bp, 'dependencies': dependencies(), 'source_sha256': source['sha256'],
        'fx_source_sha256': fx.source_hash, 'model': 'total_return_equivalent_v1',
        'fee_policy': 'dated 2026-09-17 raw-share equivalent'}
    row = StrategyRow(key=key, name=f'C10 {variant}-last TLT month-end {bp}bp', venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C10', 'research_family': 'c10', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = TreasuryMonthEnd(params)
        runtime = C10Backtester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed selected version')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C10 TLT month-end demand, total-return equivalent, fixed planned dates, settled cash')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, observed, trips, fills, runtime))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0 and not runtime.halt_events
        by_day = {r['date']: r for r in source['prices']}
        metrics['admitted_windows'] = sum(shared.complete_window(w, by_day, split, final) for w in plans)
        metrics['source_window_skips'] = source_skips
        metrics['gross_after_execution_costs_before_fees'] = str(sum((t.gross_pnl for t in trips), ZERO))
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'c10-total-return-v1', json_value(metrics)
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
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c10-total-return-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C10 failed; any consumed final and partial fills preserved: {type(error).__name__}: {error}'
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
    committed = subprocess.check_output(['git', 'show', commit+':'+str(RESULTS.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != RESULTS.read_bytes():
        raise ValueError('selection hash must be in committed results before final')
    choice = json.loads(raw)
    if (choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies()
            or choice['split'] != split_for(source).metadata() or choice['selected'] not in VARIANTS):
        raise ValueError('invalid or absent frozen C10 winner')
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
