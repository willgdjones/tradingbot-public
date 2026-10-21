"""Causality and provenance around the shared strict trade-through matcher."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from tradingbot.backtest.fills import ProposedFill, RestingOrder, match_trade_through
from tradingbot.fees.core import aware, decimal_input
from tradingbot.risk.limits import STALE_DATA_MAX_SECONDS
from tradingbot.strategy import MarketEvent

ZERO = Decimal(0)


def instant(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    aware(parsed)
    return parsed


def positive(value: Decimal) -> Decimal:
    value = decimal_input(value)
    if value <= 0:
        raise ValueError("Expected a finite positive amount")
    return value


def _digest(parts: object) -> str:
    return sha256(json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def trade_key(event: MarketEvent) -> str:
    """Stable across reconnect duplicates; DB row/receive time is not identity.

    Without a native trade ID, identical prints at the same venue timestamp are
    conservatively treated as one. Missing venue time never qualifies for fills.
    """
    native_id = event.meta.get("external_trade_id")
    identity = [event.instrument_id, native_id] if native_id else [
        event.instrument_id, instant(event.meta["trade_time"]).astimezone(timezone.utc).isoformat()
        if event.meta.get("trade_time") else None,
        str(event.price.normalize()) if event.price is not None else None,
        str(event.size.normalize()) if event.size is not None else None,
        event.aggressor_side, event.meta.get("maker"), event.meta.get("taker"),
    ]
    return "paper-trade:" + _digest(identity)


def book_key(event: MarketEvent, side: str) -> str:
    """A heartbeat repeating the same book cannot manufacture fresh depth."""
    return "paper-book:" + _digest([
        event.instrument_id, event.meta.get("transact_time"), side,
        str(event.bid.normalize()) if event.bid is not None else None,
        str(event.ask.normalize()) if event.ask is not None else None,
        str(event.bid_size.normalize()) if event.bid_size is not None else None,
        str(event.ask_size.normalize()) if event.ask_size is not None else None,
    ])


@dataclass(frozen=True)
class SubmittedMaker:
    resting: RestingOrder
    submitted_at: datetime


def maker_fills(orders: list[SubmittedMaker], event: MarketEvent, *, now: datetime,
                consumed: Decimal = ZERO) -> list[ProposedFill]:
    """Later means venue execution time strictly after our submission time.

    Quotes, marks, touches, pre-existing/delayed trades and stale observations
    never fill makers. Known aggressor direction must oppose the resting side.
    """
    aware(now)
    aware(event.time)
    if (not event.is_trade or not event.maker_fill_eligible or event.meta.get("source") != "trade"
            or not event.meta.get("trade_time")
            or not 0 <= (now - event.time).total_seconds() <= STALE_DATA_MAX_SECONDS):
        return []
    occurred_at = instant(event.meta["trade_time"])
    if occurred_at > event.time:
        return []  # cannot assert causality with a future venue timestamp
    price, size = positive(event.price), positive(event.size)
    consumed = decimal_input(consumed)
    if consumed < 0:
        raise ValueError("Consumed tape volume cannot be negative")
    eligible = []
    for candidate in orders:
        order = candidate.resting
        aware(candidate.submitted_at)
        if order.instrument_id != event.instrument_id or occurred_at <= candidate.submitted_at:
            continue
        if event.aggressor_side in ("buy", "sell") and event.aggressor_side == order.side:
            continue
        eligible.append(order)
    return match_trade_through(eligible, trade_price=price, trade_size=max(ZERO, size - consumed))
