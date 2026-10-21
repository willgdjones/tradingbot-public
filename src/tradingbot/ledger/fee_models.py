"""Map a venue to its exact per-order fee model (thin adapter over ``tradingbot.fees``).

The underlying models are *stateful per order* (e.g. a cumulative taker-fee cap),
so callers instantiate one model per order and call ``charge`` once per fill in
order. The :class:`~tradingbot.ledger.ledger.Ledger` uses this to auto-compute
prediction-market fees; equities (Alpaca) are commission-free so there is no
model. For live trading, pass the venue-reported fee explicitly instead.
"""

from __future__ import annotations

from ..fees import (
    PM_US_STANDARD_2026_09_25,
    KalshiOrderFees,
    KalshiSchedule,
    OrderFeeModel,
    PolymarketUSOrderFees,
)

# Venues with no per-trade fee model: Alpaca US equities are commission-free;
# international Polymarket is research-only (never traded, PRD §5).
FEELESS_VENUES = frozenset({"alpaca", "polymarket_intl"})


def fee_model_for_venue(
    venue_key: str,
    *,
    schedule: object | None = None,
) -> OrderFeeModel | None:
    """Return a fresh per-order fee model for ``venue_key``, or ``None`` if the
    venue has no per-trade fee. Raise for an unknown venue."""
    if venue_key == "polymarket_us":
        return PolymarketUSOrderFees(schedule=schedule or PM_US_STANDARD_2026_09_25)
    if venue_key == "kalshi":
        if not isinstance(schedule, KalshiSchedule):
            raise ValueError(
                "Kalshi fees need an explicit dated KalshiSchedule (research only)"
            )
        return KalshiOrderFees(schedule=schedule)
    if venue_key in FEELESS_VENUES:
        return None
    raise ValueError(f"No fee model configured for venue {venue_key!r}")
