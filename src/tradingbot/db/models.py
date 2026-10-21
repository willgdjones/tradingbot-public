"""ORM models: the single source of truth for the trading bot's schema.

Design notes
------------
* **Money is ``NUMERIC``, never float.** Prediction-market prices live in
  ``[0, 1]`` (dollars per share); equity prices in dollars. Fees and P&L are in
  USD. Sizes are shares/contracts.
* **One code path for backtest, paper and live** (PRD §4). Orders, fills and
  positions all carry a ``mode`` column instead of living in separate tables.
* **``quotes`` and ``trades`` are TimescaleDB hypertables** (the tape + book
  snapshots). They are append-only, high volume, and deliberately carry *no*
  foreign key on ``instrument_id`` (indexed instead) to keep ingestion cheap and
  avoid hypertable FK edge cases. The hypertable conversion happens in the
  Alembic migration, not here.
* **USD/GBP rate is snapshotted onto every fill** (PRD §10) so an accountant can
  reconstruct GBP values without a rate lookup.

The risk engine (tradingbot-s94) and ledger (tradingbot-845) build directly on
these tables; do not change ``risk_halts``/``positions``/``fills`` shapes without
coordinating.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from . import enums
from .iex_models import IexBar, IexSnapshot, IexRecorderHealth  # noqa: F401
from .event_models import EventFeedSnapshot  # noqa: F401
from .jev_intraday_models import JevTurn  # noqa: F401

# Reusable column types. Precision is generous; prediction-market prices need
# only a few decimals, but equities/options and FX rates want the headroom.
PRICE = Numeric(18, 8)
SIZE = Numeric(28, 10)
MONEY = Numeric(18, 6)  # USD amounts: fees, P&L, allocations
RATE = Numeric(18, 8)


def _mode_check(name: str = "mode_valid"):
    return CheckConstraint(
        "mode IN %s" % _sql_tuple(enums.Mode.ALL), name=name
    )


def _sql_tuple(values: tuple[str, ...]) -> str:
    inner = ", ".join("'%s'" % v for v in values)
    return "(%s)" % inner


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
class Venue(Base, TimestampMixin):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    is_live_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    markets: Mapped[list["Market"]] = relationship(back_populates="venue")
    instruments: Mapped[list["Instrument"]] = relationship(back_populates="venue")

    __table_args__ = (
        CheckConstraint(
            "kind IN %s" % _sql_tuple(enums.VenueKind.ALL), name="kind_valid"
        ),
    )


class Market(Base, TimestampMixin):
    """A resolvable event / underlying grouping (a Kalshi event, a Polymarket
    condition, or an equity's synthetic market)."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    market_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=enums.MarketStatus.OPEN
    )
    open_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolve_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    venue: Mapped[Venue] = relationship(back_populates="markets")
    instruments: Mapped[list["Instrument"]] = relationship(back_populates="market")

    __table_args__ = (
        UniqueConstraint("venue_id", "external_id", name="uq_markets_venue_external"),
        CheckConstraint(
            "market_type IN %s" % _sql_tuple(enums.MarketType.ALL),
            name="market_type_valid",
        ),
        CheckConstraint(
            "status IN %s" % _sql_tuple(enums.MarketStatus.ALL), name="status_valid"
        ),
    )


