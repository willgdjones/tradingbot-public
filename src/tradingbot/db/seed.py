"""Idempotent reference-data seed: venues and the PRD §5 strategy definitions.

Downstream work (data downloaders, connectors, backtests) needs venue and
strategy rows to attach markets, instruments, trials and orders to. Running this
more than once is safe — rows are upserted on their natural key.

Usage::

    uv run python -m tradingbot.db.seed
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert

from .enums import StrategyStatus, VenueKind
from .models import Strategy, Venue
from .session import session_scope

# Venues. Kalshi is research-only for now (no account, PRD §5); Polymarket US is
# the first live prediction venue. is_live_enabled reflects that.
VENUES: list[dict] = [
    {
        "key": "kalshi",
        "name": "Kalshi",
        "kind": VenueKind.PREDICTION_MARKET,
        "is_live_enabled": False,  # blocked: no account (2026-09-29)
    },
    {
        "key": "polymarket_us",
        "name": "Polymarket US",
        "kind": VenueKind.PREDICTION_MARKET,
        "is_live_enabled": True,
    },
    {
        "key": "polymarket_intl",
        "name": "Polymarket (international, research only)",
        "kind": VenueKind.PREDICTION_MARKET,
        "is_live_enabled": False,
    },
    {
        "key": "alpaca",
        "name": "Alpaca",
        "kind": VenueKind.EQUITIES,
        "is_live_enabled": False,  # paper first
    },
]

# The first batch of strategies (PRD §5). All start as ideas; the pipeline
# (idea → backtest → paper → live) promotes them. Allocation stays 0 until live.
# venue_key is resolved to venue_id at seed time.
STRATEGIES: list[dict] = [
    {
        "key": "longshot",
        "name": "Favourite–longshot bias",
        "venue_key": "polymarket_us",
        "description": (
            "Rest maker orders on the backtest-picked side per category; hold to "
            "settlement; markets resolving within 7 days. Kalshi+PM research, "
            "trade on Polymarket US."
        ),
    },
    {
        "key": "rewards",
        "name": "Liquidity rewards farming",
        "venue_key": "polymarket_us",
        "description": (
            "Two-sided quotes near reference price; cap net inventory at $15/market; "
            "rank markets by reward pool / competing depth."
        ),
    },
    {
        "key": "spx_ranges",
        "name": "S&P/Nasdaq ranges vs SPX options",
        "venue_key": "kalshi",
        "description": (
            "Trade when Kalshi price minus options-implied prob exceeds fee + 3c; "
            "2:00–3:30pm ET; hold to settlement. Deferred: needs Kalshi account."
        ),
    },
    {
        "key": "weather",
        "name": "Weather: high already recorded",
        "venue_key": "kalshi",
        "description": (
            "Buy the range the day's METAR high has already landed in, after the "
            "historical high-set time, when priced below ~97c. Deferred: needs Kalshi."
        ),
    },
    {
        "key": "letf_eod",
        "name": "End-of-day leveraged-ETF rebalance",
        "venue_key": "alpaca",
        "description": (
            "Enter 3:30pm ET in the direction of the day's large move, exit at close; "
            "cash account T+1, split into alternating-day halves; backtest 2023–2026."
        ),
    },
    {
        "key": "turn_of_month",
        "name": "Turn of the month",
        "venue_key": "alpaca",
        "description": (
            "Buy at close of the 4th-to-last trading day; sell at close of the 3rd "
            "trading day of the next month (SPY)."
        ),
    },
    {
        "key": "promotions",
        "name": "Promotions + Kalshi interest",
        "venue_key": None,
        "description": (
            "Manual: claim guaranteed bonuses; keep >= $250 on Kalshi for 3.75% APY. "
            "Kalshi interest on hold while account is blocked."
        ),
    },
    {
        "key": "x_mention",
        "name": "X mention-spike event study",
        "venue_key": "alpaca",
        "description": (
            "Event = ticker gets >5x its 30-day avg mentions; measure abnormal "
            "returns vs SPY on days 1–5. Paper only until an unseen period confirms."
        ),
    },
]


def seed() -> None:
    """Upsert venues and strategies. Safe to run repeatedly."""
    with session_scope() as session:
        # --- Venues ---------------------------------------------------------
        for v in VENUES:
            stmt = insert(Venue).values(**v)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Venue.key],
                set_={
                    "name": stmt.excluded.name,
                    "kind": stmt.excluded.kind,
                    "is_live_enabled": stmt.excluded.is_live_enabled,
                },
            )
            session.execute(stmt)
        session.flush()

        venue_ids = {v.key: v.id for v in session.query(Venue).all()}

        # --- Strategies -----------------------------------------------------
        for s in STRATEGIES:
            venue_key = s.get("venue_key")
            values = {
                "key": s["key"],
                "name": s["name"],
                "description": s["description"],
                "venue_id": venue_ids.get(venue_key) if venue_key else None,
                "status": StrategyStatus.IDEA,
            }
            stmt = insert(Strategy).values(**values)
            # Do not clobber status/allocation once the pipeline has moved them.
            stmt = stmt.on_conflict_do_update(
                index_elements=[Strategy.key],
                set_={
                    "name": stmt.excluded.name,
                    "description": stmt.excluded.description,
                    "venue_id": stmt.excluded.venue_id,
                },
            )
            session.execute(stmt)

    print(f"Seeded {len(VENUES)} venues and {len(STRATEGIES)} strategies.")


if __name__ == "__main__":
    seed()
