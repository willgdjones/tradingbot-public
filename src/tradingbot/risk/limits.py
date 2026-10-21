"""PRD §6 hard risk limits.

╔══════════════════════════════════════════════════════════════════════════╗
║  DO NOT CHANGE THESE VALUES WITHOUT EXPLICIT OWNER APPROVAL.              ║
║  AGENTS.md: "Never change the risk limits (PRD §6) without explicit       ║
║  approval from the owner." The risk engine has absolute veto power and    ║
║  these constants are hard-coded on purpose — never computed, configured   ║
║  from .env, or delegated to a model. PRD §9 accepts that the only         ║
║  guardrail on the limits themselves is process (this rule).               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

from decimal import Decimal

# Per-strategy kill: stop a strategy permanently once its P&L (after fees,
# incl. open marks) reaches −40% of its allocation.
PER_STRATEGY_KILL_FRACTION = Decimal("0.40")

# Global daily halt: halt everything once the day's P&L reaches −$50.
GLOBAL_DAILY_HALT_USD = Decimal("-50")

# Per-market position cap (PRD §6; asset-class split approved by the owner on
# 2026-10-01). Prediction markets: no single market may hold more than $25 of
# exposure. Every other venue kind (equities/ETFs, options, futures): a single
# position may use up to the owning strategy's allocation (its slot).
PER_MARKET_POSITION_MAX_USD = Decimal("25")
PREDICTION_MARKET_VENUE_KINDS = frozenset({"prediction_market"})


def position_cap_usd(venue_kind: str | None, strategy_allocation_usd: Decimal | None) -> Decimal:
    """The §6 per-position cap for one market.

    Prediction markets (and anything we cannot classify) get the $25 cap. Other
    venue kinds get the strategy's allocation; a missing or non-positive
    allocation falls back to the conservative $25.
    """
    if venue_kind is None or venue_kind in PREDICTION_MARKET_VENUE_KINDS:
        return PER_MARKET_POSITION_MAX_USD
    if strategy_allocation_usd is None or strategy_allocation_usd <= 0:
        return PER_MARKET_POSITION_MAX_USD
    return strategy_allocation_usd

# Stale data: halt if the freshest market data is older than 30 seconds.
STALE_DATA_MAX_SECONDS = 30

# API errors: halt once 5 errors occur within a rolling 60-second window.
API_ERROR_MAX_PER_MINUTE = 5
API_ERROR_WINDOW_SECONDS = 60
