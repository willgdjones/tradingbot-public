"""Finite-collateral prediction research through the shared reactor/risk/ledger.

Only research-local balances/halts are changed. Public prints are observations,
not account executions; the ledger records the explicit maker/fee scenario.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select

from tradingbot.db.models import Instrument, Position, RiskHalt, Strategy as StrategyRow, Venue
from tradingbot.risk import limits
from tradingbot.risk.engine import RiskEngine
from tradingbot.strategy.interface import CancelOrder, PlaceOrder
from .engine import Backtester
from .favourite_longshot import _PmUsFeeLedger, PM_US_RESEARCH_SCHEDULE
from .holdout import utc

D = Decimal
ZERO = D(0)


class PredictionLedger(_PmUsFeeLedger):
    def __init__(self, session, runtime):
        super().__init__(session, auto_fee=True,
                         fee_schedules={'polymarket_us': PM_US_RESEARCH_SCHEDULE})
        self.runtime = runtime
        self.position_cache = {}

    def get_position(self, strategy_id, mode, instrument_id):
        key = (strategy_id, mode, instrument_id)
        if strategy_id == self.runtime.strategy_id and mode == self.runtime.mode:
            # Construction verified an empty isolated book. Only our fills can
            # create positions; do not query the DB for every public observation.
            return self.position_cache.get(key)
        if key not in self.position_cache:
            self.position_cache[key] = super().get_position(*key)
        return self.position_cache[key]

    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        runtime, iid = self.runtime, fill.instrument_id
        key = (runtime.strategy_id, runtime.mode, iid)
        if self.position_cache.get(key) is None:
            self.position_cache[key] = super().get_position(*key)
        signed = fill.size if fill.side == 'buy' else -fill.size
        runtime.cash -= signed * fill.price + fill.fee
        runtime.quantities[iid] = runtime.quantities.get(iid, ZERO) + signed
        runtime.inventory_value += signed * runtime.marks[iid]
        runtime.fees += fill.fee
        if (fill.metadata_ or {}).get('settlement'):
            runtime.collateral[iid] = ZERO
        else:
            # This adapter is for one-sided accumulation held to settlement.
            unit = fill.price if fill.side == 'buy' else 1 - fill.price
            runtime.collateral[iid] = runtime.collateral.get(iid, ZERO) + fill.size * unit
            runtime.entry_times.setdefault(iid, fill.fill_ts)
            runtime.entry_prices.setdefault(iid, fill.price)
        runtime.record_equity(fill.fill_ts)
        return fill


class PredictionRisk(RiskEngine):
    """The shared pre-trade checks, using this isolated replay's clock and book."""
    def __init__(self, session, runtime):
        super().__init__(session)
        self.runtime, self.ledger = runtime, runtime.ledger
        self.persisted_halt_days = set(session.scalars(select(RiskHalt.halt_date).where(
            RiskHalt.scope == 'global_daily', RiskHalt.mode == 'backtest', RiskHalt.active.is_(True))))

    def stale_data_check(self, instrument_id, now=None):
        latest = self.runtime.observed.get(instrument_id)
        if latest is None or now is None:
            return False, None
        age = (utc(now) - utc(latest)).total_seconds()
        return 0 <= age <= limits.STALE_DATA_MAX_SECONDS, age

    def is_strategy_killed(self, strategy_id):
        return self.runtime.killed

    def daily_halt_active(self, mode, day=None):
        return day in self.persisted_halt_days or (day == self.runtime.day and self.runtime.daily_halted)

    def position_cap_usd(self, strategy_id, instrument_id):
        # The constructor verifies every allowed instrument is a binary prediction.
        return limits.position_cap_usd('prediction_market', self.runtime.initial_cash)

    def _multiplier(self, instrument_id):
        return D(1)  # Verified instrument multiplier, not a mutable risk setting.