class Instrument(Base, TimestampMixin):
    """A single tradeable line: a Polymarket outcome token, a Kalshi
    yes/no side, an equity symbol, or an option contract."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id"), nullable=False, index=True
    )
    market_id: Mapped[int | None] = mapped_column(
        ForeignKey("markets.id"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default="USD")
    price_min: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    price_max: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    tick_size: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    contract_multiplier: Mapped[Decimal] = mapped_column(
        SIZE, nullable=False, server_default="1"
    )
    expiry_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    strike: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    range_low: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    range_high: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    venue: Mapped[Venue] = relationship(back_populates="instruments")
    market: Mapped[Market | None] = relationship(back_populates="instruments")

    __table_args__ = (
        UniqueConstraint(
            "venue_id", "external_id", name="uq_instruments_venue_external"
        ),
        CheckConstraint(
            "instrument_type IN %s" % _sql_tuple(enums.InstrumentType.ALL),
            name="instrument_type_valid",
        ),
    )


# ---------------------------------------------------------------------------
# Market data (TimescaleDB hypertables). No FK on instrument_id by design.
# ---------------------------------------------------------------------------
class Quote(Base):
    """Top-of-book snapshot. Hypertable on ``time``."""

    __tablename__ = "quotes"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bid: Mapped[Decimal | None] = mapped_column(PRICE)
    ask: Mapped[Decimal | None] = mapped_column(PRICE)
    bid_size: Mapped[Decimal | None] = mapped_column(SIZE)
    ask_size: Mapped[Decimal | None] = mapped_column(SIZE)
    mid: Mapped[Decimal | None] = mapped_column(PRICE)
    last: Mapped[Decimal | None] = mapped_column(PRICE)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_quotes_instrument_time", "instrument_id", "time"),
    )


class Trade(Base):
    """A public trade print (the tape). The paper engine fills a resting maker
    order only when a later trade goes *through* its price (PRD §7), so this is
    the ground truth for paper fills. Hypertable on ``time``."""

    __tablename__ = "trades"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Public APIs can report more decimal places than an order's tick/size grid
    # (including historical aggregate execution prices). Preserve their exact
    # wire decimal. Order/fill/position accounting keeps its existing types.
    price: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    aggressor_side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    external_trade_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_trades_instrument_time", "instrument_id", "time"),
    )


# ---------------------------------------------------------------------------
# Strategies and the trials ledger
# ---------------------------------------------------------------------------
class Strategy(Base, TimestampMixin):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=enums.StrategyStatus.IDEA
    )
    # Allocation drives the per-strategy −40% kill (PRD §6). USD.
    allocation_usd: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, server_default="0"
    )
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    trials: Mapped[list["Trial"]] = relationship(back_populates="strategy")

    __table_args__ = (
        CheckConstraint(
            "status IN %s" % _sql_tuple(enums.StrategyStatus.ALL), name="status_valid"
        ),
    )


class BacktestDataset(Base):
    """Immutable time bounds for a named research dataset (PRD §4)."""

    __tablename__ = "backtest_datasets"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    data_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    holdout_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("data_start < holdout_start AND holdout_start < data_end", name="ordered_split"),)


class HoldoutFamilyAlias(Base):
    """An immutable strategy-row/reactor-name binding to a research family."""

    __tablename__ = "holdout_family_aliases"

    alias: Mapped[str] = mapped_column(String(256), primary_key=True)
    family_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)


class FamilyHoldoutSpend(Base):
    """Permanent admission receipt; source coverage includes the seen training data."""

    __tablename__ = "family_holdout_spends"

    trial_id: Mapped[int] = mapped_column(ForeignKey("trials.id"), primary_key=True)
    family_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dataset_key: Mapped[str] = mapped_column(ForeignKey("backtest_datasets.key"), nullable=False)
    data_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    holdout_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("data_start < holdout_start AND holdout_start < data_end", name="ordered_split"),)


class Trial(Base):
    """Trials ledger: every strategy variant and parameter set tried, including
    failures (PRD §4). A backtest run, a paper experiment, or a live run all get
    a row here; orders/fills reference the trial they belong to."""

    __tablename__ = "trials"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("strategies.id"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dataset_key: Mapped[str | None] = mapped_column(ForeignKey("backtest_datasets.key"))
    holdout_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    strategy_version: Mapped[str | None] = mapped_column(String(64))
    final_holdout: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=enums.TrialStatus.RUNNING
    )
    # Result metrics (populated on completion).
    pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    pnl_after_fees: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fees_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    sharpe: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_drawdown: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Probability the result is luck vs zero edge (PRD §4 "luck odds").
    luck_p_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    strategy: Mapped[Strategy] = relationship(back_populates="trials")

    __table_args__ = (
        _mode_check(),
        Index("uq_trials_final_holdout_version", "strategy_version", unique=True,
              postgresql_where=text("final_holdout")),
        CheckConstraint("NOT final_holdout OR (mode = 'backtest' AND strategy_version IS NOT NULL "
                        "AND dataset_key IS NOT NULL AND holdout_start IS NOT NULL)", name="holdout_identity"),
        CheckConstraint(
            "status IN %s" % _sql_tuple(enums.TrialStatus.ALL), name="status_valid"
        ),
    )


# ---------------------------------------------------------------------------
# Orders, fills, positions (the ledger's tables)
# ---------------------------------------------------------------------------
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id"), nullable=True, index=True
    )
    trial_id: Mapped[int | None] = mapped_column(
        ForeignKey("trials.id"), nullable=True, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    intended_liquidity: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=enums.Liquidity.UNKNOWN
    )
    limit_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    size: Mapped[Decimal] = mapped_column(SIZE, nullable=False)
    filled_size: Mapped[Decimal] = mapped_column(SIZE, nullable=False, server_default="0")
    avg_fill_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=enums.OrderStatus.PENDING
    )
    venue_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    submitted_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    closed_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    fills: Mapped[list["Fill"]] = relationship(back_populates="order")

    __table_args__ = (
        _mode_check(),
        CheckConstraint("side IN %s" % _sql_tuple(enums.Side.ALL), name="side_valid"),
        CheckConstraint(
            "order_type IN %s" % _sql_tuple(enums.OrderType.ALL),
            name="order_type_valid",
        ),
        CheckConstraint(
            "intended_liquidity IN %s" % _sql_tuple(enums.Liquidity.ALL),
            name="liquidity_valid",
        ),
        CheckConstraint(
            "status IN %s" % _sql_tuple(enums.OrderStatus.ALL), name="status_valid"
        ),
        Index("ix_orders_strategy_mode_status", "strategy_id", "mode", "status"),
        Index("ix_orders_instrument_status", "instrument_id", "status"),
    )


class Fill(Base):
    """An execution of one of our orders. This is a *tax record* (PRD §10): it
    stores timestamp, venue (via instrument), price, size, fee and the USD/GBP
    rate at fill time."""

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False, index=True
    )
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id"), nullable=True, index=True
    )
    trial_id: Mapped[int | None] = mapped_column(
        ForeignKey("trials.id"), nullable=True, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    size: Mapped[Decimal] = mapped_column(SIZE, nullable=False)
    notional: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    liquidity: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=enums.Liquidity.UNKNOWN
    )
    venue_fill_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fill_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usd_gbp_rate: Mapped[Decimal | None] = mapped_column(RATE, nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    order: Mapped[Order] = relationship(back_populates="fills")

    __table_args__ = (
        _mode_check(),
        CheckConstraint("side IN %s" % _sql_tuple(enums.Side.ALL), name="side_valid"),
        CheckConstraint(
            "liquidity IN %s" % _sql_tuple(enums.Liquidity.ALL), name="liquidity_valid"
        ),
        Index("ix_fills_strategy_mode_ts", "strategy_id", "mode", "fill_ts"),
        Index("ix_fills_instrument_ts", "instrument_id", "fill_ts"),
    )


class Position(Base):
    """Current holding per (strategy, mode, instrument). A materialised
    aggregate the risk engine reads for the $25 per-market cap (PRD §6); the
    full history always lives in ``fills``."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("strategies.id"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(SIZE, nullable=False, server_default="0")
    avg_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    cost_basis: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    fees_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    last_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=enums.PositionStatus.OPEN
    )
    opened_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    closed_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _mode_check(),
        CheckConstraint(
            "status IN %s" % _sql_tuple(enums.PositionStatus.ALL), name="status_valid"
        ),
        UniqueConstraint(
            "strategy_id", "mode", "instrument_id", name="strategy_mode_instrument"
        ),
        Index("ix_positions_strategy_mode_status", "strategy_id", "mode", "status"),
    )


