"""Forward PM US paper execution, with durable orders and per-event commits.

The session belongs exclusively to this engine. No venue API is called. A
caller supplies an explicitly reviewed standard, non-sports instrument universe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.backtest.fills import RestingOrder
from tradingbot.db import enums
from tradingbot.db.models import Fill, FxRate, Instrument, Market, Order, Position, Quote, Strategy as StrategyRow, Trial, Venue
from tradingbot.fees import FeeFill, PolymarketUSOrderFees, PM_US_STANDARD_2026_09_25
from tradingbot.ledger import Ledger
from tradingbot.risk import RiskEngine, limits
from tradingbot.strategy import CancelOrder, MarketEvent, MarketSnapshot, PlaceOrder, Strategy, StrategyContext

from .feed import FeedCursor, QUOTE_SOURCES, live_events
from .fills import SubmittedMaker, book_key, instant, maker_fills, positive, trade_key

ZERO = Decimal(0)
ACTIVE = (enums.OrderStatus.OPEN, enums.OrderStatus.PARTIALLY_FILLED, enums.OrderStatus.PENDING)
NAME = "pm_us_paper_v1"


class PaperContext(StrategyContext):
    def __init__(self, engine: PaperEngine):
        self.engine = engine

    @property
    def now(self):
        return self.engine.time

    @property
    def mode(self):
        return enums.Mode.PAPER

    @property
    def params(self):
        return dict(self.engine.strategy.params)

    def position(self, instrument_id):
        pos = self.engine.ledger.get_position(self.engine.strategy_id, self.mode, instrument_id)
        return pos.quantity if pos else ZERO

    def snapshot(self, instrument_id):
        return self.engine.snapshots.get(instrument_id)

    def resting_tags(self, instrument_id=None):
        return tuple(row.metadata_["tag"] for row in self.engine._orders()
                     if instrument_id is None or row.instrument_id == instrument_id)


class PaperEngine:
    """One trial/strategy, polled from the recorder's committed live rows.

    Start is explicit. A process exit never cancels resting orders. Resume is
    also explicit and requires strategy state to have been restored by caller;
    database cursors/order state alone cannot serialize arbitrary Python state.
    """

    def __init__(self, session: Session, strategy: Strategy, *, strategy_id: int,
                 instrument_ids: list[int], now=None):
        if not instrument_ids or len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("Provide a nonempty distinct, reviewed instrument universe")
        self.session, self.strategy, self.strategy_id = session, strategy, strategy_id
        self.instrument_ids = list(instrument_ids)
        self.clock = now or (lambda: datetime.now(timezone.utc))
        self.time = instant(self.clock())
        self.ledger = Ledger(session, auto_fee=False)
        self.risk = RiskEngine(session)
        self.ctx = PaperContext(self)
        self.trial_id = None
        self.snapshots: dict[int, MarketSnapshot] = {}
        self.books: dict[int, MarketEvent] = {}
        self.venue_id = None

    def _lock(self):
        # Serialize liquidity consumption/reservations across paper processes.
        self.session.expire_all()
        self.session.execute(select(Venue).where(Venue.id == self.venue_id).with_for_update()).scalar_one()

    def _trial(self):
        row = self.session.get(Trial, self.trial_id)
        if row is None or row.status != enums.TrialStatus.RUNNING:
            raise ValueError("A running paper trial is required")
        return row

    def _state(self):
        return dict(self._trial().metrics[NAME])

    def _save(self, state):
        trial = self._trial()
        trial.metrics = {**(trial.metrics or {}), NAME: state}

    def _validate_universe(self):
        row = self.session.get(StrategyRow, self.strategy_id)
        if row is None or row.status != enums.StrategyStatus.PAPER or row.allocation_usd <= 0:
            raise ValueError("Strategy must already be in paper with a positive allocation")
        venue = self.session.scalar(select(Venue).where(Venue.key == "polymarket_us"))
        if venue is None or row.venue_id != venue.id:
            raise ValueError("This paper runtime supports Polymarket US only")
        self.venue_id = venue.id
        for iid in self.instrument_ids:
            instrument = self.session.get(Instrument, iid)
            market = self.session.get(Market, instrument.market_id) if instrument else None
            if (instrument is None or instrument.venue_id != venue.id or instrument.currency != "USD"
                    or instrument.contract_multiplier != 1 or instrument.instrument_type not in
                    (enums.InstrumentType.BINARY_YES, enums.InstrumentType.BINARY_NO)
                    or market is None or market.status != enums.MarketStatus.OPEN
                    or not market.category or "sport" in market.category.lower()):
                raise ValueError("Only reviewed open, categorized non-sports USD binary markets are supported")

    def start(self, *, git_commit: str | None = None) -> int:
        if self.trial_id is not None:
            raise ValueError("Engine already started")
        self.time = instant(self.clock())
        # Persist every attempted variant before validation or strategy callbacks.
        trial = Trial(strategy_id=self.strategy_id, mode="paper", params=self.strategy.params,
                      git_commit=git_commit, code_version=NAME, data_start=self.time,
                      metrics={NAME: {"started_at": self.time.isoformat(), "quote_id": 0, "trade_id": 0,
                                      "instrument_ids": self.instrument_ids, "strategy_key": self.strategy.key,
                                      "fee_schedule": PM_US_STANDARD_2026_09_25.schedule_id}})
        self.session.add(trial)
        self.session.commit()
        self.trial_id = trial.id
        try:
            self._validate_universe()
            self._lock()
            existing = self.session.scalar(select(Order.id).where(
                Order.strategy_id == self.strategy_id, Order.mode == "paper", Order.status.in_(ACTIVE)))
            if existing is not None or self.ledger.open_positions(strategy_id=self.strategy_id, mode="paper"):
                raise ValueError("Existing paper orders or positions require explicit continuation of their trial")
            self.strategy.on_start(self.ctx)
            self.session.commit()
        except Exception as exc:
            self._fail(exc)
            raise
        return self.trial_id

    def resume(self, trial_id: int, *, strategy_state_restored: bool = False):
        if self.trial_id is not None or not strategy_state_restored:
            raise ValueError("Explicitly restore strategy state before resuming")
        self._validate_universe()
        self.trial_id = trial_id
        try:
            self._lock()
            trial, state = self._trial(), self._state()
            if (trial.strategy_id != self.strategy_id or trial.mode != "paper"
                    or trial.params != self.strategy.params or state["strategy_key"] != self.strategy.key
                    or state["instrument_ids"] != self.instrument_ids
                    or state["fee_schedule"] != PM_US_STANDARD_2026_09_25.schedule_id):
                raise ValueError("Trial identity, parameters, universe or fee schedule differ")
            self._restore_views(state)
            self.session.commit()
        except Exception:
            self.session.rollback()
            self.trial_id = None
            raise

    def _orders(self):
        return list(self.session.scalars(select(Order).where(
            Order.trial_id == self.trial_id, Order.mode == "paper", Order.status.in_(ACTIVE)
        ).order_by(Order.submitted_ts, Order.id)))

    def _consumed(self, key):
        return self.session.scalar(select(func.coalesce(func.sum(Fill.size), 0)).where(
            Fill.mode == "paper", Fill.metadata_["liquidity_key"].as_string() == key))

    def _refresh(self):
        # Include all paper positions, not only this strategy's current event.
        marks, mark_times = {}, {}
        ids = self.session.scalars(select(Position.instrument_id).where(
            Position.mode == "paper", Position.status == "open").distinct())
        for iid in ids:
            quote = self.session.scalar(select(Quote).where(
                Quote.instrument_id == iid, Quote.time <= self.time).order_by(Quote.time.desc(), Quote.id.desc()).limit(1))
            if quote:
                value = quote.mid if quote.mid is not None else quote.last
                if value is None and quote.bid is not None and quote.ask is not None:
                    value = (quote.bid + quote.ask) / 2
                if value is not None:
                    marks[iid] = value
                    mark_times[iid] = quote.time
        for iid, snapshot in self.snapshots.items():
            if snapshot.reference_price is not None and snapshot.time >= mark_times.get(iid, snapshot.time):
                marks[iid] = snapshot.reference_price
        self.risk.refresh_halts("paper", marks, now=self.time)

    def _reasons(self, iid, side, size, price, *, exclude_order=None):
        self._refresh()
        decision = self.risk.evaluate_order(instrument_id=iid, strategy_id=self.strategy_id,
                    mode="paper", side=side, size=size, price=price, now=self.time)
        reasons = list(decision.reasons)
        snapshot = self.snapshots.get(iid)
        if snapshot is None or not 0 <= (self.time - snapshot.time).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
            reasons.append("No fresh forward observation")
        # Reserve both independently executable sides across strategies/outcomes.
        # Orders on the opposite side cannot be assumed to fill first/net away risk.
        instrument = self.session.get(Instrument, iid)
        market = self.session.get(Market, instrument.market_id)
        if (market.status != "open" or (market.close_ts is not None and self.time >= market.close_ts)
                or (instrument.expiry_ts is not None and self.time >= instrument.expiry_ts)):
            reasons.append("Market is closed or expired")
        ids = list(self.session.scalars(select(Instrument.id).where(Instrument.market_id == instrument.market_id)))
        positions = {i: ZERO for i in ids}
        buys, sells, prices = dict.fromkeys(ids, ZERO), dict.fromkeys(ids, ZERO), dict.fromkeys(ids, price)
        low_prices = dict.fromkeys(ids, price)
        for row in self.session.scalars(select(Position).where(Position.mode == "paper", Position.instrument_id.in_(ids))):
            positions[row.instrument_id] += row.quantity or ZERO
            if row.quantity:
                prices[row.instrument_id] = max(prices[row.instrument_id], row.avg_price or ZERO)
                low_prices[row.instrument_id] = min(low_prices[row.instrument_id], row.avg_price or price)
        for row in self.session.scalars(select(Order).where(Order.mode == "paper", Order.instrument_id.in_(ids), Order.status.in_(ACTIVE))):
            remaining = row.size - row.filled_size - (size if row.id == exclude_order else ZERO)
            (buys if row.side == "buy" else sells)[row.instrument_id] += max(ZERO, remaining)
            prices[row.instrument_id] = max(prices[row.instrument_id], row.limit_price or price)
            low_prices[row.instrument_id] = min(low_prices[row.instrument_id], row.limit_price or price)
        (buys if side == "buy" else sells)[iid] += size
        # A short binary pays out up to $1: its capital at risk is 1-price,
        # not its small sale proceeds. The shared cap is unchanged.
        exposure = sum(max(max(ZERO, positions[i] + buys[i]) * prices[i],
                           max(ZERO, sells[i] - positions[i]) * (1 - low_prices[i])) for i in ids)
        if exposure > limits.PER_MARKET_POSITION_MAX_USD:
            reasons.append("Per-market position cap including resting orders and other strategies")
        return reasons

    def _fill(self, order, *, price, size, key, evidence):
        if self._reasons(order.instrument_id, order.side, size, price, exclude_order=order.id):
            return False
        rate = self.session.scalar(select(FxRate.rate).where(FxRate.base == "USD", FxRate.quote == "GBP",
                    FxRate.ts <= self.time).order_by(FxRate.ts.desc()).limit(1))
        if rate is None or rate <= 0:
            raise ValueError("A dated positive USD/GBP rate is required for every fill")
        fees = PolymarketUSOrderFees(PM_US_STANDARD_2026_09_25)
        # Rebuild order-level rounding state, so rollback/restart cannot alter fees.
        for fill in self.session.scalars(select(Fill).where(Fill.order_id == order.id).order_by(Fill.id)):
            fees.charge(FeeFill(price=fill.price, quantity=fill.size, liquidity=fill.liquidity,
                               side=fill.side, executed_at=fill.fill_ts))
        fee = fees.charge(FeeFill(price=price, quantity=size, liquidity=order.intended_liquidity,
                                 side=order.side, executed_at=self.time))
        self.ledger.record_fill(order=order, price=price, size=size, liquidity=order.intended_liquidity,
             fill_ts=self.time, fee=fee.net_fee, usd_gbp_rate=rate,
             metadata={"engine": NAME, "liquidity_key": key, "evidence": evidence,
                       "fee_schedule": fee.schedule_id})
        self._refresh()
        return True

    def _makers(self, event):
        rows = {row.id: row for row in self._orders() if row.intended_liquidity == "maker"}
        candidates = [SubmittedMaker(RestingOrder(row.metadata_["tag"], row.id, row.instrument_id,
                        row.side, row.limit_price, row.size - row.filled_size), row.submitted_ts)
                      for row in rows.values()]
        key = trade_key(event)
        for fill in maker_fills(candidates, event, now=self.time, consumed=self._consumed(key)):
            self._fill(rows[fill.order_id], price=fill.price, size=fill.size, key=key,
                       evidence={"row_id": event.meta["row_id"], "received_at": event.time.isoformat(),
                                 "trade_time": event.meta["trade_time"], "trade_price": str(event.price)})

    def _intent(self, intent):
        if isinstance(intent, CancelOrder):
            for row in self._orders():
                if row.metadata_["tag"] == intent.tag:
                    row.status, row.closed_ts = enums.OrderStatus.CANCELED, self.time
            self.session.flush()
            return
        if not isinstance(intent, PlaceOrder):
            raise TypeError("Strategies must return PlaceOrder or CancelOrder")
        if intent.instrument_id not in self.instrument_ids:
            raise ValueError("Strategy requested an instrument outside its reviewed universe")
        size, price = positive(intent.size), positive(intent.limit_price)
        if (intent.order_type != "limit" or intent.intended_liquidity not in ("maker", "taker")
                or price >= 1 or price != price.quantize(Decimal(".00000001"))
                or size != size.quantize(Decimal(".0000000001"))):
            raise ValueError("Use finite binary limit orders with ledger-supported precision")
        tag = intent.tag if intent.tag is not None else uuid4().hex
        if not isinstance(tag, str) or not tag or tag in self.ctx.resting_tags():
            raise ValueError("An order tag must be nonempty and unique among resting orders")
        reasons = self._reasons(intent.instrument_id, intent.side, size, price)
        book = self.books.get(intent.instrument_id)
        fresh_book = book is not None and 0 <= (self.time - book.time).total_seconds() <= limits.STALE_DATA_MAX_SECONDS
        touch = (book.ask if intent.side == "buy" else book.bid) if fresh_book else None
        crosses = touch is not None and (price >= touch if intent.side == "buy" else price <= touch)
        if intent.intended_liquidity == "maker" and crosses:
            reasons.append("Maker order would cross the current book")
        if intent.intended_liquidity == "taker" and not crosses:
            reasons.append("Taker requires a fresh executable BBO within its limit")
        row = self.ledger.record_order(instrument_id=intent.instrument_id, strategy_id=self.strategy_id,
              trial_id=self.trial_id, mode="paper", side=intent.side, order_type="limit", size=size,
              limit_price=price, intended_liquidity=intent.intended_liquidity,
              status="rejected" if reasons else "open", reason="; ".join(reasons) if reasons else intent.reason,
              metadata={"engine": NAME, "tag": tag, "fee_schedule": PM_US_STANDARD_2026_09_25.schedule_id})
        row.created_ts = row.submitted_ts = self.time
        if reasons:
            row.closed_ts = self.time
        elif intent.intended_liquidity == "taker":
            depth = book.ask_size if intent.side == "buy" else book.bid_size
            key = book_key(book, intent.side)
            if depth is not None and depth > 0:
                available = min(size, max(ZERO, depth - self._consumed(key)))
                if available > 0:
                    self._fill(row, price=touch, size=available, key=key,
                               evidence={"quote_row_id": book.meta["row_id"], "received_at": book.time.isoformat()})
            # Explicit immediate-or-cancel simulation for takers only.
            if row.status != "filled":
                row.status, row.closed_ts = "canceled", self.time
        self.session.flush()

    def _restore_views(self, state):
        self.snapshots, self.books = {}, {}
        for key, raw in state.get("books", {}).items():
            values = {name: Decimal(raw[name]) if raw.get(name) is not None else None
                      for name in ("bid", "ask", "mid", "last", "bid_size", "ask_size")}
            self.books[int(key)] = MarketEvent.quote(int(key), instant(raw["time"]), meta=raw["meta"], **values)
        for key, raw in state.get("snapshots", {}).items():
            values = {name: Decimal(raw[name]) if raw.get(name) is not None else None
                      for name in ("bid", "ask", "mid", "last", "bid_size", "ask_size")}
            self.snapshots[int(key)] = MarketSnapshot(int(key), instant(raw["time"]), **values)

    @staticmethod
    def _view(value):
        raw = {name: str(getattr(value, name)) if getattr(value, name) is not None else None
               for name in ("bid", "ask", "mid", "last", "bid_size", "ask_size")}
        return {**raw, "time": value.time.isoformat()}

    def process(self, event: MarketEvent) -> bool:
        """Commit one recorder row atomically, including callback intents/fills.

        Use poll() in production; process() accepts the same adapter's row events
        for deterministic tests. It never ingests synthetic data into the recorder.
        """
        self.time = instant(self.clock())
        try:
            self._lock()
            state = self._state()
            self._restore_views(state)
            channel = "trade_id" if event.is_trade else "quote_id"
            row_id = event.meta.get("row_id")
            if (type(row_id) is not int or row_id <= 0 or event.instrument_id not in self.instrument_ids
                    or event.meta.get("source") not in (("trade",) if event.is_trade else QUOTE_SOURCES)
                    or event.time < instant(state["started_at"]) or event.time > self.time):
                raise ValueError("Expected a committed forward live-recorder observation")
            if row_id <= state[channel]:
                self.session.rollback()
                return False
            state[channel] = row_id
            # Older arriving rows are consumed but cannot rewind strategy/book time.
            if state.get("observed_at") and event.time < instant(state["observed_at"]):
                self._save(state)
                self.session.commit()
                return False
            state["observed_at"] = event.time.isoformat()
            previous = self.snapshots.get(event.instrument_id)
            if event.is_quote:
                self.books[event.instrument_id] = event
                self.snapshots[event.instrument_id] = event.as_snapshot()
            else:
                # A trade updates last/time, never refreshes the separate BBO age.
                self.snapshots[event.instrument_id] = MarketSnapshot(event.instrument_id, event.time,
                    last=event.price, bid=previous.bid if previous else None, ask=previous.ask if previous else None,
                    mid=event.price, bid_size=previous.bid_size if previous else None, ask_size=previous.ask_size if previous else None)
                self._makers(event)  # before reacting; orders cannot fill on their creating print
            self._refresh()
            for intent in self.strategy.on_event(self.ctx, event):
                self._intent(intent)
            state["books"] = {str(i): {**self._view(v), "meta": v.meta} for i, v in self.books.items()}
            state["snapshots"] = {str(i): self._view(v) for i, v in self.snapshots.items()}
            self._save(state)
            self.session.commit()
            return True
        except Exception as exc:
            self._fail(exc)
            raise

    def poll(self, *, batch_size=500) -> int:
        state = self._state()
        events = live_events(self.session, self.instrument_ids, since=instant(state["started_at"]),
                   through=instant(self.clock()), cursor=FeedCursor(state["quote_id"], state["trade_id"]), batch_size=batch_size)
        count = sum(self.process(event) for event in events)
        self.tick()
        return count

    def tick(self):
        """Refresh risk during quiet feeds. Never cancel orders on silence/exit."""
        self.time = instant(self.clock())
        try:
            self._lock()
            self._restore_views(self._state())
            self._refresh()
            self.session.commit()
        except Exception as exc:
            self._fail(exc)
            raise

    def finish(self):
        """Explicitly finish a flat experiment; open orders/positions require management."""
        self.time = instant(self.clock())
        try:
            self._lock()
            self._trial()
            if self._orders() or self.ledger.open_positions(strategy_id=self.strategy_id, mode="paper"):
                raise ValueError("Cannot complete a trial with outstanding orders or positions")
            self.strategy.on_finish(self.ctx)
            self.ledger.finalize_trial(self.trial_id)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _fail(self, exc):
        self.session.rollback()
        if self.trial_id is not None:
            trial = self.session.get(Trial, self.trial_id)
            if trial and trial.status == "running":
                self.ledger.finalize_trial(trial.id, status="failed")
                trial.notes = f"Paper runtime failed: {type(exc).__name__}. Resting orders retained."
                self.risk.log_incident(severity="warning", category="other", mode="paper",
                    strategy_id=self.strategy_id, message=trial.notes, ts=self.time)
                self.session.commit()
