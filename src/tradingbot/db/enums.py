"""Controlled vocabularies used across the schema.

These are stored as plain ``VARCHAR`` columns guarded by ``CHECK`` constraints
(not native PostgreSQL ENUMs), which keeps them trivial to extend in a later
migration without an ``ALTER TYPE`` dance. Import the tuples when building
``CheckConstraint``s and the ``str`` constants elsewhere in the code base.
"""

from __future__ import annotations


class Mode:
    """Execution context. The *same* strategy code runs in each (PRD §4)."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"
    ALL = (BACKTEST, PAPER, LIVE)


class VenueKind:
    PREDICTION_MARKET = "prediction_market"
    EQUITIES = "equities"
    OPTIONS = "options"
    ALL = (PREDICTION_MARKET, EQUITIES, OPTIONS)


class MarketType:
    BINARY = "binary"
    SCALAR = "scalar"
    CATEGORICAL = "categorical"
    EQUITY = "equity"
    OPTION_CHAIN = "option_chain"
    ALL = (BINARY, SCALAR, CATEGORICAL, EQUITY, OPTION_CHAIN)


class MarketStatus:
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"
    CANCELED = "canceled"
    ALL = (OPEN, CLOSED, SETTLED, CANCELED)


class InstrumentType:
    BINARY_YES = "binary_yes"
    BINARY_NO = "binary_no"
    SCALAR = "scalar"
    EQUITY = "equity"
    OPTION = "option"
    ALL = (BINARY_YES, BINARY_NO, SCALAR, EQUITY, OPTION)


class StrategyStatus:
    IDEA = "idea"
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"
    RETIRED = "retired"
    KILLED = "killed"  # hit the per-strategy -40% kill (PRD §6); permanent
    ALL = (IDEA, BACKTEST, PAPER, LIVE, RETIRED, KILLED)


class TrialStatus:
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    ABANDONED = "abandoned"
    ALL = (RUNNING, COMPLETE, FAILED, ABANDONED)


class Side:
    BUY = "buy"
    SELL = "sell"
    ALL = (BUY, SELL)


class OrderType:
    LIMIT = "limit"
    MARKET = "market"
    ALL = (LIMIT, MARKET)


class Liquidity:
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"
    ALL = (MAKER, TAKER, UNKNOWN)


class OrderStatus:
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ALL = (PENDING, OPEN, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED)


class PositionStatus:
    OPEN = "open"
    CLOSED = "closed"
    ALL = (OPEN, CLOSED)


class Severity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ALL = (INFO, WARNING, CRITICAL)


class IncidentCategory:
    KILL_SWITCH = "kill_switch"
    DAILY_HALT = "daily_halt"
    STRATEGY_KILL = "strategy_kill"
    POSITION_CAP = "position_cap"
    API_ERROR = "api_error"
    STALE_DATA = "stale_data"
    RECONCILIATION = "reconciliation"
    CONNECTIVITY = "connectivity"
    OTHER = "other"
    ALL = (
        KILL_SWITCH,
        DAILY_HALT,
        STRATEGY_KILL,
        POSITION_CAP,
        API_ERROR,
        STALE_DATA,
        RECONCILIATION,
        CONNECTIVITY,
        OTHER,
    )


class HaltScope:
    GLOBAL_DAILY = "global_daily"  # −$50 in one day halts everything (PRD §6)
    STRATEGY = "strategy"  # −40% of allocation, permanent (PRD §6)
    MARKET = "market"
    ALL = (GLOBAL_DAILY, STRATEGY, MARKET)
