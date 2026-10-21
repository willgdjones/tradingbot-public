"""Strategy interface and reference strategies (tradingbot-ltj).

One code path for backtest, paper and live (PRD §4). Author a strategy as a
:class:`Strategy` subclass in its own module; the runtime
(:mod:`tradingbot.backtest`, and later paper/live) drives it through the identical
:class:`StrategyContext`.
"""

from __future__ import annotations

from . import examples  # noqa: F401 - registers the reference strategy on import
from .interface import (
    CancelOrder,
    Intent,
    MarketEvent,
    MarketSnapshot,
    PlaceOrder,
    Strategy,
    StrategyContext,
)
from .registry import get_strategy, register, registered

__all__ = [
    "CancelOrder",
    "Intent",
    "MarketEvent",
    "MarketSnapshot",
    "PlaceOrder",
    "Strategy",
    "StrategyContext",
    "get_strategy",
    "register",
    "registered",
]
