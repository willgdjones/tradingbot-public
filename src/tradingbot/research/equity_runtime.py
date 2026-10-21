"""Equity research adapter over the shared strategy/backtester and ledger.

Bar execution is an explicit scenario, never written as observed DB BBO. All
orders pass the unchanged risk limits; cash and fees are research-local state.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from tradingbot.backtest import Backtester
from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.backtest.fills import taker_fill_price
from tradingbot.connectors.cash import CashMovement, MarketSession, NEW_YORK, cash_balance
from tradingbot.db.models import Strategy as StrategyRow
from tradingbot.ledger.ledger import Ledger
from tradingbot.risk.engine import RiskEngine
from tradingbot.risk import limits
from tradingbot.strategy.interface import PlaceOrder, Strategy, StrategyContext
from .equity_fees import EquityFeeBook

ZERO = Decimal(0)


def equity_split(data, symbols):
    """Pin the split to full source coverage, never a requested evaluation slice."""
    bars = [bar for (symbol, _), bar in data.bars.get("bars_1Day_raw", {}).items() if symbol in symbols]
    if not bars:
        raise ValueError("daily source coverage is required for the locked split")
    first, last = min(bar.time for bar in bars), max(bar.time for bar in bars)
    last_day = last.astimezone(NEW_YORK).date()
    return HoldoutSplit("equity:" + data.source_hash, first,
                        data.sessions[last_day].closes_at + timedelta(microseconds=1))


class ReplayRisk(RiskEngine):
    """Use the replay's latest observation, not a future row from the live DB."""
    def __init__(self, session, runtime):
        super().__init__(session)
        self.runtime = runtime

    def stale_data_check(self, instrument_id, now=None):
        observation = self.runtime.observed.get(instrument_id)
        if observation is None or now is None:
            return False, None
        age = (now - observation).total_seconds()
        return 0 <= age <= limits.STALE_DATA_MAX_SECONDS, age

    def is_strategy_killed(self, strategy_id):
        return self.runtime.killed or super().is_strategy_killed(strategy_id)

    def daily_halt_active(self, mode, day=None):
        return (self.runtime.daily_halted and day == self.runtime.day) or super().daily_halt_active(mode, day)


class EquityResearchLedger(Ledger):
    def __init__(self, session, runtime):
        super().__init__(session, auto_fee=False)
        self.runtime = runtime

    def record_order(self, **kwargs):
        order = super().record_order(**kwargs)
        order.created_ts = self.runtime.now
        if order.status != 'rejected':
            order.submitted_ts = self.runtime.now
        return order

    def record_fill(self, **kwargs):
        runtime = self.runtime
        ts, price, size, order = kwargs['fill_ts'], kwargs['price'], kwargs['size'], kwargs['order']
        day = ts.astimezone(NEW_YORK).date()
        side = kwargs.get('side') or order.side
        fee, fee_evidence = runtime.fees.charge(day=day, side=side, price=price, size=size)
        rate, fx_day = runtime.fx.at(ts)
        kwargs['fee'], kwargs['usd_gbp_rate'] = fee, rate
        kwargs['metadata'] = {**(kwargs.get('metadata') or {}), 'research': {
            'source': 'alpaca_sip_bar_execution_scenario', 'not_broker_execution': True,
            'fee': fee_evidence, 'fx_reference_date': fx_day.isoformat(),
            'fx_source': runtime.fx.source_url, 'fx_sha256': runtime.fx.source_hash,
            'execution': runtime.execution_meta, 'cash_bucket': runtime.active_bucket,
            'settlement_date': runtime.sessions[day].settlement_date.isoformat(),
        }}
        fill = super().record_fill(**kwargs)
        runtime.cash[runtime.active_bucket].append(CashMovement(side, price * size, fee, runtime.sessions[day].settlement_date))
        runtime.realized += fill.realized_pnl or ZERO
        runtime.charged += fee
        position = self.get_position(order.strategy_id, 'backtest', order.instrument_id)
        runtime.positions[order.instrument_id] = (position.quantity, position.avg_price or ZERO)
        if side == 'buy':
            runtime.position_bucket[order.instrument_id] = runtime.active_bucket
        runtime.record_equity(ts)
        return fill


class EquityContext(StrategyContext):
    """Expose replay cash through the same optional read-only context API."""
    def __init__(self, delegate, runtime):
        self.delegate, self.runtime = delegate, runtime

    @property
    def now(self): return self.delegate.now
    @property
    def mode(self): return self.delegate.mode
    @property
    def params(self): return self.delegate.params
    def position(self, instrument_id): return self.delegate.position(instrument_id)
    def snapshot(self, instrument_id): return self.delegate.snapshot(instrument_id)
    def resting_tags(self, instrument_id=None): return self.delegate.resting_tags(instrument_id)

    def available_cash(self, instrument_id):
        runtime = self.runtime
        day = self.now.astimezone(NEW_YORK).date()
        bucket = runtime.bucket_by_day.get(day, 0)
        return cash_balance(runtime.initial_cash / runtime.buckets, runtime.cash[bucket], ZERO, self.now).available


