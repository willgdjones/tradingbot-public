"""Pure decoders: Polymarket US market-data wire frames → observations.

No I/O, no DB, no async. Each function takes a plain ``dict`` matching the SDK's
``TypedDict``s (:mod:`polymarket_us.websocket.types`) and the *receive* timestamp
— our wall clock at the moment the frame arrived — and returns a frozen
observation.

Why the receive timestamp becomes the row ``time`` the risk engine reads: the
§6 staleness gate means "halt if the freshest data is more than 30 seconds old",
i.e. *how long since we last observed data*. That must be our clock, not the
venue's, so a skewed or oddly formatted venue timestamp can never make stale
data look fresh (or vice-versa). The venue's own event time is preserved in
``meta`` so the tape keeps its precise timing for research and the paper engine.

Prices arrive as strings (``Amount.value``) and are parsed with
:class:`~decimal.Decimal` directly, never via ``float`` — money is exact
(:mod:`tradingbot.db.models`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from ..db import enums


@dataclass(frozen=True, slots=True)
class QuoteObs:
    """A decoded top-of-book observation, keyed by venue market slug.

    ``instrument_id`` is deliberately absent: the slug→instrument mapping is a
    database concern owned by :mod:`tradingbot.recorder.store`.
    """

    market_slug: str
    recv_ts: datetime
    bid: Decimal | None
    ask: Decimal | None
    bid_size: Decimal | None
    ask_size: Decimal | None
    mid: Decimal | None
    last: Decimal | None
    meta: dict


@dataclass(frozen=True, slots=True)
class TradeObs:
    """A decoded public trade print (the tape)."""

    market_slug: str
    recv_ts: datetime
    price: Decimal
    size: Decimal
    aggressor_side: str | None
    external_trade_id: str | None
    meta: dict


def parse_amount(amount: object) -> Decimal | None:
    """Parse an ``Amount`` (``{"value": "0.53", "currency": "USD"}``), a bare
    numeric string, or ``None`` into an exact :class:`Decimal`. Blank or
    unparseable values become ``None`` rather than raising — a malformed level
    should not crash the feed."""
    if amount is None:
        return None
    value = amount.get("value") if isinstance(amount, dict) else amount
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _best_level(levels: object, *, side: str) -> tuple[Decimal | None, Decimal | None]:
    """Best (price, size) from a list of book levels. Best bid is the highest
    price; best ask (offer) is the lowest. Computed rather than assuming the
    venue pre-sorts the array."""
    best_px: Decimal | None = None
    best_qty: Decimal | None = None
    for level in levels or []:
        px = parse_amount(level.get("px"))
        if px is None:
            continue
        better = best_px is None or (px > best_px if side == "bid" else px < best_px)
        if better:
            best_px, best_qty = px, parse_amount(level.get("qty"))
    return best_px, best_qty


def _mid(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def decode_market_data(payload: dict, *, recv_ts: datetime) -> QuoteObs:
    """Decode a full order-book frame (``SUBSCRIPTION_TYPE_MARKET_DATA``)."""
    bid, bid_size = _best_level(payload.get("bids"), side="bid")
    ask, ask_size = _best_level(payload.get("offers"), side="ask")
    stats = payload.get("stats") or {}
    meta: dict = {"source": "market_data"}
    if payload.get("state"):
        meta["state"] = payload["state"]
    if payload.get("transactTime"):
        meta["transact_time"] = payload["transactTime"]
    for wire_key, meta_key in (("sharesTraded", "shares_traded"),
                               ("openInterest", "open_interest")):
        if stats.get(wire_key) is not None:
            meta[meta_key] = stats[wire_key]
    return QuoteObs(
        market_slug=payload.get("marketSlug") or "",
        recv_ts=recv_ts,
        bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size,
        mid=_mid(bid, ask),
        last=parse_amount(stats.get("lastTradePx")),
        meta=meta,
    )


def decode_market_data_lite(payload: dict, *, recv_ts: datetime) -> QuoteObs:
    """Decode a lightweight best-price frame (``..._MARKET_DATA_LITE``). No
    sizes are carried on the wire, so book depth is ``None``."""
    bid = parse_amount(payload.get("bestBid"))
    ask = parse_amount(payload.get("bestAsk"))
    return QuoteObs(
        market_slug=payload.get("marketSlug") or "",
        recv_ts=recv_ts,
        bid=bid, ask=ask, bid_size=None, ask_size=None,
        mid=_mid(bid, ask),
        last=parse_amount(payload.get("lastTradePx")),
        meta={"source": "market_data_lite"},
    )


def _normalize_side(raw: object) -> str | None:
    """Map a venue side token (e.g. ``"SIDE_BUY"``) to our :class:`enums.Side`;
    unknown tokens return ``None`` and are preserved raw in ``meta``."""
    if not raw or not isinstance(raw, str):
        return None
    upper = raw.upper()
    if "BUY" in upper:
        return enums.Side.BUY
    if "SELL" in upper:
        return enums.Side.SELL
    return None


def decode_trade(payload: dict, *, recv_ts: datetime) -> TradeObs:
    """Decode a public trade print (``SUBSCRIPTION_TYPE_TRADE``).

    The aggressor is the *taker*. Raises :class:`ValueError` on a frame missing
    price or quantity — a trade without either is not a usable tape entry.
    """
    price = parse_amount(payload.get("price"))
    size = parse_amount(payload.get("quantity"))
    if price is None or size is None:
        raise ValueError("trade frame missing price or quantity")
    taker = payload.get("taker") or {}
    meta: dict = {"source": "trade"}
    if payload.get("tradeTime"):
        meta["trade_time"] = payload["tradeTime"]
    if taker:
        meta["taker"] = taker
    if payload.get("maker"):
        meta["maker"] = payload["maker"]
    return TradeObs(
        market_slug=payload.get("marketSlug") or "",
        recv_ts=recv_ts,
        price=price,
        size=size,
        aggressor_side=_normalize_side(taker.get("side")),
        external_trade_id=None,
        meta=meta,
    )