class PredictionBacktester(Backtester):
    def __init__(self, session, *, strategy, strategy_id, instruments, initial_cash=D('140')):
        super().__init__(session, strategy=strategy, strategy_id=strategy_id)
        row = session.get(StrategyRow, strategy_id)
        if row is None or row.status != 'backtest' or row.allocation_usd != initial_cash or initial_cash <= 0:
            raise ValueError('dedicated backtest strategy must match virtual collateral')
        if session.scalar(select(Position.id).where(Position.strategy_id == strategy_id,
                                                   Position.mode == 'backtest')) is not None:
            raise ValueError('prediction research must start with an empty isolated book')
        # Full manifest verification belongs to the caller; each record exposes
        # native venue/type/multiplier so non-binary inputs cannot use this adapter.
        if not instruments or any(i['venue'] not in {'kalshi', 'polymarket_intl', 'polymarket_us'}
                                  or i['instrument_type'] not in {'binary_yes', 'binary_no'}
                                  or D(i['multiplier']) != 1 for i in instruments):
            raise ValueError('unit-multiplier binary prediction instruments required')
        self.instruments = {i['instrument_id']: i for i in instruments}
        if len(self.instruments) != len(instruments):
            raise ValueError('duplicate research instruments')
        actual = session.execute(select(Instrument.id, Instrument.instrument_type, Instrument.contract_multiplier,
                                        Venue.key, Venue.kind).join(Venue, Venue.id == Instrument.venue_id)
                                 .where(Instrument.id.in_(self.instruments))).all()
        if len(actual) != len(instruments) or any(
                kind != 'prediction_market' or instrument_type != self.instruments[iid]['instrument_type']
                or multiplier != 1 or venue != self.instruments[iid]['venue']
                for iid, instrument_type, multiplier, venue, kind in actual):
            raise ValueError('binary manifest disagrees with database instrument/venue identity')
        self.initial_cash = self.cash = initial_cash
        self.quantities, self.marks, self.observed, self.collateral = {}, {}, {}, {}
        self.entry_times, self.entry_prices = {}, {}
        self.inventory_value = self.fees = ZERO
        self.killed = self.daily_halted = False
        self.day = self.now = None
        self.day_start_equity = self.last_equity = self.peak_equity = initial_cash
        self.max_drawdown = self.max_collateral = ZERO
        self.halt_events, self.holding_breaches = [], []
        self.daily, self.monthly = {}, {}
        self.rejection_reasons = Counter()
        self.rejected_cache = {}
        self.ledger = PredictionLedger(session, self)
        self.risk = PredictionRisk(session, self)
        self.version_context = {'initial_cash': initial_cash, 'collateral': 'fully funded held plus pending; profits above slot parked',
                                'fee_basis': PM_US_RESEARCH_SCHEDULE.schedule_id,
                                'quantity_precision': '0.0000000001 rounded down',
                                'persisted_backtest_halt_days': sorted(d.isoformat() for d in self.risk.persisted_halt_days),
                                'risk_clock': 'UTC observed equity, print fills before reactive halt'}

    def equity(self):
        return self.cash + self.inventory_value

    def advance(self, ts):
        ts = utc(ts)
        if self.now is not None and ts < self.now:
            raise ValueError('prediction clock cannot move backwards')
        if ts.date() != self.day:
            self.day, self.day_start_equity, self.daily_halted = ts.date(), self.last_equity, False
        self.now = ts

    def mark(self, iid, price):
        self.inventory_value += self.quantities.get(iid, ZERO) * (price - self.marks.get(iid, price))
        self.marks[iid] = price

    def record_equity(self, ts):
        equity = self.equity()
        self.peak_equity = max(self.peak_equity, equity)
        self.max_drawdown = max(self.max_drawdown, self.peak_equity - equity)
        self.last_equity = equity
        self.daily[utc(ts).date().isoformat()] = equity
        month = utc(ts).strftime('%Y-%m')
        bucket = self.monthly.setdefault(month, {'start_equity': self.day_start_equity,
                                                'peak_equity': self.day_start_equity, 'max_drawdown': ZERO})
        bucket['end_equity'] = equity
        bucket['peak_equity'] = max(bucket['peak_equity'], equity)
        bucket['max_drawdown'] = max(bucket['max_drawdown'], bucket['peak_equity'] - equity)
        if equity - self.initial_cash <= -limits.PER_STRATEGY_KILL_FRACTION * self.initial_cash:
            if not self.killed:
                self.halt_events.append({'time': utc(ts).isoformat(), 'kind': 'per_strategy_kill', 'equity': str(equity)})
            self.killed = True
        if equity - self.day_start_equity <= limits.GLOBAL_DAILY_HALT_USD:
            if not self.daily_halted:
                self.halt_events.append({'time': utc(ts).isoformat(), 'kind': 'global_daily_halt', 'equity': str(equity)})
            self.daily_halted = True

    def _before_event(self, event, ctx, resting, order_by_tag, trial, counters):
        self.advance(event.time)
        if event.instrument_id not in self.instruments:
            raise ValueError('event is outside the frozen binary manifest')
        if not event.meta.get('timer'):
            price = event.as_snapshot().reference_price
            if price is None or not 0 <= price <= 1:
                raise ValueError('invalid prediction observation')
            self.mark(event.instrument_id, price)
            self.observed[event.instrument_id] = utc(event.time)
        # Known deadlines can cancel before this print; its surprise price cannot.
        blackout = timedelta(seconds=int(self.strategy.params.get('entry_blackout_seconds', 0)))
        for tag, order in tuple(resting.items()):
            deadline = utc(datetime.fromisoformat(self.instruments[order.instrument_id]['close_ts'])) - blackout
            if self.now >= deadline:
                self._handle_intent(CancelOrder(tag), ctx, resting, order_by_tag, trial, counters)

    def _after_event(self, event, ctx, resting, order_by_tag, trial, counters):
        self.record_equity(event.time)
        if self.killed or self.daily_halted or self.day in self.risk.persisted_halt_days:
            for tag in tuple(resting):
                self._handle_intent(CancelOrder(tag), ctx, resting, order_by_tag, trial, counters)

    def _apply_trade_fills(self, event, resting, order_by_tag, counters):
        size = event.size.quantize(D('.0000000001'), rounding=ROUND_DOWN)
        if size > 0:
            super()._apply_trade_fills(replace(event, size=size), resting, order_by_tag, counters)

    def _settle(self, settlement, ctx, resting, order_by_tag, trial):
        self.advance(settlement.ts)
        self.mark(settlement.instrument_id, settlement.price)
        entered = self.entry_times.get(settlement.instrument_id)
        if entered is not None and utc(settlement.ts) - utc(entered) > timedelta(days=7):
            self.holding_breaches.append({'instrument_id': settlement.instrument_id,
                                         'entry': utc(entered).isoformat(), 'resolution': utc(settlement.ts).isoformat()})
        super()._settle(settlement, ctx, resting, order_by_tag, trial)
        self.record_equity(settlement.ts)
        if self.killed or self.daily_halted or self.day in self.risk.persisted_halt_days:
            for tag in tuple(resting):
                self._handle_intent(CancelOrder(tag), ctx, resting, order_by_tag, trial, {})

    def _reservation(self, side, price, size):
        return size * (price if side == 'buy' else 1 - price)

    def _handle_intent(self, intent, ctx, resting, order_by_tag, trial, counters):
        if not isinstance(intent, PlaceOrder):
            return super()._handle_intent(intent, ctx, resting, order_by_tag, trial, counters)
        if intent.instrument_id not in self.instruments or intent.intended_liquidity != 'maker':
            raise ValueError('prediction study permits only manifested maker orders')
        if intent.limit_price is None or not 0 < intent.limit_price < 1 or intent.size <= 0:
            raise ValueError('invalid binary order')
        iid, q = intent.instrument_id, self.quantities.get(intent.instrument_id, ZERO)
        if q and (q > 0) != (intent.side == 'buy'):
            raise ValueError('prediction study holds one side until terminal settlement')
        contract = self.instruments[iid]['contract']
        held = sum(self.collateral.values(), ZERO)
        reserved = sum((self._reservation(o.side, o.limit_price, o.remaining) for o in resting.values()), ZERO)
        short_liability = sum((-q for q in self.quantities.values() if q < 0), ZERO)
        required = self._reservation(intent.side, intent.limit_price, intent.size)
        available = min(self.cash - short_liability - reserved, self.initial_cash - held - reserved)
        contract_held = sum((value for key, value in self.collateral.items()
                             if self.instruments[key]['contract'] == contract), ZERO)
        contract_reserved = sum((self._reservation(o.side, o.limit_price, o.remaining) for o in resting.values()
                                if self.instruments[o.instrument_id]['contract'] == contract), ZERO)
        reason = None
        deadline = utc(datetime.fromisoformat(self.instruments[iid]['close_ts'])) - timedelta(
            seconds=int(self.strategy.params.get('entry_blackout_seconds', 0)))
        if self.now >= deadline:
            reason = 'scheduled-event entry blackout'
        elif required > available:
            reason = 'insufficient fully funded collateral including pending orders'
        elif contract_held + contract_reserved + required > self.risk.position_cap_usd(self.strategy_id, iid):
            reason = 'binary contract held plus pending collateral exceeds prediction cap'
        if reason:
            self._record_order(intent, trial, status='rejected', reason=reason)
            counters['rejected'] += 1
            return
        super()._handle_intent(intent, ctx, resting, order_by_tag, trial, counters)
        self.max_collateral = max(self.max_collateral, held + sum(
            (self._reservation(o.side, o.limit_price, o.remaining) for o in resting.values()), ZERO))

    def _record_order(self, intent, trial, *, status, reason=None):
        if status == 'rejected':
            self.rejection_reasons[reason] += 1
            key = (intent.instrument_id, intent.tag, intent.side, intent.limit_price, intent.size, reason)
            if key in self.rejected_cache:
                order = self.rejected_cache[key]
                order.metadata_ = {**order.metadata_, 'attempt_count': order.metadata_.get('attempt_count', 1) + 1,
                                   'last_attempt_ts': self._replay_time.isoformat()}
                return order
        order = super()._record_order(intent, trial, status=status, reason=reason)
        if status == 'rejected':
            self.rejected_cache[key] = order
        return order
