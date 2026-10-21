"""Fixed 2023–2026 SPY/QQQ afternoon studies, recorded in the trials ledger."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import NEW_YORK, cash_balance
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Order, Strategy, Trial
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import luck_probability
from tradingbot.strategy.eod_letf import EodLetf
from tradingbot.strategy.interface import MarketEvent
from .equity_data import ReferenceFX, load_equities
from .equity_runtime import EquityBacktester, equity_split
from .turn_of_month import finish_metrics, instrument_for, jsonable, scenario_quote, summarize, vars_trip

VARIANTS = [('letf_1pct_2bp', '.01', 2, False), ('letf_05pct_2bp', '.005', 2, False),
            ('letf_15pct_2bp', '.015', 2, False), ('letf_1pct_5bp', '.01', 5, False),
            ('letf_1pct_10bp', '.01', 10, False), ('letf_1pct_close_2bp', '.01', 2, True)]
SYMBOLS = ('SPY', 'QQQ')
ZERO = D(0)


def study_days(data, start, through):
    if start < date(2023,1,1) or through > date(2026,12,31) or start > through:
        raise ValueError('LETF backtests are restricted to 2023–2026')
    days = sorted(d for d in data.sessions if start <= d <= through)
    if len(days) < 2:
        raise ValueError('insufficient calendar')
    return days


def is_full_session(data, day):
    return data.sessions[day].closes_at > datetime.combine(day,time(15,30),NEW_YORK)


def validate_data(data, days):
    minute_count = 0
    for symbol in SYMBOLS:
        raw, adjusted = data.daily(symbol), data.daily(symbol,'all')
        previous_factor = None
        for day in days:
            if day not in raw or day not in adjusted:
                raise ValueError(f'missing daily bar: {symbol}/{day}')
            factor = adjusted[day].close / raw[day].close
            if previous_factor is not None and abs(factor / previous_factor - 1) > D('.02'):
                raise ValueError(f'large adjustment discontinuity needs handling: {symbol}/{day}')
            previous_factor = factor
            if not is_full_session(data,day):
                continue
            ts = datetime.combine(day,time(15,30),NEW_YORK)
            while ts < data.sessions[day].closes_at:
                data.minute(symbol,ts)
                minute_count += 1
                ts += timedelta(minutes=1)
    other_actions = [a for a in data.actions if a.get('symbol') in SYMBOLS
                     and a['kind'] != 'cash_dividends']
    if other_actions:
        raise ValueError('non-cash corporate action requires explicit handling')
    halfdays = [str(d) for d in days if not is_full_session(data,d)]
    return {'trading_sessions':len(days),'full_sessions':len(days)-len(halfdays),
            'early_closes_skipped':halfdays,'first_session_warmup_only':str(days[0]),
            'signal_sessions':sum(is_full_session(data,d) for d in days[1:]),
            'required_minute_bars':minute_count,'missing_required_bars':0,
            'cash_dividend_reference_rows':len(data.actions),
            'corporate_action_reference_coverage':'vendor snapshot; no complete point-in-time coverage claim',
            'large_adjustment_discontinuities':0}


def letf_events(data, ids, days, bp, close_only):
    events=[]
    for symbol,iid in ids.items():
        daily=data.daily(symbol)
        for day in days:
            close=data.sessions[day].closes_at
            if is_full_session(data,day):
                entry=datetime.combine(day,time(15,30),NEW_YORK)
                ts=entry
                while ts<close:
                    bar=data.minute(symbol,ts)
                    meta={'symbol':symbol,'bar_time':bar.time.isoformat(),'bar_field':'minute_open'}
                    if ts==entry or (not close_only and ts==close-timedelta(minutes=1)):
                        events.append(scenario_quote(iid,ts,bar.open,bp,**meta))
                    else:
                        events.append(MarketEvent.quote(iid,ts,mid=bar.open,meta={'mark_only':True,**meta}))
                    ts+=timedelta(minutes=1)
            meta={'symbol':symbol,'bar_time':daily[day].time.isoformat(),'bar_field':'daily_close'}
            if close_only and is_full_session(data,day):
                events.append(scenario_quote(iid,close,daily[day].close,bp,**meta))
            else:
                events.append(MarketEvent.quote(iid,close,mid=daily[day].close,meta={'mark_only':True,**meta}))
    return sorted(events,key=lambda event:(event.time,event.instrument_id))


def letf_metrics(session,result,runtime,strategy,ids,data):
    metrics,trips,fills=finish_metrics(session,result,runtime,allow_rejections=True,require_flat=False)
    if metrics['open_positions'] and not runtime.killed:
        raise ValueError('unexpected open position without recorded strategy kill')
    by_day=defaultdict(lambda:ZERO)
    for trip in trips:
        by_day[str(trip.exit_ts.astimezone(NEW_YORK).date())]+=trip.net_pnl
    per_symbol={}
    for symbol,iid in ids.items():
        rows=[FillEvent(f.side,f.price,f.size,f.fee,f.fill_ts) for f in fills if f.instrument_id==iid]
        decisions=[d for d in strategy.decisions if d['instrument_id']==iid]
        per_symbol[symbol]={**summarize(iter_round_trips(rows)), 'signal_counts':dict(Counter(d['signal'] for d in decisions))}
    rejected=list(session.scalars(select(Order).where(Order.trial_id==result.trial_id,Order.status=='rejected')))
    dividend_days={(a.get('symbol'),a.get('ex_date')) for a in data.actions if a['kind']=='cash_dividends'}
    symbols_by_id={iid:symbol for symbol,iid in ids.items()}
    metrics.update({'per_symbol':per_symbol,'day_aggregated_one_sided_t_pvalue':luck_probability(list(by_day.values())),
                    'active_exit_days':len(by_day),'daily_closed_net_usd':dict(by_day),
                    'signal_counts':dict(Counter(d['signal'] for d in strategy.decisions)),
                    'signals_on_reported_ex_dividend_dates':sum((symbols_by_id[d['instrument_id']],d['date']) in dividend_days
                                                               and d['signal']=='long' for d in strategy.decisions),
                    'rejections_by_reason':dict(Counter(o.reason for o in rejected)),
                    'cash_buckets_last_event':{str(b):{
                        'settled':str(balance.settled),'unsettled':str(balance.unsettled),'available':str(balance.available)}
                        for b in range(runtime.buckets)
                        for balance in [cash_balance(runtime.initial_cash/runtime.buckets,runtime.cash[b],ZERO,runtime.now)]},
                    'execution_order':'SPY then QQQ for equal-time observations; fee attribution follows this order'})
    # Every fill must use the trading-session-index half, including exits.
    for fill in fills:
        day=fill.fill_ts.astimezone(NEW_YORK).date()
        if fill.metadata_['research']['cash_bucket']!=runtime.bucket_by_day[day]:
            raise ValueError('fill used the wrong alternating capital half')
    return metrics,trips,fills


def run_variant(session,data,fx,run_id,variant,commit,start,through,*,final_holdout=False):
    name,threshold,bp,close_only=variant
    key='eq_'+hashlib.sha256((run_id+':'+name).encode()).hexdigest()[:30]
    if session.scalar(select(Strategy.id).where(Strategy.key==key)):
        raise ValueError(f'run already attempted: {run_id}/{name}; choose an explicit new run-id')
    ids={}
    for symbol in SYMBOLS:
        ids[symbol],venue_id=instrument_for(session,symbol)
    params={'variant':name,'study_run_id':run_id,'threshold':threshold,'slippage_bp_per_side':bp,
            'symbols':list(SYMBOLS),'side':'long_only_cash_account','start':str(start),'through':str(through),
            'source_sha256':data.source_hash,'source_pages':data.source_pages,'source_records':data.source_records,
            'fx_sha256':fx.source_hash,'virtual_cash_usd':'140','cash_buckets':2,'entry_notional_usd':'24.90',
            'signal':'raw 15:30 minute open / previous daily close - 1',
            'exit':'daily_close_nonexecutable_benchmark' if close_only else 'final_minute_open_scenario',
            'fee_policy':'Alpaca retail 2026-09-17 current-cost counterfactual; account/day/type ceil cent'}
    row=Strategy(key=key,name=name+' '+run_id,venue_id=venue_id,status='backtest',allocation_usd=D(140),
                 config={'research_only':True,'parent_strategy':'letf_eod',**params})
    session.add(row);session.commit();sid=row.id
    try:
        split=equity_split(data,SYMBOLS)
        params={**params,'holdout':{**split.metadata(),'final_holdout_requested':final_holdout}}
        all_days=study_days(data,start,through)
        days=[d for d in all_days if split.contains(data.sessions[d].opens_at,final_holdout=final_holdout)
              and split.contains(data.sessions[d].closes_at,final_holdout=final_holdout)]
        if len(days)<2:raise ValueError('insufficient complete sessions in locked partition')
        quality=validate_data(data,days)
        strategy_params={'instrument_ids':list(ids.values()),'threshold':threshold,'entry_notional':'24.90',
                         'session_closes':{str(d):data.sessions[d].closes_at.strftime('%H:%M') for d in all_days},
                         'previous_session':{str(b):str(a) for a,b in zip(all_days,all_days[1:])},
                         'seconds_before_close':0 if close_only else 60}
        params={**params,'quality':quality,'strategy_params':strategy_params}
        strategy=EodLetf(strategy_params)
        runtime=EquityBacktester(session,strategy=strategy,strategy_id=sid,sessions=data.sessions,fx=fx,
                                buckets=2,bucket_by_day={d:i%2 for i,d in enumerate(all_days)})
        result=runtime.run(letf_events(data,ids,days,bp,close_only),params=params,
                           split=split,final_holdout=final_holdout,
                           version_params={'slippage_bp_per_side':bp,'close_only':close_only},
                           notes='PRD #5 cash-account subset; six preregistered scenarios; no actual broker execution')
        metrics,trips,fills=letf_metrics(session,result,runtime,strategy,ids,data)
        metrics['quality']=quality
        trial=session.get(Trial,result.trial_id)
        trial.git_commit,trial.code_version=commit,'equity-research-v2'
        trial.metrics=jsonable(metrics)
        trial.win_rate=metrics['win_rate'];trial.max_drawdown=runtime.max_drawdown
        session.commit()
        return {'variant':name,'trial_id':trial.id,'strategy_id':sid,'git_commit':commit,'params':params,
                'metrics':metrics,'trades':[vars_trip(t) for t in trips], 'decisions':strategy.decisions,
                'equity_curve':runtime.curve,'fill_ids':[f.id for f in fills]}
    except Exception as error:
        session.rollback()
        consumed_id=getattr(locals().get('runtime'),'last_trial_id',None) if final_holdout else None
        trial=session.get(Trial,consumed_id) if consumed_id is not None else None
        if trial is None:
            trial=Trial(strategy_id=sid,mode='backtest',params=jsonable(params),
                        holdout_start=split.holdout_start if 'split' in locals() else None)
        trial.status,trial.git_commit,trial.code_version='failed',commit,'equity-research-v2'
        trial.completed_ts=datetime.now(UTC)
        trial.notes=f'{type(error).__name__}: {error}; execution rolled back; failed audit retained'
        session.add(trial);session.commit()
        return {'variant':name,'trial_id':trial.id,'error':str(error),'status':'failed'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('data/equities'))
    parser.add_argument('--data-run',default='letf-20260930')
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--fx',type=Path,default=Path('data/equities/fx/ecb-20260930.xml'))
    parser.add_argument('--start',type=date.fromisoformat,default=date(2023,1,1))
    parser.add_argument('--through',type=date.fromisoformat,default=date(2026,9,30))
    parser.add_argument('--variant',choices=[v[0] for v in VARIANTS])
    parser.add_argument('--final-holdout',action='store_true')
    args=parser.parse_args()
    if args.final_holdout and not args.variant:
        parser.error('--final-holdout requires one frozen --variant, not a parameter sweep')
    dirty=subprocess.check_output(['git','status','--porcelain','--','src/tradingbot/research',
                                  'src/tradingbot/strategy/eod_letf.py','src/tradingbot/strategy/interface.py',
                                  'src/tradingbot/backtest/engine.py','src/tradingbot/backtest/fills.py',
                                  'src/tradingbot/backtest/holdout.py',
                                  'src/tradingbot/ledger','src/tradingbot/risk','src/tradingbot/db',
                                  'src/tradingbot/connectors/cash.py','src/tradingbot/data/alpaca_history.py'],text=True)
    if dirty:raise ValueError('commit research code before ledger trials')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    data,fx=load_equities(args.root,args.data_run),ReferenceFX(args.fx)
    output=args.root/'results'/args.run_id
    output.mkdir(parents=True,exist_ok=True)
    with Session(local_engine(),expire_on_commit=False) as session:
        for variant in (v for v in VARIANTS if args.variant is None or v[0]==args.variant):
            artifact=run_variant(session,data,fx,args.run_id,variant,commit,args.start,args.through,
                                 final_holdout=args.final_holdout)
            (output/(variant[0]+'.json')).write_text(json.dumps(artifact,default=str,indent=2)+'\n')
            print(json.dumps({k:v for k,v in artifact.items() if k in {'variant','trial_id','metrics','error','status'}},default=str),flush=True)


if __name__=='__main__':main()
