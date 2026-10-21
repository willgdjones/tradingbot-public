"""C09 dated auction recovery in adjusted units with one frozen final."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from datetime import UTC, date, datetime
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
from tradingbot.research.c09_capture import ARCHIVE as TREASURY_ARCHIVE
from tradingbot.research.c09_sources import treasury_audit
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityResearchLedger
from tradingbot.research.total_return_data import ROOT, sha
from tradingbot.research.turn_of_month import finish_metrics, vars_trip
from tradingbot.strategy.c09_auction import AuctionRecovery

ARCHIVE = ROOT/'data/research/c09-total-return'
PLAN = ROOT/'docs/research/39-c09-plan.md'
START,END,ZERO = shared.START,shared.END,D(0)
VARIANTS,COSTS = ('5','10'),(5,10)
IEF_SOURCE = 'db272e7f824287049850fa3e8112d9494677240a983ddb6937b9d2b27dc9f29a'
TREASURY_RECEIPT = '424afceba2fcb886b748b2de438644c61409f368b2686edc4d984aab079c6b36'


def write_once(name,value):
    path=ARCHIVE/name
    raw=(json.dumps(json_value(value),sort_keys=True,indent=2)+'\n').encode()
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=raw: raise ValueError('refuse replacement of C09 artifact')
        if not path.exists(): path.write_bytes(raw)
    return str(path.relative_to(ROOT)),sha(raw)


def freeze_source():
    source_path=ROOT/'data/research/c03-total-return/source.json'
    raw=source_path.read_bytes()
    if sha(raw)!=IEF_SOURCE: raise ValueError('frozen total-return source changed')
    source=json.loads(raw)
    for name,digest in source['inputs'].items():
        if sha((ROOT/name).read_bytes())!=digest: raise ValueError('price/calendar input changed: '+name)
    if not source['crosscheck']['IEF']['passed']: raise ValueError('IEF prices not accepted')
    audit_path=ROOT/'docs/research/29-c09-source-audit.json'
    old=json.loads(audit_path.read_bytes()); receipt=old.pop('receipt_sha256')
    if receipt!=TREASURY_RECEIPT or sha(canonical(old).encode())!=receipt:
        raise ValueError('original Treasury evidence receipt changed')
    treasury=treasury_audit()
    if (treasury!=old['treasury'] or treasury['failures'] or treasury['parsed_events']!=242
            or treasury['review_status']!='DATED_NOTICES_AND_OCCURRENCE_RECONCILED'):
        raise ValueError('Treasury dated event evidence changed')
    records=[r for r in treasury['offering_records'] if r['use']=='candidate_event']
    if len({(r['auction_date'],r['cusip']) for r in records})!=242:
        raise ValueError('duplicate/missing auction identities')
    prices=[{k:r[k] for k in ('date','opens_at','closes_at','conservative_cash_release')} |
            {'quote':r['quotes']['IEF']} for r in source['prices']]
    files=[source_path,audit_path,ROOT/'docs/research/29-c09-special-notice-review.json']
    for folder in TREASURY_ARCHIVE.iterdir():
        if folder.is_dir() and (folder.name.startswith('auction-index-') or folder.name in ('offering','results','special','published-xml')):
            files.extend(p for p in folder.rglob('*') if p.is_file())
    inputs={**source['inputs'],**{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in files}}
    data={'candidate':'C09','prices':prices,'auctions':records,'inputs':inputs,
        'crosscheck':source['crosscheck']['IEF'],'primary':source['primary']['IEF'],
        'secondary':source['secondary']['IEF'],'prior_treasury_receipt':TREASURY_RECEIPT,
        'special_notices':treasury['special_announcements'],'model':'total_return_equivalent; no dividend cash/blackout'}
    summary={}
    for variant in VARIANTS:
        for control in (False,True):
            plans,skips=windows(data,variant,control=control)
            summary[f'{variant}-'+('pre' if control else 'post')]={'windows':len(plans),'source_skips':skips}
    data['window_audit']=summary
    path,digest=write_once('source.json',data)
    print(json.dumps({'source':path,'source_sha256':digest,'sessions':len(prices),'auctions':len(records),
                     'window_counts':{k:v['windows'] for k,v in summary.items()}}))


def load_source():
    raw=(ARCHIVE/'source.json').read_bytes();digest=sha(raw)
    if digest not in PLAN.read_text(): raise ValueError('commit source hash in C09 plan before replay')
    source=json.loads(raw)
    if not source['crosscheck']['passed']: raise ValueError('IEF cross-check is not accepted')
    for name,expected in source['inputs'].items():
        if sha((ROOT/name).read_bytes())!=expected: raise ValueError('C09 source input changed: '+name)
    return {**source,'sha256':digest}


def split_for(source):
    return HoldoutSplit('c09-total-return:'+source['sha256'],START,END)


def windows(source,variant,*,control=False):
    if variant not in VARIANTS: raise ValueError('outside C09 holding variants')
    horizon=int(variant)
    rows=source['prices'];days=[date.fromisoformat(r['date']) for r in rows]
    if days!=sorted(set(days)): raise ValueError('calendar ordering or duplicates')
    post,skips=[],[]
    for auction in sorted(source['auctions'],key=lambda r:(r['auction_date'],r['cusip'])):
        identity=auction['auction_date']+':'+auction['cusip']
        a=date.fromisoformat(auction['auction_date']);decision=bisect_left(days,a)
        entry,exit_=decision+1,decision+1+horizon
        if exit_>=len(days):
            skips.append({'id':identity,'reason':'full-source entry/exit endpoint unavailable'})
            continue
        clock=datetime.strptime(auction['embargo_clock'],'%I:%M %p').time()
        announced=datetime.combine(date.fromisoformat(auction['announcement_date']),clock,tzinfo=NEW_YORK)
        if announced>datetime.fromisoformat(rows[decision]['closes_at']):
            raise ValueError('auction offering not available by decision')
        post.append({'id':identity,'auction_date':str(a),'cusip':auction['cusip'],
            'decision':str(days[decision]),'entry':str(days[entry]),'exit':str(days[exit_]),
            'exit_phase':'open','entry_index':entry,'exit_index':exit_,
            'announcement_at':announced.isoformat(),'hold_sessions':horizon,'diagnostic_preauction':False})
    if not control: return post,skips
    controls=[]
    for window in post:
        entry,exit_=window['entry_index']-horizon,window['entry_index']
        if entry<=0:
            skips.append({'id':window['id'],'reason':'control decision/entry endpoint unavailable'})
            continue
        intersections=[other['id'] for other in post if other['id']!=window['id']
            and max(entry,other['entry_index'])<min(exit_,other['exit_index'])]
        if intersections:
            skips.append({'id':window['id'],'reason':'control intersects another planned post-auction interval',
                          'intersections':intersections})
            continue
        controls.append({**window,'decision':str(days[entry-1]),'entry':str(days[entry]),'exit':str(days[exit_]),
            'entry_index':entry,'exit_index':exit_,'diagnostic_preauction':True})
    return controls,skips


class C09Ledger(EquityResearchLedger):
    def record_fill(self,**kwargs):
        fill=super().record_fill(**kwargs)
        fill.metadata_={**fill.metadata_,'research':{**fill.metadata_['research'],
            'source':'c09_total_return_equivalent','source_sha256':self.runtime.source_hash,
            'auction_id':self.runtime.version_strategy.active_id,'separate_dividend_credit':False,
            'terminal_liquidation':kwargs['order'].reason=='C09 terminal liquidation'}}
        return fill


class C09Backtester(shared.C11Backtester):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.ledger=C09Ledger(self.session,self)


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
    result['benchmarks']={'cash':{'total_return':'0'},'IEF_buy_hold':{
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
    return result


def dependencies():
    return {**shared.dependencies(), **{p: sha((ROOT/'src/tradingbot'/p).read_bytes()) for p in (
        'research/c09_total_return.py', 'strategy/c09_auction.py', 'research/c09_sources.py', 'research/c09_capture.py')}}


def require_committed():
    paths = ['src/tradingbot/'+p for p in dependencies()] + [str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C09 plan and dependencies before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, control=False, final=False, expected_version=None):
    commit = require_committed()
    if variant not in VARIANTS or bp not in COSTS or control and bp != 10 or final and (bp != 10 or control):
        raise ValueError('configuration outside frozen C09 family')
    key = f'c09-tr-{source["sha256"][:12]}-{variant}-{bp}-{int(control)}-' + ('final' if final else 'train')
    prior = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if prior:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C09 final before feed construction',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': prior, 'source_sha256': source['sha256']}))
            session.commit()
        raise ValueError('C09 configuration already attempted; inspect stored evidence')
    CaptureDiskBudget(ROOT/'data').check()
    iid, venue = shared.tr_instrument(session, 'IEF')
    plans, source_skips = windows(source, variant, control=control)
    params = {'instrument_id': iid, 'slot_usd': '140', 'hold_sessions': int(variant),
        'windows': plans, 'source_sha256': source['sha256'], 'diagnostic_preauction': control}
    fx = ReferenceFX(ROOT/'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': bp, 'diagnostic_preauction': control, 'dependencies': dependencies(), 'source_sha256': source['sha256'],
        'fx_source_sha256': fx.source_hash, 'model': 'total_return_equivalent_v1',
        'fee_policy': 'dated 2026-09-17 raw-share equivalent'}
    row = StrategyRow(key=key, name=f'C09 {variant} sessions {bp}bp preauction={control}', venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C09', 'research_family': 'c09', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = AuctionRecovery(params)
        runtime = C09Backtester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed selected version')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C09 dated auction recovery, total-return equivalent, fixed exit, settled cash; preauction diagnostic='+str(control))
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, observed, trips, fills, runtime))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0 and not runtime.halt_events
        by_day = {r['date']: r for r in source['prices']}
        metrics['admitted_windows'] = sum(shared.complete_window(w, by_day, split, final) for w in plans)
        metrics['source_window_skips'] = source_skips
        metrics['gross_after_execution_costs_before_fees'] = str(sum((t.gross_pnl for t in trips), ZERO))
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'c09-total-return-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl, trial.max_drawdown = D(metrics['net_usd']), D(metrics['net_usd'])+runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']; trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'variant': variant, 'cost_bp': bp, 'final_holdout': final, 'diagnostic_preauction': control,
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
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c09-total-return-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C09 failed; any consumed final and partial fills preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total, trial.pnl_after_fees = runtime.max_drawdown, runtime.charged, runtime.realized-runtime.charged
            trial.metrics = json_value({'complete_execution': False, 'partial_replay': True,
                'last_processed_at': runtime.now, 'fees_usd': runtime.charged,
                'ending_marked_equity_usd': runtime.equity(), 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception): raise
        return {'status': 'failed', 'variant': variant, 'cost_bp': bp, 'final_holdout': bool(trial.final_holdout),
            'requested_final': final, 'diagnostic_preauction': control, 'trial_id': trial.id, 'strategy_id': row.id, 'git_commit': commit,
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


def controls():
    source = load_source()
    for variant in VARIANTS:
        with session_scope() as session:
            result = run_variant(session, source, variant, 10, control=True)
        _, digest = write_once(f'control-{variant}-10.json', result)
        print(json.dumps({'trial_id': result['trial_id'], 'variant': variant, 'status': result['status'],
                          'artifact_sha256': digest}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE/'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('selection hash must be in committed plan before final')
    choice = json.loads(raw)
    if (choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies()
            or choice['split'] != split_for(source).metadata() or choice['selected'] not in VARIANTS):
        raise ValueError('invalid or absent frozen C09 winner')
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
    parser.add_argument('phase', choices=('source', 'train', 'controls', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'controls': controls, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