class ObservedStrategy(Strategy):
    """Runtime instrumentation; decisions remain entirely in the wrapped strategy."""
    key = 'equity_research_observer'

    def __init__(self, delegate, runtime):
        self.delegate, self.runtime = delegate, runtime
        super().__init__(delegate.params)

    def on_start(self, ctx):
        self.delegate.on_start(EquityContext(ctx, self.runtime))

    def on_event(self, ctx, event):
        self.runtime.observe(event)
        return self.delegate.on_event(EquityContext(ctx, self.runtime), event)

    def on_finish(self, ctx):
        self.delegate.on_finish(EquityContext(ctx, self.runtime))


class EquityBacktester(Backtester):
    def __init__(self, session, *, strategy, strategy_id, sessions: dict[date, MarketSession],
                 fx, initial_cash=Decimal('140'), buckets=1, bucket_by_day=None):
        if initial_cash <= 0 or buckets not in {1, 2}:
            raise ValueError('invalid simulated cash budget')
        self.sessions, self.fx = sessions, fx
        self.initial_cash, self.buckets = initial_cash, buckets
        self.cash = defaultdict(list)
        self.bucket_by_day = bucket_by_day or {}
        self.position_bucket = {}
        self.positions, self.marks, self.observed = {}, {}, {}
        self.realized = self.charged = ZERO
        self.killed = self.daily_halted = False
        self.halt_events = []
        self.day = self.now = None
        self.day_start_equity = self.last_equity = self.peak_equity = initial_cash
        self.max_drawdown = ZERO
        self.curve = []
        self.fees = EquityFeeBook()
        self.execution_meta = {}
        self.active_bucket = 0
        super().__init__(session, strategy=ObservedStrategy(strategy, self), strategy_id=strategy_id)
        self.version_strategy = strategy
        self.version_context = {"initial_cash": initial_cash, "cash_buckets": buckets,
                                "bucket_by_day": bucket_by_day or {}}
        self.ledger = EquityResearchLedger(session, self)
        self.risk = ReplayRisk(session, self)
        # The allocation is a virtual research input, never a funded account.
        row = session.get(StrategyRow, strategy_id)
        if row is None or row.status != 'backtest' or row.allocation_usd != initial_cash:
            raise ValueError('dedicated backtest strategy must match virtual budget')

    def equity(self):
        unrealized = sum(((self.marks[iid] - average) * quantity
                          for iid, (quantity, average) in self.positions.items()
                          if quantity and iid in self.marks), ZERO)
        return self.initial_cash + self.realized - self.charged + unrealized

    def record_equity(self, ts):
        equity = self.equity()
        self.peak_equity = max(self.peak_equity, equity)
        self.max_drawdown = max(self.max_drawdown, self.peak_equity - equity)
        self.curve.append((ts, equity))
        self.last_equity = equity
        if equity - self.initial_cash <= -limits.PER_STRATEGY_KILL_FRACTION * self.initial_cash:
            if not self.killed:
                self.halt_events.append({'time': ts.isoformat(), 'kind': 'per_strategy_kill', 'equity_usd': str(equity)})
            self.killed = True
        if equity - self.day_start_equity <= limits.GLOBAL_DAILY_HALT_USD:
            if not self.daily_halted:
                self.halt_events.append({'time': ts.isoformat(), 'kind': 'global_daily_halt', 'equity_usd': str(equity)})
            self.daily_halted = True

    def observe(self, event):
        day = event.time.astimezone(NEW_YORK).date()
        if self.now is not None and event.time < self.now:
            raise ValueError('events must be chronological')
        if day not in self.sessions:
            raise ValueError('missing trading/settlement calendar')
        if day != self.day:
            self.day_start_equity = self.last_equity
            self.day, self.daily_halted = day, False
        self.now = event.time
        reference = event.as_snapshot().reference_price
        if reference is None:
            raise ValueError('equity research event has no mark')
        self.marks[event.instrument_id] = reference
        self.observed[event.instrument_id] = event.time
        self.execution_meta = event.meta
        self.record_equity(event.time)

    def _handle_intent(self, intent, ctx, resting, order_by_tag, trial, counters):
        if not isinstance(intent, PlaceOrder):
            return super()._handle_intent(intent, ctx, resting, order_by_tag, trial, counters)
        if intent.intended_liquidity != 'taker':
            raise ValueError('bar research adapter does not simulate maker fills')
        day = ctx.now.astimezone(NEW_YORK).date()
        bucket = self.bucket_by_day.get(day, 0) if intent.side == 'buy' else self.position_bucket.get(intent.instrument_id, 0)
        if not 0 <= bucket < self.buckets:
            raise ValueError('invalid cash bucket')
        self.active_bucket = bucket
        balance = cash_balance(self.initial_cash / self.buckets, self.cash[bucket], ZERO, ctx.now)
        price = taker_fill_price(intent.side, ctx.snapshot(intent.instrument_id))
        if price is None:
            raise ValueError('no assumed execution price')
        fee, _ = self.fees.charge(day=day, side=intent.side, price=price, size=intent.size, commit=False)
        current = ctx.position(intent.instrument_id)
        reason = None
        if intent.side == 'sell' and intent.size > current:
            reason = 'cash research forbids short sales'
        elif intent.side == 'buy' and price * intent.size + fee > balance.available:
            reason = 'insufficient settled cash in assigned half'
        elif intent.side == 'buy' and price * intent.size < 1:
            reason = 'fractional buy below $1 minimum'
        if reason:
            self._record_order(intent, trial, status='rejected', reason=reason)
            counters['rejected'] += 1
            return
        super()._handle_intent(intent, ctx, resting, order_by_tag, trial, counters)
