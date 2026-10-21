"""Live Polymarket US market-data recorder (tradingbot-xgt).

Captures the order book and public trade tape into the ``quotes`` / ``trades``
hypertables, and keeps a staleness heartbeat so the risk engine's §6 gate stays
honest. See :mod:`tradingbot.recorder.recorder` for the design.
"""

from __future__ import annotations

from .decode import QuoteObs, TradeObs, decode_market_data, decode_market_data_lite, decode_trade
from .heartbeat import FEED_SILENCE_SECONDS, KEEPALIVE_INTERVAL_SECONDS, FeedHealth
from .recorder import MarketDataRecorder
from .store import DbSink, SubscriptionError, resolve_subscriptions

__all__ = [
    "FEED_SILENCE_SECONDS",
    "KEEPALIVE_INTERVAL_SECONDS",
    "DbSink",
    "FeedHealth",
    "MarketDataRecorder",
    "QuoteObs",
    "SubscriptionError",
    "TradeObs",
    "decode_market_data",
    "decode_market_data_lite",
    "decode_trade",
    "resolve_subscriptions",
]
