"""The backtest fill model (PRD §7), pure and unit-tested.

The one rule that defines a faithful maker backtest: **a resting maker order is
filled only when a later public trade goes strictly *through* its price.** A
resting BUY at ``L`` fills when a trade prints below ``L`` (someone sold through
your bid); a resting SELL at ``L`` fills when a trade prints above ``L``. The
fill price is your resting limit ``L`` — you posted it, you get it.

A single trade's size is finite, so it is allocated across eligible resting
orders most-in-the-money first (then time priority, via a stable sort), capped by
the trade's size. This is deliberately conservative: it never fills more than the
volume that actually traded through.

Taker/market orders cross the spread and fill at the touch (see
:func:`taker_fill_price`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from ..db import enums
from ..strategy.interface import MarketSnapshot

ZERO = Decimal(0)


@dataclass(slots=True)
class RestingOrder:
    """A maker order resting in the simulated book. ``remaining`` is mutated by the
    engine as fills accrue."""

    tag: str
    order_id: int
    instrument_id: int
    side: str
    limit_price: Decimal
    remaining: Decimal


@dataclass(frozen=True, slots=True)
class ProposedFill:
    tag: str
    order_id: int
    size: Decimal
    price: Decimal


def _improvement(order: RestingOrder, trade_price: Decimal) -> Decimal | None:
    """How far the trade prints *through* the order's limit, or ``None`` if it
    does not (strict inequality — a trade exactly at the limit does not fill)."""
    if order.remaining <= ZERO:
        return None
    if order.side == enums.Side.BUY and trade_price < order.limit_price:
        return order.limit_price - trade_price
    if order.side == enums.Side.SELL and trade_price > order.limit_price:
        return trade_price - order.limit_price
    return None


def match_trade_through(
    orders: Iterable[RestingOrder], *, trade_price: Decimal, trade_size: Decimal
) -> list[ProposedFill]:
    """Fills produced by one public trade, per the strict trade-through rule.

    Allocates ``trade_size`` across eligible resting orders, most-in-the-money
    first (ties keep input/time order via a stable sort). Does not mutate the
    orders — the engine applies the returned fills.
    """
    eligible: list[tuple[Decimal, RestingOrder]] = []
    for order in orders:
        improvement = _improvement(order, trade_price)
        if improvement is not None:
            eligible.append((improvement, order))
    eligible.sort(key=lambda pair: pair[0], reverse=True)

    remaining_trade = trade_size
    fills: list[ProposedFill] = []
    for _, order in eligible:
        if remaining_trade <= ZERO:
            break
        fill_size = min(order.remaining, remaining_trade)
        if fill_size <= ZERO:
            continue
        fills.append(ProposedFill(order.tag, order.order_id, fill_size, order.limit_price))
        remaining_trade -= fill_size
    return fills


def taker_fill_price(side: str, snapshot: MarketSnapshot | None) -> Decimal | None:
    """The price a marketable/taker order pays: cross to the far touch (buy → ask,
    sell → bid), falling back to the snapshot's reference price when that touch is
    unknown. ``None`` if no price is available at all (the order cannot fill)."""
    if snapshot is None:
        return None
    if side == enums.Side.BUY:
        return snapshot.ask if snapshot.ask is not None else snapshot.reference_price
    return snapshot.bid if snapshot.bid is not None else snapshot.reference_price
