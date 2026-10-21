"""The backtester: run a :class:`~tradingbot.strategy.interface.Strategy` over a
time-ordered market-event stream, through the *same* risk gate and ledger the
live path uses (PRD §4).

The strategy only ever sees a :class:`StrategyContext` and returns intents. The
engine is the runtime: it applies the §6 risk veto to every intent (read-only —
it never trips or writes a halt), records allowed orders and their fills through
the :class:`~tradingbot.ledger.ledger.Ledger` (so fees, positions, P&L and the
luck p-value are computed by the one source of truth), simulates maker fills with
the strict trade-through model, and writes a :class:`~tradingbot.db.models.Trial`
row — including runs that lose money (PRD §4 requires every variant logged).

Per-event ordering matters for causality: a trade first fills orders that were
resting *before* it, then the strategy reacts to that same trade. Orders the
strategy places in reaction can only fill on *later* trades — no look-ahead.

Scope note: the ``positions`` table is keyed by (strategy, mode, instrument), not
by trial, so a backtest run assumes it starts flat for that scope. Run backtests
in isolation (a fresh/rolled-back DB, or distinct strategies) — the paper/live
runtimes share one real book, which is correct there.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ..db import enums
from ..db.models import Order, Trial
from ..ledger.ledger import Ledger
from ..risk.engine import RiskEngine
from ..strategy.interface import (
    CancelOrder,
    Intent,
    MarketEvent,
    MarketSnapshot,
    PlaceOrder,
    Strategy,
    StrategyContext,
)
from .fills import RestingOrder, match_trade_through, taker_fill_price
from .holdout import HoldoutSplit, HoldoutViolation, claim_final, json_value, register_split, strategy_identity, utc

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Settlement:
    """A hold-to-settlement close: mark the position to ``price`` at ``ts``."""

    instrument_id: int
    price: Decimal
    ts: datetime


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trial_id: int
    report: dict
    orders_placed: int
    orders_rejected: int
    fills: int


class _RuntimeContext(StrategyContext):
    """Concrete context backed by the engine's live state and the ledger. The same
    shape the paper/live runtimes will present."""

    def __init__(
        self,
        *,
        mode: str,
        params: dict,
        ledger: Ledger,
        strategy_id: int,
        resting: dict[str, RestingOrder],
        books: dict[int, MarketSnapshot],
    ) -> None:
        self._mode = mode
        self._params = params
        self._ledger = ledger
        self._strategy_id = strategy_id
        self._resting = resting
        self._books = books
        self._now: datetime | None = None

    @property
    def now(self) -> datetime:
        assert self._now is not None, "context clock read before the first event"
        return self._now

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def params(self) -> dict:
        return self._params

    def position(self, instrument_id: int) -> Decimal:
        pos = self._ledger.get_position(self._strategy_id, self._mode, instrument_id)
        if pos is None or pos.quantity is None:
            return ZERO
        return pos.quantity

    def snapshot(self, instrument_id: int) -> MarketSnapshot | None:
        return self._books.get(instrument_id)

    def resting_tags(self, instrument_id: int | None = None) -> tuple[str, ...]:
        return tuple(
            r.tag for r in self._resting.values()
            if instrument_id is None or r.instrument_id == instrument_id
        )


class Backtester:
    def __init__(
        self,
        session: Session,
        *,
        strategy: Strategy,
        strategy_id: int,
        mode: str = enums.Mode.BACKTEST,
        fee_schedules: dict[str, object] | None = None,
    ) -> None:
        self.session = session
        self.strategy = strategy
        self.version_strategy = strategy
        self.version_context = {"fee_schedules": {
            key: asdict(value) if is_dataclass(value) else vars(value)
            for key, value in (fee_schedules or {}).items()}}
        self.strategy_id = strategy_id
        self.mode = mode
        self.last_trial_id = None
        self.ledger = Ledger(session, auto_fee=True, fee_schedules=fee_schedules)
        self.risk = RiskEngine(session)

    def run(
        self,
        events: Iterable[MarketEvent],
        *,
        split: HoldoutSplit,
        final_holdout: bool = False,
        version_params: dict | None = None,
        settlements: Sequence[Settlement] | None = None,
        params: dict | None = None,
        data_start: datetime | None = None,
        data_end: datetime | None = None,
        notes: str | None = None,
    ) -> BacktestResult:
        if self.mode != enums.Mode.BACKTEST:
            raise HoldoutViolation("historical replay must use backtest mode")
        if not isinstance(split, HoldoutSplit) or type(final_holdout) is not bool:
            raise HoldoutViolation("an explicit HoldoutSplit and boolean final_holdout are required")
        params = params if params is not None else dict(self.strategy.params)
        version, identity = strategy_identity(self.version_strategy, type(self),
                                             {"runtime": self.version_context, "run": version_params or {}},
                                             (type(self.ledger), type(self.risk)))
        trial_params = {**json_value(params), "_holdout": {**split.metadata(), "final_holdout": final_holdout,
                         "strategy_version": version, "identity": identity}}
        if final_holdout:
            # Claim before consuming the iterable: even a failed replay exposes
            # the held-out observations and therefore consumes the sole attempt.
            trial_id = claim_final(self.session, split=split, strategy_id=self.strategy_id,
                                   version=version, params=trial_params, notes=notes)
            trial = self.session.get(Trial, trial_id)
        else:
            register_split(self.session, split)
            trial = Trial(strategy_id=self.strategy_id, mode=self.mode, params=trial_params,
                          dataset_key=split.dataset_key, holdout_start=split.holdout_start,
                          strategy_version=version, final_holdout=False,
                          status=enums.TrialStatus.RUNNING, notes=notes)
            self.session.add(trial)
            self.session.flush()
        self.last_trial_id = trial.id
        try:
            events = list(events)
            previous = None
            for event in events:
                split.require(event.time, final_holdout=final_holdout)
                if previous is not None and utc(event.time) < previous:
                    raise HoldoutViolation("events must be chronological")
                previous = utc(event.time)
            for settlement in settlements or ():
                split.require(settlement.ts, final_holdout=final_holdout)
            if len({s.instrument_id for s in settlements or ()}) != len(settlements or ()):
                raise ValueError("one terminal settlement per instrument is required")
        except Exception as error:
            trial.status = enums.TrialStatus.FAILED
            trial.notes = (trial.notes or "") + f"\nReplay validation refused: {type(error).__name__}: {error}"
            self.session.flush()
            raise
        if events:
            data_start = data_start or events[0].time
            data_end = data_end or events[-1].time
        for boundary in (data_start, data_end):
            if boundary is not None:
                split.require(boundary, final_holdout=final_holdout)
        trial.data_start, trial.data_end = data_start, data_end
        self.session.flush()
        try:
            return self._run_trial(events, settlements, trial)
        except Exception as error:
            if self.session.is_active:
                trial.status = enums.TrialStatus.FAILED
                trial.notes = (trial.notes or "") + f"\nReplay failed: {type(error).__name__}: {error}"
                self.session.flush()
            raise

    def _run_trial(self, events, settlements, trial):
        resting: dict[str, RestingOrder] = {}
        order_by_tag: dict[str, Order] = {}
        books: dict[int, MarketSnapshot] = {}
        ctx = _RuntimeContext(
            mode=self.mode, params=self.strategy.params, ledger=self.ledger,
            strategy_id=self.strategy_id, resting=resting, books=books,
        )
        counters = {"placed": 0, "rejected": 0, "fills": 0}
        pending = iter(sorted(settlements or (), key=lambda s: (utc(s.ts), s.instrument_id)))
        next_settlement = next(pending, None)
        settled = set()

        self.strategy.on_start(ctx)
        for event in events:
            while next_settlement is not None and utc(next_settlement.ts) <= utc(event.time):
                self._settle(next_settlement, ctx, resting, order_by_tag, trial)
                settled.add(next_settlement.instrument_id)
                next_settlement = next(pending, None)
            if event.instrument_id in settled:
                continue  # A terminal instrument cannot be traded again.
            ctx._now = event.time
            self._replay_time = event.time
            self._before_event(event, ctx, resting, order_by_tag, trial, counters)
            if (
                event.is_trade and event.maker_fill_eligible
                and event.price is not None and event.size is not None
            ):
                self._apply_trade_fills(event, resting, order_by_tag, counters)
            books[event.instrument_id] = _merge_snapshot(books.get(event.instrument_id), event)
            self._after_event(event, ctx, resting, order_by_tag, trial, counters)
            for intent in self.strategy.on_event(ctx, event) or ():
                self._handle_intent(intent, ctx, resting, order_by_tag, trial, counters)
        while next_settlement is not None:
            self._settle(next_settlement, ctx, resting, order_by_tag, trial)
            next_settlement = next(pending, None)
        self.strategy.on_finish(ctx)

        self.ledger.finalize_trial(trial.id)
        report = self.ledger.strategy_report(
            strategy_id=self.strategy_id, mode=self.mode, trial_id=trial.id
        )
        report["holdout"] = {key: value for key, value in trial.params["_holdout"].items() if key != "identity"}
        return BacktestResult(
            trial_id=trial.id, report=report,
            orders_placed=counters["placed"], orders_rejected=counters["rejected"],
            fills=counters["fills"],
        )

    def _before_event(self, event, ctx, resting, order_by_tag, trial, counters):
        """Replay instrumentation hook, before any trade can fill a resting order."""

    def _after_event(self, event, ctx, resting, order_by_tag, trial, counters):
        """Observe risk after existing orders meet the print, before new decisions."""

    def _settle(self, settlement, ctx, resting, order_by_tag, trial):
        ctx._now = settlement.ts
        self._replay_time = settlement.ts
        for tag in tuple(ctx.resting_tags(settlement.instrument_id)):
            self._handle_intent(CancelOrder(tag), ctx, resting, order_by_tag, trial, {})
        fill = self.ledger.settle_position(
            strategy_id=self.strategy_id, mode=self.mode,
            instrument_id=settlement.instrument_id, settlement_price=settlement.price,
            settle_ts=settlement.ts, trial_id=trial.id,
        )
        if fill is not None:
            fill.order.created_ts = fill.order.submitted_ts = settlement.ts

    # -- fills from a public trade ------------------------------------------
    def _apply_trade_fills(self, event, resting, order_by_tag, counters) -> None:
        here = [r for r in resting.values() if r.instrument_id == event.instrument_id
                and utc(order_by_tag[r.tag].created_ts) < utc(event.time)]
        if not here:
            return
        for pf in match_trade_through(here, trade_price=event.price, trade_size=event.size):
            order = order_by_tag[pf.tag]
            self.ledger.record_fill(
                order=order, price=pf.price, size=pf.size,
                liquidity=enums.Liquidity.MAKER, fill_ts=event.time,
                metadata={"tag": pf.tag, "trade_through": str(event.price),
                          "public_trade_id": event.meta.get("trade_id"),
                          "source_execution_identity": event.meta.get("execution_identity")},
            )
            counters["fills"] += 1
            r = resting[pf.tag]
            r.remaining -= pf.size
            if r.remaining <= ZERO:
                del resting[pf.tag]

    # -- intents -------------------------------------------------------------
    def _handle_intent(self, intent, ctx, resting, order_by_tag, trial, counters) -> None:
        if isinstance(intent, CancelOrder):
            r = resting.pop(intent.tag, None)
            if r is not None:
                order = order_by_tag.get(intent.tag)
                if order is not None:
                    order.status = enums.OrderStatus.CANCELED
                    order.closed_ts = ctx.now
            return
        if not isinstance(intent, PlaceOrder):
            raise TypeError(f"unknown intent {type(intent).__name__}")

        tag = intent.tag or None
        if tag is not None and tag in resting:
            return  # a live order already rests under this tag

        snapshot = ctx.snapshot(intent.instrument_id)
        risk_price = (
            intent.limit_price if intent.limit_price is not None
            else taker_fill_price(intent.side, snapshot)
        )
        if risk_price is None:
            return  # no price to evaluate or fill against; drop silently

        decision = self.risk.evaluate_order(
            instrument_id=intent.instrument_id, mode=self.mode, side=intent.side,
            size=intent.size, price=risk_price, strategy_id=self.strategy_id, now=ctx.now,
        )
        if not decision.allowed:
            self._record_order(intent, trial, status=enums.OrderStatus.REJECTED,
                               reason="; ".join(decision.reasons))
            counters["rejected"] += 1
            return

        order = self._record_order(intent, trial, status=enums.OrderStatus.OPEN,
                                   reason=intent.reason)
        counters["placed"] += 1

        is_taker = (
            intent.order_type == enums.OrderType.MARKET
            or intent.intended_liquidity == enums.Liquidity.TAKER
        )
        if is_taker:
            price = taker_fill_price(intent.side, snapshot)
            if price is None:
                order.status = enums.OrderStatus.CANCELED
                return
            self.ledger.record_fill(
                order=order, price=price, size=intent.size,
                liquidity=enums.Liquidity.TAKER, fill_ts=ctx.now,
                metadata={"tag": tag} if tag else None,
            )
            counters["fills"] += 1
        else:
            key = tag or f"auto-{order.id}"
            resting[key] = RestingOrder(
                tag=key, order_id=order.id, instrument_id=intent.instrument_id,
                side=intent.side, limit_price=intent.limit_price, remaining=intent.size,
            )
            order_by_tag[key] = order

    def _record_order(self, intent: PlaceOrder, trial: Trial, *, status: str,
                      reason: str | None) -> Order:
        order = self.ledger.record_order(
            instrument_id=intent.instrument_id, mode=self.mode, side=intent.side,
            order_type=intent.order_type, size=intent.size, strategy_id=self.strategy_id,
            trial_id=trial.id, limit_price=intent.limit_price,
            intended_liquidity=intent.intended_liquidity, status=status, reason=reason,
            metadata={"tag": intent.tag} if intent.tag else None,
        )
        order.created_ts = self._replay_time
        if status != enums.OrderStatus.REJECTED:
            order.submitted_ts = self._replay_time
        return order


def _merge_snapshot(prev: MarketSnapshot | None, event: MarketEvent) -> MarketSnapshot:
    """Carry the last-known book forward across events. A quote replaces the book
    fields (a fresh top-of-book) but keeps the last trade; a trade updates only
    the last price."""
    last = prev.last if prev is not None else None
    if event.is_trade:
        return MarketSnapshot(
            instrument_id=event.instrument_id, time=event.time,
            bid=prev.bid if prev else None, ask=prev.ask if prev else None,
            mid=prev.mid if prev else None, last=event.price,
            bid_size=prev.bid_size if prev else None,
            ask_size=prev.ask_size if prev else None,
        )
    return MarketSnapshot(
        instrument_id=event.instrument_id, time=event.time,
        bid=event.bid, ask=event.ask, mid=event.mid, last=last,
        bid_size=event.bid_size, ask_size=event.ask_size,
    )
