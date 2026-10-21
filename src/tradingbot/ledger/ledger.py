"""The ledger: the single source of truth for orders, fills, fees and P&L.

Records every order and fill, computes exact fees (via the per-venue models),
snapshots the USD/GBP rate on each fill for tax (PRD §10), and keeps the
``positions`` table as a materialised average-cost book. Reporting produces
per-strategy P&L after fees, a trade count, and the luck p-value (PRD §4).

Usage::

    with session_scope() as s:
        led = Ledger(s)
        order = led.record_order(instrument_id=iid, mode="paper", side="buy",
                                 order_type="limit", size=Decimal("10"),
                                 strategy_id=sid, limit_price=Decimal("0.40"))
        led.record_fill(order=order, price=Decimal("0.40"), size=Decimal("10"),
                        liquidity="maker", fill_ts=ts)   # fee auto-computed
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import enums
from ..db.models import Fill, FxRate, Instrument, Order, Position, Trial, Venue
from ..fees import FeeFill, OrderFeeModel
from . import accounting
from .accounting import FillEvent, PositionState
from .fee_models import fee_model_for_venue
from .stats import luck_probability, max_drawdown

ZERO = Decimal(0)
ONE = Decimal(1)


class Ledger:
    """Order/fill/position/P&L bookkeeping bound to one SQLAlchemy ``Session``.

    ``auto_fee`` computes prediction-market fees from the venue model when a fill
    is recorded without an explicit ``fee`` (correct for backtest/paper where all
    of an order's fills flow through this instance in order). For live trading,
    pass the venue-reported ``fee`` explicitly.
    """

    def __init__(
        self,
        session: Session,
        *,
        auto_fee: bool = True,
        fee_schedules: dict[str, object] | None = None,
    ) -> None:
        self.session = session
        self.auto_fee = auto_fee
        self._fee_schedules = fee_schedules or {}
        self._fee_models: dict[int, OrderFeeModel | None] = {}
        self._instrument_info: dict[int, tuple[str, Decimal]] = {}

    # -- internals ----------------------------------------------------------
    def _info(self, instrument_id: int) -> tuple[str, Decimal]:
        """Return (venue_key, contract_multiplier) for an instrument, cached."""
        cached = self._instrument_info.get(instrument_id)
        if cached is not None:
            return cached
        row = self.session.execute(
            select(Venue.key, Instrument.contract_multiplier)
            .join(Instrument, Instrument.venue_id == Venue.id)
            .where(Instrument.id == instrument_id)
        ).one()
        info = (row[0], row[1] if row[1] is not None else ONE)
        self._instrument_info[instrument_id] = info
        return info

    def _fee_model(self, order: Order, venue_key: str) -> OrderFeeModel | None:
        if order.id not in self._fee_models:
            schedule = self._fee_schedules.get(venue_key)
            self._fee_models[order.id] = fee_model_for_venue(
                venue_key, schedule=schedule
            )
        return self._fee_models[order.id]

    def _compute_fee(
        self,
        order: Order,
        venue_key: str,
        *,
        price: Decimal,
        size: Decimal,
        side: str,
        liquidity: str,
        fill_ts: datetime,
    ) -> Decimal:
        model = self._fee_model(order, venue_key)
        if model is None:
            return ZERO  # commission-free venue
        if liquidity not in (enums.Liquidity.MAKER, enums.Liquidity.TAKER):
            raise ValueError(
                f"Cannot compute {venue_key} fee for liquidity={liquidity!r}; "
                "pass an explicit fee or a maker/taker fill"
            )
        breakdown = model.charge(
            FeeFill(
                price=price,
                quantity=size,
                liquidity=liquidity,
                side=side,
                executed_at=fill_ts,
            )
        )
        return breakdown.net_fee

    def _latest_fx_rate(
        self, base: str, quote: str, as_of: datetime
    ) -> Decimal | None:
        return self.session.scalar(
            select(FxRate.rate)
            .where(FxRate.base == base, FxRate.quote == quote, FxRate.ts <= as_of)
            .order_by(FxRate.ts.desc())
            .limit(1)
        )

    # -- writes -------------------------------------------------------------
    def record_order(
        self,
        *,
        instrument_id: int,
        mode: str,
        side: str,
        order_type: str,
        size: Decimal,
        strategy_id: int | None = None,
        trial_id: int | None = None,
        limit_price: Decimal | None = None,
        intended_liquidity: str = enums.Liquidity.UNKNOWN,
        status: str = enums.OrderStatus.OPEN,
        venue_order_id: str | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> Order:
        order = Order(
            instrument_id=instrument_id,
            mode=mode,
            side=side,
            order_type=order_type,
            size=size,
            strategy_id=strategy_id,
            trial_id=trial_id,
            limit_price=limit_price,
            intended_liquidity=intended_liquidity,
            status=status,
            venue_order_id=venue_order_id,
            reason=reason,
            metadata_=metadata,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def record_fill(
        self,
        *,
        order: Order,
        price: Decimal,
        size: Decimal,
        liquidity: str,
        fill_ts: datetime,
        side: str | None = None,
        fee: Decimal | None = None,
        usd_gbp_rate: Decimal | None = None,
        venue_fill_id: str | None = None,
        metadata: dict | None = None,
    ) -> Fill:
        """Record one execution: insert the fill, update the order, and update the
        position (realizing P&L on any reduction). Returns the persisted ``Fill``.
        """
        side = side or order.side
        venue_key, multiplier = self._info(order.instrument_id)

        if fee is None:
            fee = (
                self._compute_fee(
                    order,
                    venue_key,
                    price=price,
                    size=size,
                    side=side,
                    liquidity=liquidity,
                    fill_ts=fill_ts,
                )
                if self.auto_fee
                else ZERO
            )

        if usd_gbp_rate is None:
            usd_gbp_rate = self._latest_fx_rate("USD", "GBP", fill_ts)

        notional = price * size * multiplier

        # --- update the position and get the realized P&L for this fill ---
        realized = ZERO
        if order.strategy_id is not None:
            realized = self._apply_to_position(
                strategy_id=order.strategy_id,
                mode=order.mode,
                instrument_id=order.instrument_id,
                side=side,
                price=price,
                size=size,
                fee=fee,
                multiplier=multiplier,
                ts=fill_ts,
            )

        fill = Fill(
            order_id=order.id,
            strategy_id=order.strategy_id,
            trial_id=order.trial_id,
            instrument_id=order.instrument_id,
            mode=order.mode,
            side=side,
            price=price,
            size=size,
            notional=notional,
            fee=fee,
            liquidity=liquidity,
            venue_fill_id=venue_fill_id,
            fill_ts=fill_ts,
            usd_gbp_rate=usd_gbp_rate,
            realized_pnl=realized,
            metadata_=metadata,
        )
        self.session.add(fill)

        self._update_order_fill_state(order, price=price, size=size, ts=fill_ts)
        self.session.flush()
        return fill

    def _update_order_fill_state(
        self, order: Order, *, price: Decimal, size: Decimal, ts: datetime
    ) -> None:
        prev_filled = order.filled_size or ZERO
        new_filled = prev_filled + size
        prev_avg = order.avg_fill_price or ZERO
        order.avg_fill_price = (prev_avg * prev_filled + price * size) / new_filled
        order.filled_size = new_filled
        if new_filled >= order.size:
            order.status = enums.OrderStatus.FILLED
            order.closed_ts = ts
        else:
            order.status = enums.OrderStatus.PARTIALLY_FILLED

    def _apply_to_position(
        self,
        *,
        strategy_id: int,
        mode: str,
        instrument_id: int,
        side: str,
        price: Decimal,
        size: Decimal,
        fee: Decimal,
        multiplier: Decimal,
        ts: datetime,
    ) -> Decimal:
        pos = self.get_position(strategy_id, mode, instrument_id)
        if pos is None:
            pos = Position(
                strategy_id=strategy_id,
                mode=mode,
                instrument_id=instrument_id,
                quantity=ZERO,
                avg_price=ZERO,
                realized_pnl=ZERO,
                fees_paid=ZERO,
                status=enums.PositionStatus.OPEN,
                opened_ts=ts,
            )
            self.session.add(pos)
            self.session.flush()

        state = PositionState(
            quantity=pos.quantity or ZERO,
            avg_price=pos.avg_price or ZERO,
            realized_pnl=pos.realized_pnl or ZERO,
            fees_paid=pos.fees_paid or ZERO,
        )
        was_flat = state.is_flat
        result = accounting.apply_fill(state, side, price, size, fee, multiplier)
        new = result.state

        if was_flat and pos.opened_ts is None:
            pos.opened_ts = ts
        pos.quantity = new.quantity
        pos.avg_price = new.avg_price
        pos.cost_basis = new.cost_basis(multiplier)
        pos.realized_pnl = new.realized_pnl
        pos.fees_paid = new.fees_paid
        if new.is_flat:
            pos.status = enums.PositionStatus.CLOSED
            pos.closed_ts = ts
        else:
            pos.status = enums.PositionStatus.OPEN
            pos.closed_ts = None
        return result.realized_pnl

    def settle_position(
        self,
        *,
        strategy_id: int,
        mode: str,
        instrument_id: int,
        settlement_price: Decimal,
        settle_ts: datetime,
        trial_id: int | None = None,
    ) -> Fill | None:
        """Close a held position at settlement (hold-to-settlement strategies).

        Records a synthetic, fee-free settlement order+fill so the round-trip and
        luck statistics include the settlement P&L. Returns ``None`` if flat.
        """
        pos = self.get_position(strategy_id, mode, instrument_id)
        if pos is None or pos.quantity == ZERO:
            return None
        closing_side = (
            enums.Side.SELL if pos.quantity > ZERO else enums.Side.BUY
        )
        size = abs(pos.quantity)
        order = self.record_order(
            instrument_id=instrument_id,
            mode=mode,
            side=closing_side,
            order_type=enums.OrderType.MARKET,
            size=size,
            strategy_id=strategy_id,
            trial_id=trial_id,
            intended_liquidity=enums.Liquidity.TAKER,
            status=enums.OrderStatus.FILLED,
            reason="settlement",
        )
        return self.record_fill(
            order=order,
            price=settlement_price,
            size=size,
            liquidity=enums.Liquidity.TAKER,
            fill_ts=settle_ts,
            fee=ZERO,
            metadata={"settlement": True},
        )

    def mark_position(
        self, position: Position, last_price: Decimal, *, multiplier: Decimal | None = None
    ) -> Decimal:
        """Mark a position to ``last_price`` and store its unrealized P&L."""
        if multiplier is None:
            _, multiplier = self._info(position.instrument_id)
        state = PositionState(
            quantity=position.quantity or ZERO, avg_price=position.avg_price or ZERO
        )
        position.last_price = last_price
        position.unrealized_pnl = state.unrealized(last_price, multiplier)
        return position.unrealized_pnl

    # -- reads / reporting --------------------------------------------------
    def get_position(
        self, strategy_id: int, mode: str, instrument_id: int
    ) -> Position | None:
        return self.session.scalar(
            select(Position).where(
                Position.strategy_id == strategy_id,
                Position.mode == mode,
                Position.instrument_id == instrument_id,
            )
        )

    def open_positions(
        self, *, mode: str | None = None, strategy_id: int | None = None
    ) -> list[Position]:
        stmt = select(Position).where(Position.status == enums.PositionStatus.OPEN)
        if mode is not None:
            stmt = stmt.where(Position.mode == mode)
        if strategy_id is not None:
            stmt = stmt.where(Position.strategy_id == strategy_id)
        return list(self.session.scalars(stmt))

    def realized_after_fees(
        self,
        *,
        strategy_id: int | None = None,
        mode: str | None = None,
        trial_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Decimal:
        """Sum of realized gross P&L minus all fees over matching fills.

        ``since``/``until`` bound ``fill_ts`` (``since`` inclusive, ``until``
        exclusive) — used by the risk engine for a single day's realized P&L.
        """
        stmt = select(
            func.coalesce(func.sum(Fill.realized_pnl), 0),
            func.coalesce(func.sum(Fill.fee), 0),
        )
        if strategy_id is not None:
            stmt = stmt.where(Fill.strategy_id == strategy_id)
        if mode is not None:
            stmt = stmt.where(Fill.mode == mode)
        if trial_id is not None:
            stmt = stmt.where(Fill.trial_id == trial_id)
        if since is not None:
            stmt = stmt.where(Fill.fill_ts >= since)
        if until is not None:
            stmt = stmt.where(Fill.fill_ts < until)
        realized, fees = self.session.execute(stmt).one()
        return Decimal(realized) - Decimal(fees)

    def _trips_from_grouped(
        self, by_instrument: dict[int, list[Fill]]
    ) -> list[accounting.RoundTrip]:
        """Replay fills grouped by instrument into completed round trips, ordered
        globally by exit time (so the equity curve / drawdown is chronological)."""
        trips: list[accounting.RoundTrip] = []
        for instrument_id, inst_fills in by_instrument.items():
            _, multiplier = self._info(instrument_id)
            events = [
                FillEvent(
                    side=f.side, price=f.price, size=f.size,
                    fee=f.fee or ZERO, fill_ts=f.fill_ts,
                )
                for f in inst_fills
            ]
            trips.extend(accounting.iter_round_trips(events, multiplier))
        trips.sort(key=lambda t: t.exit_ts)
        return trips

    def round_trips(
        self, *, strategy_id: int, mode: str, trial_id: int | None = None
    ) -> list[accounting.RoundTrip]:
        """All completed round trips for the scope, time-ordered by exit. Each
        carries entry/exit ts, gross P&L and fees (``net_pnl`` is after fees). The
        unit for the drawdown and per-regime report (tradingbot-l0v)."""
        stmt = select(Fill).where(Fill.strategy_id == strategy_id, Fill.mode == mode)
        if trial_id is not None:
            stmt = stmt.where(Fill.trial_id == trial_id)
        stmt = stmt.order_by(Fill.instrument_id, Fill.fill_ts, Fill.id)
        by_instrument: dict[int, list[Fill]] = {}
        for f in self.session.scalars(stmt):
            by_instrument.setdefault(f.instrument_id, []).append(f)
        return self._trips_from_grouped(by_instrument)

    def strategy_report(
        self,
        *,
        strategy_id: int,
        mode: str,
        trial_id: int | None = None,
    ) -> dict:
        """Per-strategy P&L after fees, trade count, luck p-value, and max
        drawdown (PRD §4).

        ``trade_count`` is the number of completed round trips; the luck p-value
        is a one-sample t-test of round-trip net P&L against a zero-edge null;
        ``max_drawdown`` is the worst peak-to-trough fall of the cumulative net
        P&L (filter survivors on drawdown, not just return — tradingbot-l0v).
        """
        stmt = (
            select(Fill)
            .where(Fill.strategy_id == strategy_id, Fill.mode == mode)
            .order_by(Fill.instrument_id, Fill.fill_ts, Fill.id)
        )
        if trial_id is not None:
            stmt = stmt.where(Fill.trial_id == trial_id)
        fills = list(self.session.scalars(stmt))

        by_instrument: dict[int, list[Fill]] = {}
        gross = fees_total = ZERO
        for f in fills:
            by_instrument.setdefault(f.instrument_id, []).append(f)
            gross += f.realized_pnl or ZERO
            fees_total += f.fee or ZERO

        trips = self._trips_from_grouped(by_instrument)
        net_pnls = [t.net_pnl for t in trips]  # time-ordered by exit

        return {
            "strategy_id": strategy_id,
            "mode": mode,
            "trial_id": trial_id,
            "fill_count": len(fills),
            "trade_count": len(net_pnls),  # completed round trips
            "pnl": gross,  # gross realized (excludes fees)
            "fees_total": fees_total,
            "pnl_after_fees": gross - fees_total,
            "max_drawdown": max_drawdown(net_pnls),
            "luck_p_value": luck_probability(net_pnls),
        }

    def finalize_trial(
        self, trial_id: int, *, status: str = enums.TrialStatus.COMPLETE
    ) -> Trial:
        """Compute the report for a trial's fills and write it onto the Trial row."""
        trial = self.session.get(Trial, trial_id)
        if trial is None:
            raise ValueError(f"No trial {trial_id}")
        report = self.strategy_report(
            strategy_id=trial.strategy_id, mode=trial.mode, trial_id=trial_id
        )
        trial.pnl = report["pnl"]
        trial.pnl_after_fees = report["pnl_after_fees"]
        trial.fees_total = report["fees_total"]
        trial.trade_count = report["trade_count"]
        trial.max_drawdown = report["max_drawdown"]
        lp = report["luck_p_value"]
        trial.luck_p_value = Decimal(str(lp)) if lp is not None else None
        trial.status = status
        trial.completed_ts = func.now()
        self.session.flush()
        return trial
