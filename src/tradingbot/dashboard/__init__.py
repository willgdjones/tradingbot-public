"""Local read-only dashboard (localhost, PRD §7).

Leaderboard (P&L after fees, trade count, luck odds), backtest-vs-live gap,
kill-switch / incident log, and pipeline status — all read straight from the
ledger and risk tables. Serve it with ``python -m tradingbot.dashboard``.
"""

from __future__ import annotations

from .reports import dashboard_snapshot
from .server import make_server, serve

__all__ = ["dashboard_snapshot", "make_server", "serve"]
