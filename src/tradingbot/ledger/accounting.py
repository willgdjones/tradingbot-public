"""Pure position accounting — no database, no I/O, exact ``Decimal`` maths.

Average-cost method. Realized P&L is *gross* (price move only); fees are tracked
separately so "profit after all fees" (PRD §4) is ``realized - fees``. Positive
fees reduce P&L; a negative fee is a maker rebate and adds to it.

Quantities are signed: positive is long, negative is short. Prices are in the
instrument's own units (dollars per share for equities; dollars per contract,
0..1, for prediction markets). ``multiplier`` scales price*size into money
(1 for shares/PM contracts, 100 for equity options).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from ..db.enums import Side

ZERO = Decimal(0)


def _signed(side: str, size: Decimal) -> Decimal:
    if side == Side.BUY:
        return size
    if side == Side.SELL:
        return -size
    raise ValueError(f"Unknown side: {side!r}")


@dataclass(frozen=True, slots=True)
class PositionState:
    """Running state of one (strategy, mode, instrument) position."""

    quantity: Decimal = ZERO  # signed
    avg_price: Decimal = ZERO  # avg price of the currently-open position; 0 if flat
    realized_pnl: Decimal = ZERO  # cumulative gross realized (excludes fees)
    fees_paid: Decimal = ZERO  # cumulative net fees (positive = expense)

    @property
    def is_flat(self) -> bool:
        return self.quantity == ZERO

    @property
    def net_realized(self) -> Decimal:
        """Realized P&L after fees."""
        return self.realized_pnl - self.fees_paid

    def cost_basis(self, multiplier: Decimal = Decimal(1)) -> Decimal:
        """Capital currently deployed in the open position."""
        return self.avg_price * abs(self.quantity) * multiplier

    def unrealized(self, last_price: Decimal, multiplier: Decimal = Decimal(1)) -> Decimal:
        """Mark-to-market P&L of the open position at ``last_price``."""
        if self.is_flat:
            return ZERO
        return (last_price - self.avg_price) * self.quantity * multiplier


@dataclass(frozen=True, slots=True)
class FillResult:
    state: PositionState
    realized_pnl: Decimal  # gross realized by this fill (0 unless it reduced/closed)


def apply_fill(
    state: PositionState,
    side: str,
    price: Decimal,
    size: Decimal,
    fee: Decimal = ZERO,
    multiplier: Decimal = Decimal(1),
) -> FillResult:
    """Apply one execution to ``state`` and return the new state + realized P&L.

    Handles opening, increasing, partial close, full close, and flipping through
    zero (the closed portion realizes; the remainder opens at ``price``).
    """
    if size <= 0:
        raise ValueError("Fill size must be positive")

    signed = _signed(side, size)
    q, a = state.quantity, state.avg_price
    realized = ZERO

    if q == ZERO or (q > ZERO) == (signed > ZERO):
        # Opening from flat, or increasing an existing position.
        new_qty = q + signed
        total_abs = abs(q) + size
        new_avg = (a * abs(q) + price * size) / total_abs
    else:
        # Reducing, closing, or flipping.
        closing = min(size, abs(q))
        sign_q = Decimal(1) if q > ZERO else Decimal(-1)
        realized = (price - a) * closing * sign_q * multiplier
        new_qty = q + signed
        if new_qty == ZERO:
            new_avg = ZERO
        elif (new_qty > ZERO) == (q > ZERO):
            new_avg = a  # still same side, just smaller
        else:
            new_avg = price  # flipped: remainder is a fresh position at price

    new_state = replace(
        state,
        quantity=new_qty,
        avg_price=new_avg,
        realized_pnl=state.realized_pnl + realized,
        fees_paid=state.fees_paid + fee,
    )
    return FillResult(state=new_state, realized_pnl=realized)


def settle(
    state: PositionState,
    settlement_price: Decimal,
    multiplier: Decimal = Decimal(1),
) -> FillResult:
    """Realize the entire open position at a settlement price (no trading fee).

    Used by hold-to-settlement strategies (#1, #3, #4). For binary prediction
    markets ``settlement_price`` is 0 or 1.
    """
    if state.is_flat:
        return FillResult(state=state, realized_pnl=ZERO)
    sign_q = Decimal(1) if state.quantity > ZERO else Decimal(-1)
    realized = (settlement_price - state.avg_price) * abs(state.quantity) * sign_q * multiplier
    new_state = replace(
        state,
        quantity=ZERO,
        avg_price=ZERO,
        realized_pnl=state.realized_pnl + realized,
    )
    return FillResult(state=new_state, realized_pnl=realized)


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """A completed trade: a position opened from flat and returned to flat (or
    flipped through zero). ``net_pnl`` is after fees — the unit for the luck
    (p-value) test and the trade count in PRD §4."""

    entry_ts: datetime | None
    exit_ts: datetime
    gross_pnl: Decimal
    fees: Decimal

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees


@dataclass
class _OpenCycle:
    entry_ts: datetime | None = None
    gross: Decimal = ZERO
    fees: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class FillEvent:
    """Minimal fill shape for replaying round trips (order-independent of the ORM)."""

    side: str
    price: Decimal
    size: Decimal
    fee: Decimal
    fill_ts: datetime


def iter_round_trips(
    fills: list[FillEvent],
    multiplier: Decimal = Decimal(1),
) -> list[RoundTrip]:
    """Replay one instrument's fills (already time-ordered) into round trips.

    A round trip is emitted whenever the position returns to flat or flips sign.
    A still-open position at the end is *not* emitted (incomplete trade). Fees of
    every fill in a cycle are attributed to that cycle's round trip.
    """
    state = PositionState()
    cycle = _OpenCycle()
    trips: list[RoundTrip] = []

    for f in fills:
        was_flat = state.is_flat
        prev_qty = state.quantity
        result = apply_fill(state, f.side, f.price, f.size, f.fee, multiplier)
        state = result.state

        if was_flat:
            cycle.entry_ts = f.fill_ts
        cycle.gross += result.realized_pnl
        cycle.fees += f.fee

        crossed_to_flat = prev_qty != ZERO and state.is_flat
        flipped = (
            prev_qty != ZERO
            and not state.is_flat
            and (prev_qty > ZERO) != (state.quantity > ZERO)
        )
        if crossed_to_flat or flipped:
            trips.append(
                RoundTrip(
                    entry_ts=cycle.entry_ts,
                    exit_ts=f.fill_ts,
                    gross_pnl=cycle.gross,
                    fees=cycle.fees,
                )
            )
            # A flip starts a new open cycle at this same fill.
            cycle = _OpenCycle(entry_ts=f.fill_ts if flipped else None)

    return trips
