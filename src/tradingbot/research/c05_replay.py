"""Source-bound C05 replay, durable trials, and one frozen final attempt."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import CashMovement, MarketSession, NEW_YORK, cash_balance
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Fill, Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c05_blackout import ARCHIVE, END, ROOT, START, sha
from tradingbot.research.c06_month_end import drawdown, monthly_luck
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityBacktester, EquityContext, EquityResearchLedger, ObservedStrategy
from tradingbot.research.turn_of_month import instrument_for, scenario_quote, vars_trip
from tradingbot.strategy.c05_commodity_trend import CommodityTrend
from tradingbot.strategy.interface import MarketEvent
from tradingbot.ledger.accounting import FillEvent, iter_round_trips

SOURCE_RECEIPT = '05774a5a2f1ccbfef2898471f32311874e67298fc2bbbb6efb39b1cda893cb7c'
VARIANTS = ('total_return_252_positive', 'total_return_126_positive', 'above_sma_200')
SYMBOLS = ('GLD', 'SLV', 'USO', 'UNG', 'DBA')
COSTS = (5, 10)
ZERO = D(0)


def load_source():
    path = ARCHIVE / 'frozen-source-v1'
    manifest = json.loads((path / 'manifest.json').read_text())
    digest = manifest.pop('receipt_sha256')
    if SOURCE_RECEIPT == 'PENDING_SOURCE_ADMISSION' or digest != SOURCE_RECEIPT or sha(canonical(manifest).encode()) != digest:
        raise ValueError('C05 source admission is absent or changed')
    if manifest['status'] != 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES':
        raise ValueError('C05 source audit is not admitted')
    raw = (path / 'data.json').read_bytes()
    if sha(raw) != manifest['identity']['data_sha256']:
        raise ValueError('C05 frozen data checksum mismatch')
    for name, expected in manifest['source_code_sha256'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('C05 source-audit dependency changed')
    manifest['receipt_sha256'] = digest
    return {**json.loads(raw), 'receipt': manifest}


def dependencies():
    paths = ['research/c05_replay.py', 'strategy/c05_commodity_trend.py', 'research/c05_blackout.py',
             'research/c06_month_end.py', 'research/equity_runtime.py', 'research/equity_fees.py',
             'research/equity_data.py', 'research/turn_of_month.py', 'backtest/engine.py',
             'backtest/holdout.py', 'backtest/fills.py', 'ledger/ledger.py', 'risk/engine.py',
             'risk/limits.py', 'connectors/cash.py', 'strategy/interface.py', 'ledger/accounting.py']
    return {name: sha((ROOT / 'src/tradingbot' / name).read_bytes()) for name in paths}


def split_for(source):
    declared = source['receipt']['split']
    split = HoldoutSplit(declared['dataset_key'], START, END)
    if split.metadata() != declared:
        raise ValueError('C05 source split differs from fixed preregistration')
    return split


def execution_sessions(source):
    return {date.fromisoformat(r['date']): MarketSession(date.fromisoformat(r['date']),
        datetime.fromisoformat(r['conservative_cash_release']).astimezone(NEW_YORK).date(),
        datetime.fromisoformat(r['opens_at']), datetime.fromisoformat(r['closes_at'])) for r in source['prices']}


class C05Context(EquityContext):
    def marked_equity(self):
        return self.runtime.equity()


class C05ObservedStrategy(ObservedStrategy):
    def on_start(self, ctx):
        self.delegate.on_start(C05Context(ctx, self.runtime))

    def on_event(self, ctx, event):
        self.runtime.observe(event)
        return self.delegate.on_event(C05Context(ctx, self.runtime), event)

    def on_finish(self, ctx):
        self.delegate.on_finish(C05Context(ctx, self.runtime))


class C05Ledger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        row = self.runtime.source_sessions[fill.fill_ts.astimezone(NEW_YORK).date().isoformat()]
        reason = kwargs['order'].reason
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'c05_actual_share_yahoo_open_reference_scenario',
            'source_receipt': self.runtime.source_receipt,
            'settlement_date': row['completed_settlement'], 'scheduled_t1': row['scheduled_t1'],
            'conservative_cash_release': row['conservative_cash_release'], 'cash_is_counterfactual': True,
            'terminal_liquidation': reason == 'C05 terminal liquidation',
            'forced_blackout_exit': reason == 'C05 forced blackout exit',
            'blackout_reentry': reason == 'C05 blackout reentry'}}
        return fill


class C05Backtester(EquityBacktester):
    def __init__(self, session, *, strategy, strategy_id, source, fx):
        self.source_sessions = {r['date']: r for r in source['prices']}
        self.source_receipt = source['receipt']['receipt_sha256']
        self.source_distributions = source['distributions']
        self.dividend_entitlements, self.daily_exposure = [], []
        self.income_days = set()
        self.instrument_ids = strategy.params['instrument_ids']
        super().__init__(session, strategy=strategy, strategy_id=strategy_id,
                         sessions=execution_sessions(source), fx=fx)
        self.strategy = C05ObservedStrategy(strategy, self)
        self.ledger = C05Ledger(session, self)

    def observe(self, event):
        day = event.time.astimezone(NEW_YORK).date().isoformat()
        if day not in self.income_days:
            self.income_days.add(day)
            for distribution in self.source_distributions:
                if distribution['ex_date'] != day:
                    continue
                iid = self.instrument_ids[distribution['symbol']]
                quantity = self.positions.get(iid, (ZERO, ZERO))[0]
                if not quantity:
                    continue
                credit = quantity * D(distribution['amount'])
                # CashMovement's credit side is also used for non-trade income.
                # No order or fill is fabricated for a dividend.
                self.cash[0].append(CashMovement('sell', credit, ZERO,
                    date.fromisoformat(distribution['cash_available_session'])))
                self.realized += credit
                self.dividend_entitlements.append({**distribution, 'quantity_before_ex_open': str(quantity),
                    'cash_amount': str(credit), 'recognized_at': event.time.isoformat(),
                    'execution_fill': False, 'source_receipt': self.source_receipt})
        marks = event.meta.get('batch_marks') or {}
        if marks and set(map(int, marks)) != set(self.instrument_ids.values()):
            raise ValueError('incomplete simultaneous marks')
        # A single timestamp's simultaneous marks must not trigger transient
        # risk kills merely because the five ETFs are delivered in list order.
        for iid, price in marks.items():
            value = D(price)
            if not value.is_finite() or value <= 0:
                raise ValueError('invalid simultaneous mark')
            self.marks[int(iid)], self.observed[int(iid)] = value, event.time
        super().observe(event)
        if event.meta.get('phase') == 'close' and event.meta.get('batch_last'):
            value = sum((q * self.marks[i] for i, (q, _) in self.positions.items()), ZERO)
            self.daily_exposure.append({'date': day, 'owned_value_usd': str(value),
                'marked_equity_usd': str(self.equity()), 'fraction': str(value / self.equity())})

    def run(self, events, **kwargs):
        def admitted_events():
            # The shared engine creates/claims the trial before first iteration.
            # Commit training too, so an interruption cannot erase an attempt.
            trial = self.session.get(Trial, self.last_trial_id)
            if trial is None or trial.status != 'running':
                raise ValueError('C05 feed requires a running admitted trial')
            self.session.commit()
            yield from events
        return super().run(admitted_events(), **kwargs)


def strategy_params(source, ids, spy, variant):
    if variant not in VARIANTS or set(ids) != set(SYMBOLS):
        raise ValueError('outside fixed C05 universe/variants')
    rows = source['prices']
    next_session = {a['date']: b['date'] for a, b in zip(rows, rows[1:])}
    months = {row['date'][:7]: row['date'] for row in rows}
    return {'instrument_ids': ids, 'symbols': list(SYMBOLS), 'spy_benchmark_id': spy,
        'variant': variant, 'sleeve_weight': '.19', 'cash_reserve_weight': '.05',
        'slot_usd': '140', 'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001',
        'blackouts': source['blackouts'], 'month_ends': list(months.values()), 'next_session': next_session,
        'source_receipt': source['receipt']['receipt_sha256'],
        'signal': 'month-end adjusted-close own return 252/126 or above SMA200; equality cash',
        'targets': 'monthly completed-close frozen dollars; five fixed 19% sleeves; cash reserve 5%; no inactive redistribution',
        'execution': 'simultaneous current opens observed; all reductions before pro-rata buys; settled cash only',
        'cash': 'conservative first regular open after documented current-T+1 settlement completion',
        'dividends': 'prior-owned ex-open receivable; spendable first regular open strictly after issuer pay date',
        'blackout_reentry': 'latest monthly signal; preceding-close current equity; only affected sleeve resized',
        'partition': 'flat start, in-partition warm-up, final eligible open liquidation without new entry'}


def events(source, params, bp, final, observed):
    """Construct observations lazily, only after durable trial admission."""
    if bp not in COSTS:
        raise ValueError('cost outside fixed C05 cases')
    split = split_for(source)
    opens = [r['opens_at'] for r in source['prices']
             if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final)]
    if not opens:
        raise ValueError('no execution sessions in partition')
    terminal = max(opens, key=datetime.fromisoformat)
    for row in source['prices']:
        opened, closed = (datetime.fromisoformat(row[k]) for k in ('opens_at', 'closes_at'))
        if split.contains(opened, final_holdout=final):
            marks = {str(params['instrument_ids'][s]): row['quotes'][s]['open'] for s in SYMBOLS}
            for phase in ('observe_open', 'reduce', 'buy'):
                for index, symbol in enumerate(SYMBOLS):
                    event = scenario_quote(params['instrument_ids'][symbol], opened, D(row['quotes'][symbol]['open']), bp,
                        phase=phase, symbol=symbol, reference_open=row['quotes'][symbol]['open'],
                        terminal_open=row['opens_at'] == terminal, batch_last=index == len(SYMBOLS)-1,
                        batch_marks=marks if index == 0 and phase == 'observe_open' else None,
                        source='frozen_c05_actual_share_open_reference')
                    observed.append(event)
                    yield event
        if split.contains(closed, final_holdout=final):
            event = MarketEvent.quote(params['spy_benchmark_id'], closed, mid=D(row['spy_close']),
                meta={'phase': 'close', 'mark_only': True, 'symbol': 'SPY', 'distribution': row['spy_distribution']})
            observed.append(event)
            yield event
            marks = {str(params['instrument_ids'][s]): row['quotes'][s]['close'] for s in SYMBOLS}
            for index, symbol in enumerate(SYMBOLS):
                quote = row['quotes'][symbol]
                event = MarketEvent.quote(params['instrument_ids'][symbol], closed, mid=D(quote['close']),
                    meta={'phase': 'close', 'mark_only': True, 'symbol': symbol,
                          'adjusted_close': quote['adjusted_close'], 'batch_last': index == len(SYMBOLS)-1,
                          'batch_marks': marks if index == 0 else None})
                observed.append(event)
                yield event


def marked_period(curve, first, exclusive_last):
    previous, values = D(140), []
    for stamp, value in curve:
        day = stamp.astimezone(NEW_YORK).date().isoformat()
        if first <= day < exclusive_last:
            if not values:
                values.append(previous)
            values.append(value)
        previous = value
    return {'covered': bool(values), 'marked_net_usd': str(values[-1] - values[0]) if values else None,
            'marked_drawdown': drawdown(values) if values else None}


def finish_metrics(session, result, runtime):
    """Reconcile immutable execution ledger plus separately recorded dividend cash."""
    fills = list(session.scalars(select(Fill).where(Fill.trial_id == result.trial_id).order_by(Fill.fill_ts, Fill.id)))
    grouped = {}
    for fill in fills:
        grouped.setdefault(fill.instrument_id, []).append(FillEvent(fill.side, fill.price, fill.size, fill.fee, fill.fill_ts))
    trips = sorted([t for rows in grouped.values() for t in iter_round_trips(rows)], key=lambda t: t.exit_ts)
    open_positions = {str(i): {'quantity': str(q), 'average_price': str(a), 'mark': str(runtime.marks[i])}
                      for i, (q, a) in runtime.positions.items() if q}
    execution_net = D(result.report['pnl_after_fees'])
    entitled = sum((D(r['cash_amount']) for r in runtime.dividend_entitlements), ZERO)
    total_net = execution_net + entitled
    cash = cash_balance(runtime.initial_cash, runtime.cash[0], ZERO, runtime.now)
    value = sum((q * runtime.marks[i] for i, (q, _) in runtime.positions.items()), ZERO)
    unrealized = sum((q * (runtime.marks[i] - avg) for i, (q, avg) in runtime.positions.items()), ZERO)
    tolerance = D('.000001') * max(1, len(fills))
    if abs(cash.settled + cash.unsettled + value - runtime.initial_cash - total_net - unrealized) > tolerance:
        raise ValueError('C05 cash/receivable/positions/execution ledger reconciliation failed')
    if abs(runtime.equity() - runtime.initial_cash - total_net - unrealized) > tolerance:
        raise ValueError('C05 marked equity differs from ledger plus distributions')
    if not open_positions and abs(sum((t.net_pnl for t in trips), ZERO) - execution_net) > tolerance:
        raise ValueError('C05 completed execution trips disagree with ledger')
    metrics = {'net_usd': total_net, 'execution_ledger_net_usd': execution_net,
        'dividend_income_usd': entitled, 'dividend_entitlements': runtime.dividend_entitlements,
        'fees_usd': sum((f.fee for f in fills), ZERO), 'fills': len(fills), 'trades': len(trips),
        'rejected_orders': result.orders_rejected, 'open_positions': open_positions,
        'ending_settled_cash_usd': cash.settled, 'ending_unsettled_cash_and_receivables_usd': cash.unsettled,
        'ending_marked_equity_usd': runtime.equity(), 'unrealized_pnl_usd': unrealized,
        'net_return_on_virtual_cash': total_net / runtime.initial_cash,
        'halt_events': runtime.halt_events, 'holdout': result.report['holdout'],
        'cash_reconciliation_tolerance_usd': tolerance}
    return metrics, trips, fills


def diagnostics(bot, source, observed, trips, fills, runtime, final):
    split, curve = split_for(source), runtime.curve
    month_ends = {}
    for stamp, value in curve:
        month_ends[stamp.astimezone(NEW_YORK).strftime('%Y-%m')] = value
    previous, monthly = D(140), {}
    for month, equity in sorted(month_ends.items()):
        monthly[month], previous = equity - previous, equity
    def regime(first, last):
        completed = [t for t in trips if first <= t.exit_ts.astimezone(NEW_YORK).date().isoformat() < last]
        executed = [f for f in fills if first <= f.fill_ts.astimezone(NEW_YORK).date().isoformat() < last]
        return {**marked_period(curve, first, last), 'execution_round_trips_by_exit': len(completed),
            'execution_net_usd_by_exit': str(sum((t.net_pnl for t in completed), ZERO)), 'fills': len(executed),
            'fees_usd_by_fill_date': str(sum((f.fee for f in executed), ZERO)),
            'turnover_usd': str(sum((f.price * f.size for f in executed), ZERO))}
    calendar_regimes = {name: regime(lo+'-01-01', hi+'-01-01') for name, lo, hi in (
        ('2008-2009', '2008', '2010'), ('2010-2019', '2010', '2020'), ('2020-2021', '2020', '2022'),
        ('2022', '2022', '2023'), ('2023-2026', '2023', '2027'))}
    # The C08 primary prospectus audit dates USO's broader holdings change to Apr27 2020.
    uso_regimes = {name: regime(lo, hi) for name, lo, hi in (
        ('before_2020', '2008-01-01', '2020-01-01'), ('2020_dislocation_before_transition', '2020-01-01', '2020-04-27'),
        ('transition_remainder_2020', '2020-04-27', '2021-01-01'), ('post_2020', '2021-01-01', '2026-10-01'))}
    values = {'SPY': [], 'equal_weight_universe': []}
    first, latest, spy_previous, spy_factor = {}, {}, None, D(1)
    for event in observed:
        if event.meta.get('phase') != 'close':
            continue
        symbol = event.meta['symbol']
        if symbol == 'SPY':
            if spy_previous is not None:
                spy_factor *= (event.mid + D(event.meta['distribution'])) / spy_previous
            spy_previous = event.mid
            values['SPY'].append(D(140) * spy_factor)
        else:
            value = D(event.meta['adjusted_close'])
            first.setdefault(symbol, value)
            latest[symbol] = value
            if event.meta.get('batch_last'):
                values['equal_weight_universe'].append(D(140) * sum((latest[s]/first[s] for s in SYMBOLS), ZERO) / 5)
    benchmarks = {name: {'total_return': str(v[-1]/140-1) if v else None,
        'max_drawdown': drawdown(v), 'not_executable': True,
        'basis': 'same partition completed closes, reinvested distributions, no costs, full hypothetical exposure'}
        for name, v in values.items()}
    benchmarks['cash'] = {'total_return': '0', 'not_executable': True}
    def leg_cost(rows):
        return {'fills': len(rows), 'fees_usd': str(sum((f.fee for f in rows), ZERO)),
            'adverse_reference_cost_usd': str(sum((abs(f.price-D(f.metadata_['research']['execution']['reference_open']))*f.size
                                                 for f in rows), ZERO))}
    blackout_dates = [{'symbol': p['symbol'], 'date': row['date']} for p in source['blackouts'] for row in source['prices']
        if p['exit'] <= row['date'] < p['reentry'] and split.contains(datetime.fromisoformat(row['opens_at']), final_holdout=final)]
    close_times = {e.time for e in observed if e.meta.get('phase') == 'close'}
    close_equity = {t: value for t, value in curve if t in close_times}
    # Count exit months, not simultaneous legs, for the evidence sufficiency guard.
    independent_exit_months = len({t.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m') for t in trips})
    luck = monthly_luck(monthly, independent_exit_months)
    luck['exit_month_clusters'] = independent_exit_months
    return {'monthly_decisions': bot.decisions, 'skips': bot.skips,
        'cash_delay_skips': [s for s in bot.skips if 'cash' in s['reason']],
        'monthly_marked_net_usd': json_value(monthly), 'luck': luck,
        'calendar_regimes': calendar_regimes, 'uso_transition_calendar_regimes_whole_strategy': uso_regimes,
        'marked_calendar_years': {str(year): regime(f'{year}-01-01', f'{year+1}-01-01')
            for year in sorted({t.astimezone(NEW_YORK).year for t, _ in curve})},
        'max_marked_drawdown': drawdown([D(140)] + [v for _, v in curve]),
        'max_daily_close_drawdown': drawdown([D(140)] + list(close_equity.values())),
        'turnover_usd': str(sum((f.price*f.size for f in fills), ZERO)),
        'execution_gross_usd': str(sum((t.gross_pnl for t in trips), ZERO)),
        'terminal_liquidation_fills': sum(f.metadata_['research']['terminal_liquidation'] for f in fills),
        'daily_exposure': runtime.daily_exposure,
        'average_exposure': str(sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO)/len(runtime.daily_exposure))
            if runtime.daily_exposure else None,
        'blackout': {'symbol_sessions': blackout_dates, 'count': len(blackout_dates),
            'forced_exit_cost': leg_cost([f for f in fills if f.metadata_['research']['forced_blackout_exit']]),
            'reentry_cost': leg_cost([f for f in fills if f.metadata_['research']['blackout_reentry']])},
        'benchmarks': benchmarks, 'promotion_eligible': False,
        'promotion_reason': 'Amendment21 source/cash/execution counterfactual and prior USO inspection; separate confirmation required'}


def require_committed():
    paths = ['src/tradingbot/' + name for name in dependencies()]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C05 dependencies before real strategy outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if final:
        consumed = session.scalar(select(Trial).join(StrategyRow, Trial.strategy_id == StrategyRow.id).where(
            Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C05-amendment21').order_by(Trial.id))
        if consumed is not None:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused C05 family final reuse despite source/run/version identity changes',
                details={'kind': 'holdout_reuse', 'first_trial_id': consumed.id,
                         'candidate': 'C05-amendment21', 'requested_source_receipt': SOURCE_RECEIPT}))
            session.commit()
            raise ValueError('C05 Amendment21 family final already consumed; read stored evidence')
    key = f'c05-a21-{source["receipt"]["identity"]["data_sha256"][:12]}-{variant}-{bp}-' + ('final' if final else 'train')
    prior = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if prior:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C05 final invocation before feed construction',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': prior, 'source_receipt': SOURCE_RECEIPT}))
            session.commit()
        raise ValueError('C05 configuration already attempted; read stored results, never replay')
    if variant not in VARIANTS or bp not in COSTS or final and bp != 10:
        raise ValueError('C05 configuration outside frozen variant/cost family')
    CaptureDiskBudget(ROOT / 'data').check()
    instruments = {symbol: instrument_for(session, symbol) for symbol in SYMBOLS}
    ids = {symbol: pair[0] for symbol, pair in instruments.items()}
    venue = instruments['GLD'][1]
    spy, _ = instrument_for(session, 'SPY')
    params = strategy_params(source, ids, spy, variant)
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp_per_side': bp, 'dependencies': dependencies(),
               'fx_source_sha256': fx.source_hash, 'source_receipt': source['receipt']['receipt_sha256'],
               'fee_policy': 'EquityFeeBook 2026-09-17 current-account counterfactual'}
    row = StrategyRow(key=key, name=f'C05 commodity trend {variant} / {bp}bp ' + ('final' if final else 'training'),
        venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C05-amendment21', 'params': params})
    session.add(row); session.commit()
    sid, split = row.id, split_for(source)
    runtime = None
    calculated = None
    try:
        bot = CommodityTrend(params)
        runtime = C05Backtester(session, strategy=bot, strategy_id=sid, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and (not expected_version or calculated != expected_version):
            raise ValueError('C05 final version differs from frozen choice before feed construction')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C05 fixed five-sleeve monthly trend/Amendment21; primary-corrected opens, payable dividends, conservative T+1 cash.')
        metrics, trips, fills = finish_metrics(session, result, runtime)
        metrics.update(diagnostics(bot, source, observed, trips, fills, runtime, final))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'c05-amendment21-v1'
        trial.metrics = json_value(metrics)
        trial.pnl_after_fees = D(metrics['net_usd'])
        trial.pnl = D(metrics['net_usd']) + runtime.charged
        trial.max_drawdown = runtime.max_drawdown
        p = metrics['luck']['p_value']
        trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'variant': variant, 'cost_bp': bp, 'final_holdout': final,
            'trial_id': trial.id, 'strategy_id': sid, 'git_commit': commit, 'version_params': version,
            'strategy_version': trial.strategy_version, 'metrics': json_value(metrics),
            'trades': json_value([vars_trip(t) for t in trips]), 'curve': json_value(runtime.curve),
            'fill_ids': [f.id for f in fills]}
    except BaseException as error:
        if not session.is_active:
            session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=sid, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=split.data_start, data_end=split.data_end,
                strategy_version=calculated, params={'strategy': params, 'version_params': version,
                    'requested_final': final, 'final_feed_consumed': False, '_holdout': split.metadata()})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c05-amendment21-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C05 attempt failed; existing fills and consumed final preserved: {type(error).__name__}: {error}'
        if runtime is not None:
            trial.max_drawdown = runtime.max_drawdown
            trial.fees_total = runtime.charged
            trial.pnl_after_fees = runtime.realized - runtime.charged
            trial.metrics = json_value({'complete_execution': False, 'partial_replay': True,
                'last_processed_at': runtime.now, 'fees_usd': runtime.charged,
                'realized_net_usd': runtime.realized - runtime.charged,
                'ending_marked_equity_usd': runtime.equity(), 'max_marked_drawdown_usd': runtime.max_drawdown,
                'open_positions': runtime.positions, 'halt_events': runtime.halt_events,
                'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception):
            raise
        return {'status': 'failed', 'variant': variant, 'cost_bp': bp, 'final_holdout': bool(trial.final_holdout),
                'requested_final': final, 'trial_id': trial.id, 'strategy_id': sid,
                'git_commit': commit, 'error': str(error), 'strategy_version': trial.strategy_version,
                'metrics': trial.metrics}


def immutable_artifact(name, body):
    raw = (json.dumps(json_value(body), indent=2, sort_keys=True) + '\n').encode()
    path = ARCHIVE / 'runs' / name
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C05 outcome artifact')
        if not path.exists():
            path.write_bytes(raw)
    return path, sha(raw)


def train():
    source = load_source()
    results = []
    for variant in VARIANTS:
        for bp in COSTS:
            with session_scope() as session:
                result = run_variant(session, source, variant, bp)
            path, digest = immutable_artifact(f'train-{variant}-{bp}.json', result)
            results.append({k: v for k, v in result.items() if k not in {'curve', 'trades', 'fill_ids'}} |
                           {'artifact': str(path.relative_to(ROOT)), 'artifact_sha256': digest})
            print(json.dumps({k: result.get(k) for k in ('variant', 'cost_bp', 'trial_id', 'status', 'error')}), flush=True)
    eligible = [r for r in results if r['status'] == 'complete' and r['cost_bp'] == 10
                and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -VARIANTS.index(r['variant']))) if eligible else None
    choice = {'source_receipt': SOURCE_RECEIPT, 'dependencies': dependencies(), 'split': source['receipt']['split'],
              'training': results, 'selected': selected['variant'] if selected else None,
              'selected_strategy_version': selected['strategy_version'] if selected else None,
              'rule': 'highest positive complete 10bp training net; listed variant order breaks ties',
              'holdout_attempted': False, 'promotion_eligible': False}
    path, digest = immutable_artifact('selection.json', choice)
    (ROOT / 'docs/research/23-c05-selection.json').write_bytes(path.read_bytes())
    print(json.dumps({'selected': choice['selected'], 'selection_sha256': digest, 'final_attempted': False}))


def final():
    source = load_source()
    commit = require_committed()
    name = 'docs/research/23-c05-selection.json'
    committed = subprocess.check_output(['git', 'show', commit + ':' + name], cwd=ROOT)
    if (ROOT / name).read_bytes() != committed:
        raise ValueError('C05 selection must be committed before final')
    choice = json.loads(committed)
    if (choice['source_receipt'] != SOURCE_RECEIPT or choice['dependencies'] != dependencies()
            or choice['split'] != source['receipt']['split'] or choice['selected'] not in VARIANTS):
        raise ValueError('no valid frozen profitable C05 choice')
    chosen = next(r for r in choice['training'] if r['variant'] == choice['selected'] and r['cost_bp'] == 10)
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != choice['selected_strategy_version']
                or trial.metrics != chosen['metrics'] or D(trial.metrics['net_usd']) <= 0
                or not trial.metrics['complete_execution']):
            raise ValueError('C05 frozen choice disagrees with durable training evidence')
        result = run_variant(session, source, choice['selected'], 10, final=True,
                             expected_version=choice['selected_strategy_version'])
    path, digest = immutable_artifact('final.json', result)
    receipt = {k: v for k, v in result.items() if k not in {'curve', 'trades', 'fill_ids'}}
    receipt.update({'artifact': str(path.relative_to(ROOT)), 'artifact_sha256': digest,
                    'selection_sha256': sha(committed), 'promotion': 'none'})
    (ROOT / 'docs/research/23-c05-final.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'trial_id': result['trial_id'], 'status': result['status'],
                     'net_usd': result.get('metrics', {}).get('net_usd'), 'promotion': 'none'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('train', 'final'))
    args = parser.parse_args()
    train() if args.phase == 'train' else final()


if __name__ == '__main__':
    main()
