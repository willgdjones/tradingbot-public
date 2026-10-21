"""C02 monthly sector-momentum replay: durable trials and one frozen holdout.

Reuses the Amendment 21 source admitted for the nine-ETF universe
(``data/research/c07-blackout/frozen-source-v1``, receipt below, candidate
provenance C07-amendment21 — the same C02-lineage source audit, 12-c02 →
22-c02). The strategy is C02's own monthly momentum reactor; this runtime is a
self-contained sibling of the C06/C07 equity replays (next-open taker execution,
EquityFeeBook costs, conservative T+1 settled cash, ex-date dividends credited on
their documented release, corporate-action blackout, terminal liquidation),
extended to the multi-leg monthly rebalance. Training sweeps three score variants
at 5/10 bp over the first 70%; the sole 10 bp holdout runs once under the shared
durable single-use admission (PRD §4). Promotion needs the checklist and a
separate forward confirmation; nothing here is promotion evidence.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
import random
import subprocess
from types import SimpleNamespace

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import CashMovement, MarketSession, NEW_YORK, cash_balance
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Fill, Incident, Order, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.research.c07_blackout_sources import ARCHIVE, END, ROOT, START, sha
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_runtime import EquityBacktester, EquityContext, EquityResearchLedger, ObservedStrategy
from tradingbot.research.turn_of_month import instrument_for, scenario_quote, vars_trip
from tradingbot.strategy.c02_sector_momentum import SectorMomentum, VARIANTS, total_return_factor
from tradingbot.strategy.interface import MarketEvent

# Admitted source receipt (c07_blackout_sources --freeze). Same nine-ETF
# Amendment 21 data this C02 lineage audited; no strategy outcomes are in it.
SOURCE_RECEIPT = '6c89c1cd4827a63fefffcb0ebe3e00be9dd8bae2631ec1d49632c5dbc4b214e7'
SYMBOLS = ('XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY')
COSTS = (5, 10)
ARCHIVE_C02 = ROOT / 'data/research/c02-momentum'
ZERO = D(0)


def load_source():
    path = ARCHIVE / 'frozen-source-v1'
    manifest = json.loads((path / 'manifest.json').read_text())
    digest = manifest.pop('receipt_sha256')
    if digest != SOURCE_RECEIPT or sha(canonical(manifest).encode()) != digest:
        raise ValueError('C02 source admission is absent or changed')
    if manifest['status'] != 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES':
        raise ValueError('C02 source audit is not admitted')
    raw = (path / 'data.json').read_bytes()
    if sha(raw) != manifest['identity']['data_sha256']:
        raise ValueError('C02 frozen data checksum mismatch')
    for name, expected in manifest['source_code_sha256'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('C02 source-audit dependency changed')
    manifest['receipt_sha256'] = digest
    return {**json.loads(raw), 'receipt': manifest}


def dependencies():
    paths = ['research/c02_sector_momentum.py', 'strategy/c02_sector_momentum.py',
             'research/equity_runtime.py', 'research/equity_fees.py', 'research/equity_data.py',
             'research/action_blackout.py', 'research/turn_of_month.py', 'backtest/engine.py',
             'backtest/holdout.py', 'backtest/fills.py', 'ledger/ledger.py', 'ledger/accounting.py',
             'risk/engine.py', 'risk/limits.py', 'connectors/cash.py', 'strategy/interface.py']
    return {name: sha((ROOT / 'src/tradingbot' / name).read_bytes()) for name in paths}


def split_for(source):
    """The admitted 70/30 window under a C02-family dataset key (family `c02`)."""
    declared = source['receipt']['split']
    split = HoldoutSplit('c02-amendment21-' + source['receipt']['identity']['data_sha256'][:40], START, END)
    expected = {**declared, 'dataset_key': split.dataset_key}
    if split.metadata() != expected:
        raise ValueError('C02 split differs from the admitted source window')
    return split


def execution_sessions(source):
    return {date.fromisoformat(r['date']): MarketSession(date.fromisoformat(r['date']),
        datetime.fromisoformat(r['conservative_cash_release']).astimezone(NEW_YORK).date(),
        datetime.fromisoformat(r['opens_at']), datetime.fromisoformat(r['closes_at'])) for r in source['prices']}


def monthly_cycles(rows):
    """Month-end decision -> {entry: next month's first open, exit: the following}.

    The target decided at a month's last session is executed at the next month's
    first open and held until the month-after's first open (the next rebalance).
    """
    months = {}
    for row in rows:
        day = date.fromisoformat(row['date'])
        months.setdefault((day.year, day.month), []).append(row['date'])
    ordered = [sorted(days) for _, days in sorted(months.items())]
    return {days[-1]: {'entry': ordered[i + 1][0], 'exit': ordered[i + 2][0] if i + 2 < len(ordered) else None}
            for i, days in enumerate(ordered[:-1])}


class C02Context(EquityContext):
    def marked_equity(self):
        return self.runtime.equity()


class C02ObservedStrategy(ObservedStrategy):
    def on_start(self, ctx):
        self.delegate.on_start(C02Context(ctx, self.runtime))

    def on_event(self, ctx, event):
        self.runtime.observe(event)
        return self.delegate.on_event(C02Context(ctx, self.runtime), event)

    def on_finish(self, ctx):
        self.delegate.on_finish(C02Context(ctx, self.runtime))


class C02Ledger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        row = self.runtime.source_sessions[fill.fill_ts.astimezone(NEW_YORK).date().isoformat()]
        reason = kwargs['order'].reason
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'c02_actual_share_yahoo_open_reference_scenario',
            'source_receipt': self.runtime.source_receipt,
            'settlement_date': row['completed_settlement'], 'scheduled_t1': row['scheduled_t1'],
            'conservative_cash_release': row['conservative_cash_release'], 'cash_is_counterfactual': True,
            'terminal_liquidation': reason == 'C02 terminal liquidation',
            'forced_blackout_exit': reason == 'C02 forced blackout exit',
            'blackout_reentry': reason == 'C02 blackout reentry',
            'monthly_rebalance_exit': reason == 'C02 monthly rebalance exit',
            'rebalance_cycle': self.runtime.version_strategy.order_context[fill.metadata_['tag']]}}
        return fill


class C02Backtester(EquityBacktester):
    def __init__(self, session, *, strategy, strategy_id, source, fx):
        self.source_sessions = {r['date']: r for r in source['prices']}
        self.source_receipt = source['receipt']['receipt_sha256']
        self.source_distributions = source['distributions']
        self.dividend_entitlements, self.daily_exposure = [], []
        self.unavailable_income = ZERO
        self.income_days = set()
        self.instrument_ids = strategy.params['instrument_ids']
        super().__init__(session, strategy=strategy, strategy_id=strategy_id,
                         sessions=execution_sessions(source), fx=fx)
        self.strategy = C02ObservedStrategy(strategy, self)
        self.ledger = C02Ledger(session, self)

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
                # CashMovement's credit side also carries non-trade income; no
                # order or fill is fabricated for an ordinary cash dividend.
                if distribution['cash_release'] is None:
                    self.unavailable_income += credit
                else:
                    self.cash[0].append(CashMovement('sell', credit, ZERO,
                        datetime.fromisoformat(distribution['cash_release']).astimezone(NEW_YORK).date()))
                self.realized += credit
                self.dividend_entitlements.append({**distribution, 'quantity_before_ex_open': str(quantity),
                    'cash_amount': str(credit), 'recognized_at': event.time.isoformat(),
                    'execution_fill': False, 'source_receipt': self.source_receipt})
        marks = event.meta.get('batch_marks') or {}
        if marks and set(map(int, marks)) != set(self.instrument_ids.values()):
            raise ValueError('incomplete simultaneous marks')
        # Deliver the nine simultaneous marks at once so sequential list order
        # never trips a transient risk kill mid-batch.
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
            # The shared engine creates/claims the trial before the first event;
            # commit training too so an interruption cannot erase an attempt.
            trial = self.session.get(Trial, self.last_trial_id)
            if trial is None or trial.status != 'running':
                raise ValueError('C02 feed requires a running admitted trial')
            self.session.commit()
            yield from events
        return super().run(admitted_events(), **kwargs)


def strategy_params(source, ids, spy, variant):
    if variant not in VARIANTS or set(ids) != set(SYMBOLS):
        raise ValueError('outside fixed C02 universe/variants')
    return {'instrument_ids': ids, 'symbols': list(SYMBOLS), 'spy_reference_id': spy,
        'variant': variant, 'top_n': 3, 'target_weight': '.95', 'cash_reserve_weight': '.05',
        'slot_usd': '140', 'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001',
        'blackouts': source['blackouts'], 'cycles': monthly_cycles(source['prices']),
        'source_receipt': source['receipt']['receipt_sha256'],
        'signal': 'month-end economic total-return index; variant score (12m | 6m | mean of 1/3/6/9/12m); '
                  'pure top-three rank, equal weight, alphabetical ties',
        'targets': '95% divided by three; blacked-out or missing slots stay cash; targets and 5% reserve '
                   'frozen at decision-close equity; aggregate per-position slot cap',
        'execution': 'Next month first open; reductions (leavers, blackout, terminal) before pro-rata settled-cash '
                     'buys; stayers held across the rebalance, only positive gaps topped up (never trimmed)',
        'cash': 'Conservative first regular open after documented current-T+1 settlement completion',
        'dividends': 'Prior-owned ex-open receivable; cash on first regular open strictly after latest documented payable',
        'blackout': 'Flat across each split/in-kind: force-exit at the exit open, re-enter the frozen target after reentry',
        'partition': 'Flat start, in-partition warm-up (longest lookback + 1 month-ends), terminal open liquidation'}


def events(source, params, bp, final, observed):
    """Lazy observations; the durable final claim must precede the first yield."""
    if bp not in COSTS:
        raise ValueError('cost outside fixed C02 cases')
    split = split_for(source)
    opens = [r['opens_at'] for r in source['prices']
             if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final)]
    if not opens:
        raise ValueError('no execution sessions in partition')
    terminal = max(opens, key=datetime.fromisoformat)
    by_day = {r['date']: r for r in source['prices']}
    for row in source['prices']:
        opened, closed = (datetime.fromisoformat(row[k]) for k in ('opens_at', 'closes_at'))
        if split.contains(opened, final_holdout=final):
            marks = {str(params['instrument_ids'][s]): row['quotes'][s]['open'] for s in SYMBOLS}
            for phase in ('observe_open', 'reduce', 'buy'):
                for index, symbol in enumerate(SYMBOLS):
                    event = scenario_quote(params['instrument_ids'][symbol], opened, D(row['quotes'][symbol]['open']), bp,
                        phase=phase, symbol=symbol, reference_open=row['quotes'][symbol]['open'],
                        terminal_open=row['opens_at'] == terminal, batch_last=index == len(SYMBOLS) - 1,
                        batch_marks=marks if index == 0 and phase == 'observe_open' else None,
                        source='frozen_c02_actual_share_open_reference')
                    observed.append(event)
                    yield event
        if split.contains(closed, final_holdout=final):
            event = MarketEvent.quote(params['spy_reference_id'], closed, mid=D(row['spy_close']),
                meta={'phase': 'close', 'mark_only': True, 'symbol': 'SPY', 'distribution': row['spy_distribution']})
            observed.append(event)
            yield event
            marks = {str(params['instrument_ids'][s]): row['quotes'][s]['close'] for s in SYMBOLS}
            cycle = params['cycles'].get(row['date'])
            entry_admitted = bool(cycle and split.contains(
                datetime.fromisoformat(by_day[cycle['entry']]['opens_at']), final_holdout=final))
            for index, symbol in enumerate(SYMBOLS):
                quote = row['quotes'][symbol]
                event = MarketEvent.quote(params['instrument_ids'][symbol], closed, mid=D(quote['close']),
                    meta={'phase': 'close', 'mark_only': True, 'symbol': symbol,
                          'distribution': quote['signal_distribution'], 'split_ratio': quote['split_ratio'],
                          'in_kind_signal_value': quote['in_kind_signal_value'],
                          'batch_last': index == len(SYMBOLS) - 1, 'entry_admitted': entry_admitted,
                          'batch_marks': marks if index == 0 else None})
                observed.append(event)
                yield event


# --- metrics ------------------------------------------------------------------
def drawdown(values):
    peak = maximum = fraction = ZERO
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, peak - value)
        if peak:
            fraction = max(fraction, (peak - value) / peak)
    return {'dollars': str(maximum), 'fraction': str(fraction)}


def monthly_luck(monthly, round_trips):
    """Fixed 3-month circular-block, centered-null bootstrap; descriptive only."""
    values = [float(v) for v in monthly.values()]
    if len(values) < 30 or round_trips < 30 or not any(values):
        return {'p_value': None, 'reason': 'fewer than 30 completed trips/months or zero variation',
                'round_trips': round_trips}
    n = len(values)
    mean = sum(values) / n
    centered = [x - mean for x in values]
    rng, exceed = random.Random(2022026), 0
    for _ in range(10000):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(centered[(start + j) % n] for j in range(3))
        exceed += sum(sample[:n]) / n >= mean
    return {'p_value': (exceed + 1) / 10001, 'method': 'one-sided centered circular block bootstrap',
        'block_months': 3, 'draws': 10000, 'seed': 2022026, 'months': n, 'round_trips': round_trips,
        'descriptive_only': True, 'selection_adjusted': False}


def marked_period(curve, low, high):
    previous, selected = D(140), []
    for stamp, value in curve:
        if low <= stamp.astimezone(NEW_YORK).year <= high:
            if not selected:
                selected.append(previous)
            selected.append(value)
        previous = value
    return {'covered': bool(selected), 'marked_net_usd': str(selected[-1] - selected[0]) if selected else None,
            'marked_drawdown': drawdown(selected) if selected else None}


def finish_metrics(session, result, runtime):
    """Reconcile the immutable execution ledger plus separately recorded dividends."""
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
    if abs(cash.settled + cash.unsettled + runtime.unavailable_income + value - runtime.initial_cash - total_net - unrealized) > tolerance:
        raise ValueError('C02 cash/receivable/positions/execution ledger reconciliation failed')
    if abs(runtime.equity() - runtime.initial_cash - total_net - unrealized) > tolerance:
        raise ValueError('C02 marked equity differs from ledger plus distributions')
    if not open_positions and abs(sum((t.net_pnl for t in trips), ZERO) - execution_net) > tolerance:
        raise ValueError('C02 completed execution trips disagree with ledger')
    metrics = {'net_usd': total_net, 'execution_ledger_net_usd': execution_net,
        'dividend_income_usd': entitled, 'dividend_entitlements': runtime.dividend_entitlements,
        'fees_usd': sum((f.fee for f in fills), ZERO), 'fills': len(fills), 'trades': len(trips),
        'rejected_orders': result.orders_rejected, 'open_positions': open_positions,
        'ending_settled_cash_usd': cash.settled, 'ending_unsettled_cash_and_receivables_usd': cash.unsettled + runtime.unavailable_income,
        'income_without_in_sample_availability_usd': runtime.unavailable_income,
        'ending_marked_equity_usd': runtime.equity(), 'unrealized_pnl_usd': unrealized,
        'net_return_on_virtual_cash': total_net / runtime.initial_cash,
        'halt_events': runtime.halt_events, 'holdout': result.report['holdout'],
        'cash_reconciliation_tolerance_usd': tolerance}
    return metrics, trips, fills


def diagnostics(bot, source, observed, trips, fills, runtime, final):
    split, curve = split_for(source), runtime.curve
    monthly = {t.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m'): ZERO for t in trips}
    for t in trips:
        monthly[t.exit_ts.astimezone(NEW_YORK).strftime('%Y-%m')] += t.net_pnl

    def regime(lo, hi):
        completed = [t for t in trips if lo <= t.exit_ts.astimezone(NEW_YORK).year <= hi]
        executed = [f for f in fills if lo <= f.fill_ts.astimezone(NEW_YORK).year <= hi]
        return {**marked_period(curve, lo, hi), 'execution_round_trips_by_exit': len(completed),
            'execution_net_usd_by_exit': str(sum((t.net_pnl for t in completed), ZERO)), 'fills': len(executed),
            'fees_usd_by_fill_date': str(sum((f.fee for f in executed), ZERO)),
            'turnover_usd': str(sum((f.price * f.size for f in executed), ZERO))}
    calendar_regimes = {name: regime(lo, hi) for name, lo, hi in (
        ('2006-2009', 2006, 2009), ('2010-2019', 2010, 2019), ('2020-2021', 2020, 2021),
        ('2022', 2022, 2022), ('2023-2026', 2023, 2026))}

    values = {'SPY': [], 'equal_weight_universe': []}
    previous_prices, factors = {}, {s: D(1) for s in (*SYMBOLS, 'SPY')}
    for event in observed:
        if event.meta.get('phase') != 'close':
            continue
        symbol = event.meta['symbol']
        if symbol in previous_prices:
            factors[symbol] *= total_return_factor(previous_prices[symbol], event.mid,
                D(event.meta.get('distribution', '0')), D(event.meta.get('split_ratio', '1')),
                D(event.meta.get('in_kind_signal_value', '0')))
        previous_prices[symbol] = event.mid
        if symbol == 'SPY':
            values['SPY'].append(D(140) * factors[symbol])
        elif event.meta.get('batch_last'):
            values['equal_weight_universe'].append(D(140) * sum((factors[s] for s in SYMBOLS), ZERO) / len(SYMBOLS))
    benchmarks = {name: {'total_return': str(v[-1] / 140 - 1) if v else None, 'max_drawdown': drawdown(v),
        'not_executable': True, 'basis': 'same partition completed closes, reinvested economic distributions, '
        'no costs, full hypothetical exposure'} for name, v in values.items()}
    benchmarks['cash'] = {'total_return': '0', 'not_executable': True}

    def leg_cost(rows):
        return {'fills': len(rows), 'fees_usd': str(sum((f.fee for f in rows), ZERO)),
            'adverse_reference_cost_usd': str(sum((abs(f.price - D(f.metadata_['research']['execution']['reference_open'])) * f.size
                                                 for f in rows), ZERO))}
    blackout_dates = [{'symbol': p['symbol'], 'date': row['date']} for p in source['blackouts'] for row in source['prices']
        if p['exit'] <= row['date'] < p['reentry'] and split.contains(datetime.fromisoformat(row['opens_at']), final_holdout=final)]
    close_times = {e.time for e in observed if e.meta.get('phase') == 'close'}
    close_equity = {t: value for t, value in curve if t in close_times}
    return {'monthly_decisions': bot.decisions, 'skips': bot.skips,
        'cash_delay_skips': [s for s in bot.skips if 'cash' in s['reason']],
        'monthly_marked_net_usd': json_value(monthly), 'luck': monthly_luck(monthly, len(trips)),
        'calendar_regimes': calendar_regimes,
        'marked_calendar_years': {str(year): regime(year, year)
            for year in sorted({t.astimezone(NEW_YORK).year for t, _ in curve})},
        'max_marked_drawdown': drawdown([D(140)] + [v for _, v in curve]),
        'max_daily_close_drawdown': drawdown([D(140)] + list(close_equity.values())),
        'turnover_usd': str(sum((f.price * f.size for f in fills), ZERO)),
        'execution_gross_usd': str(sum((t.gross_pnl for t in trips), ZERO)),
        'terminal_liquidation_fills': sum(f.metadata_['research']['terminal_liquidation'] for f in fills),
        'daily_exposure': runtime.daily_exposure,
        'average_exposure': str(sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO) / len(runtime.daily_exposure))
            if runtime.daily_exposure else None,
        'blackout': {'symbol_sessions': blackout_dates, 'count': len(blackout_dates),
            'processed_count': sum(r['date'] <= str(runtime.now.astimezone(NEW_YORK).date()) for r in blackout_dates),
            'forced_exit_cost': leg_cost([f for f in fills if f.metadata_['research']['forced_blackout_exit']]),
            'reentry_cost': leg_cost([f for f in fills if f.metadata_['research']['blackout_reentry']])},
        'benchmarks': benchmarks, 'promotion_eligible': False,
        'promotion_reason': 'Amendment21 source/cash/execution counterfactual on free Yahoo bars and '
                            'previously inspected SPY reference; separate forward confirmation required'}


def require_committed():
    paths = ['src/tradingbot/' + name for name in dependencies()]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C02 dependencies before real strategy outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, final=False, expected_version=None):
    commit = require_committed()
    if final:
        consumed = session.scalar(select(Trial).join(StrategyRow, Trial.strategy_id == StrategyRow.id).where(
            Trial.final_holdout.is_(True), StrategyRow.config['candidate'].astext == 'C02-amendment21').order_by(Trial.id))
        if consumed is not None:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused C02 family final reuse despite source/run/version identity changes',
                details={'kind': 'holdout_reuse', 'first_trial_id': consumed.id,
                         'candidate': 'C02-amendment21', 'requested_source_receipt': SOURCE_RECEIPT}))
            session.commit()
            raise ValueError('C02 Amendment21 family final already consumed; read stored evidence')
    key = f'c02-a21-{source["receipt"]["identity"]["data_sha256"][:12]}-{variant}-{bp}-' + ('final' if final else 'train')
    prior = session.scalar(select(StrategyRow.id).where(StrategyRow.key == key))
    if prior:
        if final:
            session.add(Incident(severity='warning', category='other', mode='backtest',
                message='Refused repeated C02 final invocation before feed construction',
                details={'kind': 'holdout_reuse', 'requested_strategy_id': prior, 'source_receipt': SOURCE_RECEIPT}))
            session.commit()
        raise ValueError('C02 configuration already attempted; read stored results, never replay')
    if variant not in VARIANTS or bp not in COSTS or (final and bp != 10):
        raise ValueError('C02 configuration outside frozen variant/cost family')
    CaptureDiskBudget(ROOT / 'data').check()
    instruments = {symbol: instrument_for(session, symbol) for symbol in SYMBOLS}
    ids = {symbol: pair[0] for symbol, pair in instruments.items()}
    venue = instruments['XLB'][1]
    spy, _ = instrument_for(session, 'SPY')
    params = strategy_params(source, ids, spy, variant)
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp_per_side': bp, 'dependencies': dependencies(),
               'fx_source_sha256': fx.source_hash, 'source_receipt': source['receipt']['receipt_sha256'],
               'fee_policy': 'EquityFeeBook 2026-09-17 current-account counterfactual'}
    row = StrategyRow(key=key, name=f'C02 monthly sector momentum {variant} / {bp}bp ' + ('final' if final else 'training'),
        venue_id=venue, status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C02-amendment21', 'research_family': 'c02', 'params': params})
    session.add(row); session.commit()
    sid, split = row.id, split_for(source)
    runtime = calculated = None
    observed = []
    try:
        bot = SectorMomentum(params)
        runtime = C02Backtester(session, strategy=bot, strategy_id=sid, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and (not expected_version or calculated != expected_version):
            raise ValueError('C02 final version differs from frozen choice before feed construction')
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C02 monthly sector momentum / Amendment21; actual-share opens, payable dividends, conservative T+1 cash.')
        metrics, trips, fills = finish_metrics(session, result, runtime)
        metrics.update(diagnostics(bot, source, observed, trips, fills, runtime, final))
        metrics['complete_execution'] = not metrics['open_positions'] and result.orders_rejected == 0
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version = commit, 'c02-amendment21-v1'
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
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c02-amendment21-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C02 attempt failed; existing fills and consumed final preserved: {type(error).__name__}: {error}'
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
            if runtime.now is not None:
                try:
                    fills = list(session.scalars(select(Fill).where(Fill.trial_id == trial.id)))
                    execution_net = sum(((f.realized_pnl or ZERO) - f.fee for f in fills), ZERO)
                    rejected = len(list(session.scalars(select(Order.id).where(Order.trial_id == trial.id, Order.status == 'rejected'))))
                    partial = SimpleNamespace(trial_id=trial.id, orders_rejected=rejected,
                        report={'pnl_after_fees': str(execution_net), 'holdout': split.metadata()})
                    measured, trips, fills = finish_metrics(session, partial, runtime)
                    measured.update(diagnostics(bot, source, observed, trips, fills, runtime, final))
                    trial.metrics = json_value({**measured, 'complete_execution': False,
                        'partial_replay': True, 'last_processed_at': runtime.now,
                        'curve': runtime.curve, 'failure': str(error), 'promotion_eligible': False})
                except Exception as audit_error:
                    trial.metrics = {**trial.metrics, 'partial_measurement_error': str(audit_error)}
        session.commit()
        if not isinstance(error, Exception):
            raise
        return {'status': 'failed', 'variant': variant, 'cost_bp': bp, 'final_holdout': bool(trial.final_holdout),
                'requested_final': final, 'trial_id': trial.id, 'strategy_id': sid,
                'git_commit': commit, 'error': str(error), 'strategy_version': trial.strategy_version,
                'metrics': trial.metrics}


def immutable_artifact(name, body):
    raw = (json.dumps(json_value(body), indent=2, sort_keys=True) + '\n').encode()
    path = ARCHIVE_C02 / 'runs' / name
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C02 outcome artifact')
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
    (ROOT / 'docs/research/24-c02-momentum-selection.json').write_bytes(path.read_bytes())
    print(json.dumps({'selected': choice['selected'], 'selection_sha256': digest, 'final_attempted': False}))


def final():
    source = load_source()
    commit = require_committed()
    name = 'docs/research/24-c02-momentum-selection.json'
    committed = subprocess.check_output(['git', 'show', commit + ':' + name], cwd=ROOT)
    if (ROOT / name).read_bytes() != committed:
        raise ValueError('C02 selection must be committed before final')
    choice = json.loads(committed)
    if (choice['source_receipt'] != SOURCE_RECEIPT or choice['dependencies'] != dependencies()
            or choice['split'] != source['receipt']['split'] or choice['selected'] not in VARIANTS):
        raise ValueError('no valid frozen profitable C02 choice')
    chosen = next(r for r in choice['training'] if r['variant'] == choice['selected'] and r['cost_bp'] == 10)
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != choice['selected_strategy_version']
                or trial.metrics != chosen['metrics'] or D(trial.metrics['net_usd']) <= 0
                or not trial.metrics['complete_execution']):
            raise ValueError('C02 frozen choice disagrees with durable training evidence')
        result = run_variant(session, source, choice['selected'], 10, final=True,
                             expected_version=choice['selected_strategy_version'])
    path, digest = immutable_artifact('final.json', result)
    receipt = {k: v for k, v in result.items() if k not in {'curve', 'trades', 'fill_ids'}}
    receipt.update({'artifact': str(path.relative_to(ROOT)), 'artifact_sha256': digest,
                    'selection_sha256': sha(committed), 'promotion': 'none'})
    (ROOT / 'docs/research/24-c02-momentum-final.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'trial_id': result['trial_id'], 'status': result['status'],
                     'net_usd': result.get('metrics', {}).get('net_usd'), 'promotion': 'none'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('train', 'final'))
    args = parser.parse_args()
    train() if args.phase == 'train' else final()


if __name__ == '__main__':
    main()
