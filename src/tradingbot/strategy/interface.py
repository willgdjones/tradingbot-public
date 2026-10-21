"""The strategy interface: one contract, one code path for backtest, paper and
live (PRD §4, §7).

A strategy is written once, as a subclass of :class:`Strategy` in its own file.
It reacts to a time-ordered stream of :class:`MarketEvent`s and returns
:class:`Intent`s (place / cancel). It never touches the database, a venue, the
risk engine, or the execution mode — the *runtime* does that. In backtest the
runtime is :mod:`tradingbot.backtest`; the paper and live runtimes (later beads)
present the identical :class:`StrategyContext`, so the same strategy code runs
unchanged in every mode.

Design rules that keep the three modes identical:

* The strategy is a **pure reactor**: given a context and an event it returns
  intents. It holds no clock, no I/O, and no venue knowledge. Any state it keeps
  is derived from what it has been shown.
* All prices are :class:`~decimal.Decimal`. A strategy must tolerate ``None``
  book fields — historical display/sampled prices carry no executable BBO
  (see ``data/LOADING.md``).
* Order sizing and pricing are only *requests*. The risk engine (§6) has an
  absolute veto the runtime applies before anything reaches a book, in every
  mode, so a strategy can never breach the $25 cap or a halt by asking to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from ..db import enums


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """The latest known state of one instrument, as the strategy sees it. Any
    field may be ``None`` (e.g. a one-sided book, or a historical display price
    that only populates :attr:`mid`)."""

    instrument_id: int
    time: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None

    @property
    def reference_price(self) -> Decimal | None:
        """A single usable price: mid if both sides are known, else last, else
        whichever touch exists. Strategies use this when they just need 'a price'."""
        if self.mid is not None:
            return self.mid
        if self.last is not None:
            return self.last
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.bid if self.bid is not None else self.ask


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One market observation in the replay/live stream. ``kind`` is ``"quote"``
    (a book/top-of-book update) or ``"trade"`` (a public print)."""

    kind: str
    instrument_id: int
    time: datetime
    # quote fields
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    # trade fields
    price: Decimal | None = None
    size: Decimal | None = None
    aggressor_side: str | None = None
    # true only for a real, executable public trade (Kalshi matched tape). A
    # display/sampled "price observation" is a quote, never a trade, so it is
    # never maker-fill eligible (data/LOADING.md, PRD §7).
    maker_fill_eligible: bool = False
    meta: dict = field(default_factory=dict)

    QUOTE = "quote"
    TRADE = "trade"

    @classmethod
    def quote(cls, instrument_id: int, time: datetime, **kw) -> "MarketEvent":
        return cls(kind=cls.QUOTE, instrument_id=instrument_id, time=time, **kw)

    @classmethod
    def trade(
        cls,
        instrument_id: int,
        time: datetime,
        *,
        price: Decimal,
        size: Decimal,
        aggressor_side: str | None = None,
        maker_fill_eligible: bool = False,
        **kw,
    ) -> "MarketEvent":
        return cls(
            kind=cls.TRADE, instrument_id=instrument_id, time=time,
            price=price, size=size, aggressor_side=aggressor_side,
            maker_fill_eligible=maker_fill_eligible, **kw,
        )

    @property
    def is_trade(self) -> bool:
        return self.kind == self.TRADE

    @property
    def is_quote(self) -> bool:
        return self.kind == self.QUOTE

    def as_snapshot(self) -> MarketSnapshot:
        """The instrument's latest state implied by this event (for the context)."""
        if self.is_trade:
            return MarketSnapshot(self.instrument_id, self.time, last=self.price)
        return MarketSnapshot(
            self.instrument_id, self.time, bid=self.bid, ask=self.ask,
            mid=self.mid, last=self.last, bid_size=self.bid_size, ask_size=self.ask_size,
        )


# ---------------------------------------------------------------------------
# Intents: what a strategy asks the runtime to do.
# ---------------------------------------------------------------------------
class Intent:
    """Base class for a strategy's requests. Never executed directly — the runtime
    applies the §6 risk veto first, then routes to a book (backtest/paper/live)."""


@dataclass(frozen=True, slots=True)
class PlaceOrder(Intent):
    """Request to place an order. ``tag`` is the strategy's own handle for it
    (used to cancel later and to correlate fills); the runtime maps it to a real
    order id. A ``limit`` order with :attr:`intended_liquidity` ``maker`` rests
    and fills only when a later trade goes *through* ``limit_price`` (PRD §7)."""

    instrument_id: int
    side: str
    size: Decimal
    order_type: str = enums.OrderType.LIMIT
    limit_price: Decimal | None = None
    intended_liquidity: str = enums.Liquidity.MAKER
    tag: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.side not in enums.Side.ALL:
            raise ValueError(f"invalid side {self.side!r}")
        if self.order_type not in enums.OrderType.ALL:
            raise ValueError(f"invalid order_type {self.order_type!r}")
        if self.size <= 0:
            raise ValueError("order size must be positive")
        if self.order_type == enums.OrderType.LIMIT and self.limit_price is None:
            raise ValueError("a limit order needs a limit_price")


@dataclass(frozen=True, slots=True)
class CancelOrder(Intent):
    """Request to cancel a previously placed order by its strategy ``tag``."""

    tag: str


class StrategyContext(ABC):
    """The read-only view a strategy is given on every callback. The runtime
    implements it; the strategy only reads. Identical across all modes."""

    @property
    @abstractmethod
    def now(self) -> datetime: ...

    @property
    @abstractmethod
    def mode(self) -> str: ...

    @property
    @abstractmethod
    def params(self) -> dict: ...

    @abstractmethod
    def position(self, instrument_id: int) -> Decimal:
        """Current signed position quantity for this strategy (0 if flat)."""

    @abstractmethod
    def snapshot(self, instrument_id: int) -> MarketSnapshot | None:
        """Latest known market state for an instrument, or ``None`` if unseen."""

    @abstractmethod
    def resting_tags(self, instrument_id: int | None = None) -> tuple[str, ...]:
        """Tags of this strategy's currently resting (unfilled) orders."""

    def available_cash(self, instrument_id: int) -> Decimal | None:
        """Settled, unreserved strategy cash, or None when not provided.

        Sizing can use this observation; the runtime still independently checks
        cash, fees, position limits and all risk vetoes before submission.
        """
        return None


class Strategy(ABC):
    """Base class for a strategy — one subclass per file.

    Subclasses set a unique :attr:`key` and implement :meth:`on_event`. The
    optional :meth:`on_start` / :meth:`on_finish` hooks bracket a run.
    """

    key: str = ""

    def __init__(self, params: dict | None = None) -> None:
        if not self.key:
            raise ValueError(f"{type(self).__name__} must set a class-level `key`")
        self.params: dict = dict(params or {})

    def on_start(self, ctx: StrategyContext) -> None:  # noqa: B027 - optional hook
        """Called once before the first event. Default: no-op."""

    @abstractmethod
    def on_event(self, ctx: StrategyContext, event: MarketEvent) -> Sequence[Intent]:
        """React to one market event; return zero or more intents."""

    def on_finish(self, ctx: StrategyContext) -> None:  # noqa: B027 - optional hook
        """Called once after the last event (before settlement). Default: no-op."""
