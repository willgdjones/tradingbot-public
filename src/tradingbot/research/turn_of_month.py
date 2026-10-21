"""Run all preregistered SPY calendar variants into the local trials ledger."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import NEW_YORK, cash_balance
from tradingbot.data.alpaca_history import monthly_cycles
from tradingbot.data.loader import local_engine
from tradingbot.data.disk_budget import DiskBudget
from tradingbot.data.bulk_history import write_json
from tradingbot.db.models import Fill, Instrument, Market, Strategy, Trial, Venue
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import luck_probability
from tradingbot.strategy.interface import MarketEvent
from tradingbot.strategy.turn_of_month import TurnOfMonth
from .equity_data import ReferenceFX, load_equities
from .equity_runtime import EquityBacktester, equity_split

VARIANTS = [('tom_minute_2bp', 2, False, False), ('tom_minute_5bp', 5, False, False),
            ('tom_minute_10bp', 10, False, False), ('tom_close_2bp', 2, True, False),
            ('tom_midmonth_close_2bp', 2, True, True)]
ZERO = D(0)


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


def cycles_for(data, start, through, midmonth=False):
    rows = [{'date': day.isoformat()} for day in sorted(data.sessions) if day >= start]
    pairs = [(date.fromisoformat(a['date']), date.fromisoformat(b['date']))
             for a, b in monthly_cycles(rows, through)]
    if midmonth:
        months = {a.strftime('%Y-%m') for a, _ in pairs}
        groups = defaultdict(list)
        for day in sorted(data.sessions):
            if day.strftime('%Y-%m') in months:
                groups[day.strftime('%Y-%m')].append(day)
        pairs = [(days[3], days[9]) for days in groups.values()]
    return pairs


def validate_windows(data, symbol, pairs, close_only):
    raw, adjusted = data.daily(symbol), data.daily(symbol, 'all')
    days = sorted(d for d in data.sessions if pairs[0][0] <= d <= pairs[-1][1])
    missing = [d.isoformat() for d in days if d not in raw or d not in adjusted]
    if missing:
        raise ValueError(f'missing daily sessions: {missing}')
    for entry, exit in pairs:
        held = [d for d in days if entry <= d <= exit]
        if not held or held[0] != entry or held[-1] != exit:
            raise ValueError('missing holding-window endpoint')
        # Alpaca adjusted closes are cent-rounded: a single adjustment factor
        # must lie in every day's rounding interval throughout the holding.
        lower = max((adjusted[d].close - D('.005')) / raw[d].close for d in held)
        upper = min((adjusted[d].close + D('.005')) / raw[d].close for d in held)
        if lower > upper:
            raise ValueError(f'corporate-action factor changes during {entry}..{exit}')
        for action in data.actions:
            ex = action.get('ex_date')
            if action.get('symbol') == symbol and ex and entry < date.fromisoformat(ex) <= exit:
                raise ValueError(f'corporate action in holding window: {entry}..{exit}')
        if not close_only:
            for day in (entry, exit):
                data.minute(symbol, data.sessions[day].closes_at - timedelta(minutes=1))
    return {'daily_sessions': len(days), 'missing_daily_sessions': len(missing),
            'complete_cycles': len(pairs), 'corporate_action_windows_detected': 0,
            'action_reference_rows': len(data.actions), 'action_reference_coverage': 'partial; also checked factor rounding bands'}


def instrument_for(session, symbol):
    venue = session.scalar(select(Venue).where(Venue.key == 'alpaca'))
    if venue is None:
        raise ValueError('Alpaca venue must already exist')
    external = 'research:sip:' + symbol
    instrument = session.scalar(select(Instrument).where(Instrument.venue_id == venue.id, Instrument.external_id == external))
    if instrument is None:
        market = session.scalar(select(Market).where(Market.venue_id == venue.id, Market.external_id == symbol))
        if market is None:
            market = Market(venue_id=venue.id, external_id=symbol, title=symbol, market_type='equity')
            session.add(market); session.flush()
        instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=external,
                                symbol=symbol, instrument_type='equity', currency='USD',
                                contract_multiplier=D(1), metadata_={'research_only': True, 'not_broker_asset_id': True})
        session.add(instrument); session.flush()
    return instrument.id, venue.id


def scenario_quote(iid, ts, reference, bp, **meta):
    slip = D(bp) / 10000
    return MarketEvent.quote(iid, ts, mid=reference,
                             bid=(reference * (1 - slip)).quantize(D('.00000001')),
                             ask=(reference * (1 + slip)).quantize(D('.00000001')),
                             meta={'assumed_execution': True, 'slippage_bp_per_side': bp, **meta})


def tom_events(data, iid, pairs, bp, close_only):
    actions = {d: side for entry, exit in pairs for d, side in [(entry, 'buy'), (exit, 'sell')]}
    daily = data.daily('SPY')
    events = []
    for day in sorted(data.sessions):
        if not pairs[0][0] <= day <= pairs[-1][1]:
            continue
        close = data.sessions[day].closes_at
        if day in actions:
            ts = close if close_only else close - timedelta(minutes=1)
            bar = daily[day] if close_only else data.minute('SPY', ts)
            reference = bar.close if close_only else bar.open
            events.append(scenario_quote(iid, ts, reference, bp, bar_time=bar.time.isoformat(),
                                         bar_field='daily_close' if close_only else 'final_minute_open'))
        if not close_only or day not in actions:
            events.append(MarketEvent.quote(iid, close, mid=daily[day].close, meta={'mark_only': True}))
    return events, actions


def summarize(trips):
    values = [t.net_pnl for t in trips]
    total = sum(values, ZERO)
    return {'trades': len(trips), 'net_usd': total, 'fees_usd': sum((t.fees for t in trips), ZERO),
            'mean_net_usd': total / len(trips) if trips else None,
            'win_rate': D(sum(x > 0 for x in values)) / len(trips) if trips else None,
            'one_sided_t_pvalue': luck_probability(values)}


def exit_date_regimes(trips):
    """Exit-attributed summaries with explicit bounds, not marked-period P&L.

    The open-ended names deliberately make no claim about the dataset's first
    or last year. Old stored metrics are immutable and retain their old keys.
    """
    dated = [(t, t.exit_ts.astimezone(NEW_YORK).date()) for t in trips]
    periods = {}
    for name, start, end in (
        ('before_2023', None, date(2023, 1, 1)),
        ('from_2023', date(2023, 1, 1), None),
        ('2023_2024', date(2023, 1, 1), date(2025, 1, 1)),
        ('from_2025', date(2025, 1, 1), None),
    ):
        selected = [(trip, day) for trip, day in dated
                    if (start is None or day >= start) and (end is None or day < end)]
        days = [day for _, day in selected]
        periods[name] = {
            **summarize([trip for trip, _ in selected]),
            'start_inclusive': start.isoformat() if start else None,
            'end_exclusive': end.isoformat() if end else None,
            'first_exit_date': min(days).isoformat() if days else None,
            'last_exit_date': max(days).isoformat() if days else None,
        }
    return {'basis': 'completed round trips attributed to exit date',
            'timezone': str(NEW_YORK), 'periods': periods}


def entry_regimes(data, trips):
    """Descriptive trend state from closes strictly earlier than each entry."""
    adjusted = data.daily('SPY', 'all')
    grouped = defaultdict(list)
    for trip in trips:
        day = trip.entry_ts.astimezone(NEW_YORK).date()
        earlier = sorted(d for d in adjusted if d < day)[-200:]
        if len(earlier) < 200:
            regime = 'fewer_than_200_prior_sessions'
        else:
            mean = sum((adjusted[d].close for d in earlier), ZERO) / 200
            regime = 'above_prior_200_session_mean' if adjusted[earlier[-1]].close >= mean else 'below_prior_200_session_mean'
        grouped[regime].append(trip)
    return {name:summarize(values) for name,values in sorted(grouped.items())}


def research_dependencies():
    # These modules construct observations/costs outside the reactor itself.
    return {name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('turn_of_month.py', 'equity_data.py', 'equity_fees.py')}


def finish_metrics(session, result, runtime, *, expected_trips=None, allow_rejections=False, require_flat=True):
    fills = list(session.scalars(select(Fill).where(Fill.trial_id == result.trial_id).order_by(Fill.fill_ts, Fill.id)))
    grouped = defaultdict(list)
    for fill in fills:
        grouped[fill.instrument_id].append(FillEvent(fill.side, fill.price, fill.size, fill.fee, fill.fill_ts))
    trips = sorted([trip for rows in grouped.values() for trip in iter_round_trips(rows)], key=lambda t:t.exit_ts)
    open_positions = {str(iid): {'quantity': str(q), 'average_price': str(avg), 'mark': str(runtime.marks[iid])}
                      for iid, (q, avg) in runtime.positions.items() if q}
    if (result.orders_rejected and not allow_rejections) or (open_positions and require_flat):
        raise ValueError(f'incomplete replay: {result.orders_rejected} rejections or nonflat ending')
    if expected_trips is not None and (len(trips) != expected_trips or len(fills) != expected_trips * 2):
        raise ValueError('execution/trade count differs from fixed calendar')
    net = result.report['pnl_after_fees']
    cash = sum((cash_balance(runtime.initial_cash / runtime.buckets, runtime.cash[b], ZERO, runtime.now).settled
                + cash_balance(runtime.initial_cash / runtime.buckets, runtime.cash[b], ZERO, runtime.now).unsettled
                for b in range(runtime.buckets)), ZERO)
    # Database MONEY precision is 1e-6 per realized close.
    tolerance = D('.000001') * max(1, len(trips))
    position_value = sum((q * runtime.marks[iid] for iid, (q, _) in runtime.positions.items()), ZERO)
    unrealized = sum((q * (runtime.marks[iid] - avg) for iid, (q, avg) in runtime.positions.items()), ZERO)
    if abs(cash + position_value - runtime.initial_cash - net - unrealized) > tolerance:
        raise ValueError('cash/marked equity/ledger reconciliation failed')
    if not open_positions and abs(sum((t.net_pnl for t in trips), ZERO) - net) > tolerance:
        raise ValueError('cash/round-trip/ledger net reconciliation failed')
    yearly = {str(y): summarize([t for t in trips if t.exit_ts.astimezone(NEW_YORK).year == y])
              for y in sorted({t.exit_ts.astimezone(NEW_YORK).year for t in trips})}
    metrics = {**summarize(trips), 'ledger_net_usd': net, 'fills': len(fills), 'rejected_orders': result.orders_rejected,
               'holdout': result.report['holdout'],
               'max_marked_drawdown_usd': runtime.max_drawdown,
               'net_return_on_virtual_cash': net / runtime.initial_cash,
               'ending_cash_including_unsettled': cash, 'year_by_exit': yearly,
               'ending_marked_equity_usd': cash + position_value,
               'unrealized_pnl_usd': unrealized, 'open_positions': open_positions,
               'halt_events': runtime.halt_events,
               'exit_date_regimes': exit_date_regimes(trips),
               'position_hours': sum(((t.exit_ts - t.entry_ts).total_seconds() / 3600 for t in trips), 0),
               'cash_reconciliation_tolerance_usd': tolerance}
    return metrics, trips, fills


def run_variant(session, data, fx, run_id, variant, commit, start, through, *, final_holdout=False,
                entry_notional=D('24.90'), use_available_cash=False):
    name, bp, close_only, midmonth = variant
    key = 'eq_' + hashlib.sha256((run_id + ':' + name).encode()).hexdigest()[:30]
    if session.scalar(select(Strategy.id).where(Strategy.key == key)):
        raise ValueError(f'run already attempted: {run_id}/{name}; choose a new run-id explicitly')
    iid, venue_id = instrument_for(session, 'SPY')
    params = {'variant': name, 'study_run_id': run_id, 'source_sha256': data.source_hash,
              'source_pages': data.source_pages, 'source_records': data.source_records,
              'fx_sha256': fx.source_hash, 'slippage_bp_per_side': bp,
              'fee_policy': 'Alpaca retail 2026-09-17 current-cost counterfactual, daily type ceil cent',
              'execution': 'daily_close_nonexecutable_benchmark' if close_only else 'final_minute_open_scenario',
              'virtual_cash_usd': '140', 'entry_notional_usd': str(entry_notional),
              'use_available_cash': use_available_cash, 'entry_fee_reserve': '.01' if use_available_cash else '0',
              'start': str(start), 'through': str(through)}
    row = Strategy(key=key, name=name + ' ' + run_id, venue_id=venue_id, status='backtest',
                   allocation_usd=D(140), config={'research_only': True, 'parent_strategy': 'turn_of_month', **params})
    session.add(row); session.commit()
    sid = row.id
    try:
        split = equity_split(data, ('SPY',))
        params = {**params, 'holdout': {**split.metadata(), 'final_holdout_requested': final_holdout}}
        all_pairs = cycles_for(data, start, through, midmonth)
        pairs = [(a, b) for a, b in all_pairs
                 if split.contains(data.sessions[a].closes_at - timedelta(seconds=0 if close_only else 60), final_holdout=final_holdout)
                 and split.contains(data.sessions[b].closes_at, final_holdout=final_holdout)]
        if not pairs:
            raise ValueError('no complete calendar cycles in the selected locked partition')
        quality = validate_windows(data, 'SPY', pairs, close_only)
        events, actions = tom_events(data, iid, pairs, bp, close_only)
        # Calendar-derived configuration is frozen across training and holdout.
        actions = {d: side for entry, exit in all_pairs for d, side in [(entry, 'buy'), (exit, 'sell')]}
        strategy_params = {'instrument_id': iid, 'schedule': {str(d): side for d, side in actions.items()},
                           'session_closes': {str(d): data.sessions[d].closes_at.strftime('%H:%M') for d in actions},
                           'seconds_before_close': 0 if close_only else 60, 'entry_notional': str(entry_notional)}
        if use_available_cash:
            strategy_params.update(use_available_cash=True, entry_fee_reserve='.01')
        params = {**params, 'strategy_params': strategy_params, 'quality': quality}
        runtime = EquityBacktester(session, strategy=TurnOfMonth(strategy_params), strategy_id=sid,
                                   sessions=data.sessions, fx=fx)
        result = runtime.run(events, params=params, split=split, final_holdout=final_holdout,
                             version_params={'slippage_bp_per_side': bp, 'close_only': close_only, 'midmonth': midmonth,
                                             'research_dependencies': research_dependencies()},
                             notes='Research bar scenario; no broker execution; locked chronological partition.')
        metrics, trips, fills = finish_metrics(session, result, runtime, expected_trips=len(pairs))
        metrics.update({'quality': quality, 'first_entry': str(pairs[0][0]), 'last_exit': str(pairs[-1][1]),
                        'entry_trend_regimes': entry_regimes(data, trips),
                        'unfinished_tom_cycle_excluded': '2026-09-25 to 2026-10-05',
                        'exposure_session_intervals': sum(sum(a < d <= b for d in data.sessions) for a,b in pairs)})
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'equity-research-v1'
        trial.metrics = jsonable(metrics)
        trial.win_rate = metrics['win_rate']
        trial.max_drawdown = runtime.max_drawdown
        session.commit()
        artifact = {'variant': name, 'trial_id': trial.id, 'strategy_id': sid, 'git_commit': commit,
                    'params': params, 'metrics': metrics, 'trades': [vars_trip(t) for t in trips],
                    'equity_curve': runtime.curve, 'fill_ids': [f.id for f in fills]}
        return artifact
    except Exception as error:
        session.rollback()
        consumed_id = getattr(locals().get('runtime'), 'last_trial_id', None) if final_holdout else None
        trial = session.get(Trial, consumed_id) if consumed_id is not None else None
        if trial is None:
            trial = Trial(strategy_id=sid, mode='backtest', params=jsonable(params),
                          holdout_start=split.holdout_start if 'split' in locals() else None)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'equity-research-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'{type(error).__name__}: {error}; failed run rolled back, audit retained'
        session.add(trial); session.commit()
        return {'variant': name, 'trial_id': trial.id, 'error': str(error), 'status': 'failed'}


def vars_trip(t):
    return {'entry': t.entry_ts, 'exit': t.exit_ts, 'gross_usd': t.gross_pnl, 'fees_usd': t.fees, 'net_usd': t.net_pnl}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('data/equities'))
    parser.add_argument('--data-run', default='tom-20260930')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--fx', type=Path, default=Path('data/equities/fx/ecb-20260930.xml'))
    parser.add_argument('--start', type=date.fromisoformat, default=date(2016,1,1))
    parser.add_argument('--through', type=date.fromisoformat, default=date(2026,9,30))
    parser.add_argument('--variant', choices=[v[0] for v in VARIANTS])
    parser.add_argument('--final-holdout', action='store_true')
    parser.add_argument('--entry-notional', type=D, default=D('24.90'))
    parser.add_argument('--use-available-cash', action='store_true')
    args = parser.parse_args()
    if args.final_holdout and not args.variant:
        parser.error('--final-holdout requires one frozen --variant, not a parameter sweep')
    if not args.entry_notional.is_finite() or not 1 <= args.entry_notional <= 140:
        parser.error('--entry-notional must be $1..$140 within the virtual slot')
    # Code provenance must be committed before performance evaluation.
    dirty = subprocess.check_output(['git','status','--porcelain','--','src/tradingbot/research',
                                     'src/tradingbot/strategy/turn_of_month.py','src/tradingbot/strategy/interface.py',
                                     'src/tradingbot/backtest/engine.py','src/tradingbot/backtest/fills.py',
                                     'src/tradingbot/backtest/holdout.py',
                                     'src/tradingbot/ledger','src/tradingbot/risk','src/tradingbot/db',
                                     'src/tradingbot/connectors/cash.py','src/tradingbot/data/alpaca_history.py'],text=True)
    if dirty:
        raise ValueError('commit research code before running ledger trials')
    commit = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    data, fx = load_equities(args.root,args.data_run), ReferenceFX(args.fx)
    output = args.root / 'results' / args.run_id
    budget = DiskBudget(Path('data'))
    budget.check()
    with Session(local_engine(),expire_on_commit=False) as session:
        for variant in (v for v in VARIANTS if args.variant is None or v[0] == args.variant):
            budget.check()
            artifact = run_variant(session,data,fx,args.run_id,variant,commit,args.start,args.through,
                                   final_holdout=args.final_holdout, entry_notional=args.entry_notional,
                                   use_available_cash=args.use_available_cash)
            write_json(output / (variant[0]+'.json'), jsonable(artifact), budget)
            print(json.dumps({k:v for k,v in artifact.items() if k in {'variant','trial_id','metrics','error','status'}},default=str),flush=True)


if __name__ == '__main__':
    main()
