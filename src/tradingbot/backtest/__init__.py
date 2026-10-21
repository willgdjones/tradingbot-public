"""Backtester: run a strategy over historical data through the live risk gate and
ledger (tradingbot-ltj, PRD §4). See :mod:`tradingbot.backtest.engine`.
"""

from __future__ import annotations

from .engine import Backtester, BacktestResult, Settlement
from .feed import market_events
from .fills import ProposedFill, RestingOrder, match_trade_through, taker_fill_price

__all__ = [
    "BacktestResult",
    "Backtester",
    "ProposedFill",
    "RestingOrder",
    "Settlement",
    "market_events",
    "match_trade_through",
    "taker_fill_price",
]