# ---------------------------------------------------------------------------
# Risk & operations
# ---------------------------------------------------------------------------
class Incident(Base):
    """Kill-switch and incident log (dashboard + reporting). Anything the risk
    engine trips writes a row here."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id"), nullable=True
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id"), nullable=True
    )
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resolved_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "severity IN %s" % _sql_tuple(enums.Severity.ALL), name="severity_valid"
        ),
        CheckConstraint(
            "category IN %s" % _sql_tuple(enums.IncidentCategory.ALL),
            name="category_valid",
        ),
    )


class RiskHalt(Base):
    """Persistent kill-switch state so a permanent per-strategy kill and the
    global daily halt survive a restart. The risk engine (tradingbot-s94) owns
    the *logic*; this table is where it records state.

    PRD §9 accepts that there are no *technical* guardrails preventing edits to
    the limits themselves — but a tripped halt must persist, so we store it."""

    __tablename__ = "risk_halts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id"), nullable=True, index=True
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id"), nullable=True
    )
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    halt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    pnl_at_trigger: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    triggered_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    cleared_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "scope IN %s" % _sql_tuple(enums.HaltScope.ALL), name="scope_valid"
        ),
        Index("ix_risk_halts_scope_active", "scope", "active"),
        Index("ix_risk_halts_strategy_active", "strategy_id", "active"),
    )


class FxRate(Base):
    """Reference FX rates (USD/GBP for tax records, PRD §10). The rate in force
    at fill time is *also* snapshotted onto each fill; this table is the source
    those snapshots come from and supports later reconciliation."""

    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base: Mapped[str] = mapped_column(String(10), nullable=False)
    quote: Mapped[str] = mapped_column(String(10), nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)

    __table_args__ = (
        UniqueConstraint("ts", "base", "quote", name="ts_base_quote"),
        Index("ix_fx_rates_pair_ts", "base", "quote", "ts"),
    )


class JevBudgetControl(Base):
    """Persistent provider-contract circuit breaker; one global Jev budget."""

    __tablename__ = "jev_budget_control"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    halt_reason: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class JevRequest(Base):
    """Durable admission, exact spend, and question/probability calibration audit.

    Unsettled reservations count against every month until reconciled. A call
    spanning a month boundary counts its actual cost in both months.
    """

    __tablename__ = "jev_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billing_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    completed_month: Mapped[date | None] = mapped_column(Date)
    correlation_id: Mapped[str | None] = mapped_column(String(256), index=True)
    state_hash: Mapped[str | None] = mapped_column(String(64))
    questions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    answers: Mapped[dict | None] = mapped_column(JSONB)
    requested_model: Mapped[str] = mapped_column(String(60), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    input_price_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    outcomes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint("reserved_usd >= 0", name="nonnegative_reserved"),
        CheckConstraint("actual_usd IS NULL OR actual_usd >= 0", name="nonnegative_actual"),
        CheckConstraint(
            "status IN ('pending', 'ok', 'error', 'uncertain', 'refused')",
            name="status_valid",
        ),
    )
