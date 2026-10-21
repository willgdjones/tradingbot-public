"""Drawdown and per-regime breakdown of a backtest's round trips (tradingbot-l0v).

The salvage from the Jev-prompt intake (``docs/strategy-intake/2026-09-30-opus-jev-prompt.md``)
asked us to *filter backtest survivors on drawdown as well as return, and check
several market regimes*. The overall drawdown lives in
:meth:`tradingbot.ledger.ledger.Ledger.strategy_report`; this module adds the
per-regime split, so a result that only works in one regime is visible.

A *regime* is any labelling of a round trip by the time it closed: the default is
the calendar month (``YYYY-MM``), a neutral temporal bucket that needs no external
reference series. Pass a custom ``regime_fn`` to split by a real market regime —
e.g. the monetary regime that flips the CPI longshot bias (``docs/research``),
or a volatility state — once that series is available.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from ..ledger.accounting import RoundTrip
from ..ledger.ledger import Ledger
from ..ledger.stats import luck_probability, max_drawdown

RegimeFn = Callable[[datetime], str]


def default_regime(exit_ts: datetime) -> str:
    """Calendar month (UTC) a round trip closed in — the default regime bucket."""
    return exit_ts.astimezone(timezone.utc).strftime("%Y-%m")


def regime_breakdown(
    trips: Sequence[RoundTrip], regime_fn: RegimeFn | None = None
) -> dict[str, dict]:
    """Split time-ordered round trips by regime and report each regime's P&L after
    fees, trade count, max drawdown and luck p-value. Trips must already be in
    exit-time order (as :meth:`Ledger.round_trips` returns them) so each regime's
    drawdown is chronological."""
    regime_fn = regime_fn or default_regime
    buckets: dict[str, list[RoundTrip]] = {}
    for trip in trips:
        buckets.setdefault(regime_fn(trip.exit_ts), []).append(trip)

    out: dict[str, dict] = {}
    for regime, group in buckets.items():
        net = [t.net_pnl for t in group]
        out[regime] = {
            "trade_count": len(net),
            "pnl_after_fees": sum(net, Decimal(0)),
            "max_drawdown": max_drawdown(net),
            "luck_p_value": luck_probability(net),
        }
    return out


def drawdown_regime_report(
    session: Session,
    *,
    strategy_id: int,
    mode: str,
    trial_id: int | None = None,
    regime_fn: RegimeFn | None = None,
    ledger: Ledger | None = None,
) -> dict:
    """Overall drawdown and the per-regime breakdown for a (strategy, mode[, trial])
    scope. ``pnl_after_fees`` here is summed from completed round trips, so it
    excludes any still-open position (unlike the fill-level report)."""
    led = ledger or Ledger(session, auto_fee=False)
    trips = led.round_trips(strategy_id=strategy_id, mode=mode, trial_id=trial_id)
    net = [t.net_pnl for t in trips]
    return {
        "trade_count": len(net),
        "pnl_after_fees": sum(net, Decimal(0)),
        "max_drawdown": max_drawdown(net),
        "luck_p_value": luck_probability(net),
        "by_regime": regime_breakdown(trips, regime_fn),
    }
