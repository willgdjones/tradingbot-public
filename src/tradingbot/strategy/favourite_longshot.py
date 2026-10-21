"""PRD §5 strategy #1 — the favourite–longshot bias.

Prediction markets price longshots (low-probability outcomes) *too high* and
favourites (high-probability outcomes) *too low* relative to how often they
actually resolve. The structural edge is to take the favourite side (buy it
cheap) or, equivalently, lay the longshot (sell it dear), **as a maker**, and
**hold to settlement**. Which direction actually pays after fees differs by
category, so the backtest picks the side per category and that mapping becomes
the live config (see :mod:`tradingbot.backtest.favourite_longshot`).

This file is a pure reactor on the shared :class:`Strategy` interface — the same
code runs in backtest, paper and live (PRD §4). It never looks at a settlement
value, a clock it was not handed, or a venue; the runtime feeds it events and
applies the §6 risk veto. All reference data it needs (which markets, the
public scheduled close time, the sibling outcomes of a market) is passed in as
``params`` by the runtime, never read from the database here.

Adverse-selection guards (PRD §5, strategies 1–2):

* **Cap fills per market.** ``max_fills_per_market`` bounds how many times we let
  a market pick us off; once hit, we stop quoting that market.
* **Pull quotes before scheduled events.** With ``event_ts`` (the public close /
  release time) and ``entry_blackout_seconds`` set, we cancel resting orders and
  stop entering inside the blackout, so we are not standing in the book across
  the data release that settles the market.
* **One side per market.** We commit to a single outcome of a market (the
  favourite for ``buy_favourite``, the longshot for ``sell_longshot``) and hold
  it to settlement, rather than flip-flopping as prices wobble around the
  threshold. Skipping markets exposed to insider information is a market-
  *selection* concern handled by the runtime, not here.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from ..db import enums
from .interface import (
    CancelOrder,
    Intent,
    MarketEvent,
    PlaceOrder,
    Strategy,
    StrategyContext,
)
from .registry import register

ZERO = Decimal(0)
ONE = Decimal(1)

BUY_FAVOURITE = "buy_favourite"
SELL_LONGSHOT = "sell_longshot"
SIDE_RULES = (BUY_FAVOURITE, SELL_LONGSHOT)


@register
class FavouriteLongshotBias(Strategy):
    """Rest a maker order on the backtest-picked side of each market and hold to
    settlement (PRD §5 #1).

    Params (all optional; prices are decimals in dollars-per-contract, 0..1):

    * ``side_rule`` — ``"buy_favourite"`` (default) or ``"sell_longshot"``.
    * ``threshold`` — favourite/longshot divider price (default ``0.5``).
    * ``offset`` — how far inside the reference the maker rests (default ``0.02``):
      a BUY is posted at ``ref - offset``, a SELL at ``ref + offset``.
    * ``size`` — contracts per order (default ``10``). The §6 $25/market cap and
      the risk gate still bound the real exposure.
    * ``min_price`` / ``max_price`` — only act when the reference is inside this
      band (default ``0.03`` / ``0.97``), keeping clear of the 0/1 extremes and
      the near-certain favourites most exposed to insider flow.
    * ``max_fills_per_market`` — adverse-selection fill cap (default ``3``).
    * ``tick`` — price grid for resting prices (default ``0.01``).
    * ``entry_blackout_seconds`` — stop entering / cancel resting this long before
      ``event_ts`` (default ``0`` — off).
    * ``market_of`` — ``{instrument_id: market_id}``; groups a market's outcomes
      for the fill cap and one-side-per-market commitment. Keys may be ints or
      strings (JSON).
    * ``siblings`` — ``{instrument_id: [other instrument_ids in the market]}``;
      lets the strategy confirm an outcome really is the favourite (highest ref)
      or longshot (lowest ref) of its market, not just past the threshold.
    * ``event_ts`` — ``{instrument_id: ISO datetime}`` public scheduled close.
    * ``instruments`` — optional whitelist of instrument ids to act on.
    """

    key = "longshot"

    # -- param access -------------------------------------------------------
    def _dec(self, name: str, default: str) -> Decimal:
        value = self.params.get(name, default)
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @property
    def _side_rule(self) -> str:
        rule = self.params.get("side_rule", BUY_FAVOURITE)
        if rule not in SIDE_RULES:
            raise ValueError(f"side_rule must be one of {SIDE_RULES}, got {rule!r}")
        return rule

    @property
    def _cap(self) -> int:
        return int(self.params.get("max_fills_per_market", 3))

    @property
    def _blackout(self) -> int:
        return int(self.params.get("entry_blackout_seconds", 0))

    def _group(self, instrument_id: int) -> int | str:
        """The market key an instrument belongs to (for the fill cap and the
        one-side-per-market commitment). Falls back to the instrument itself."""
        market_of = self.params.get("market_of") or {}
        return market_of.get(str(instrument_id), market_of.get(instrument_id, instrument_id))

    def _whitelisted(self, instrument_id: int) -> bool:
        want = self.params.get("instruments")
        return not want or instrument_id in want or str(instrument_id) in want

    def _event_ts(self, instrument_id: int):
        table = self.params.get("event_ts") or {}
        raw = table.get(str(instrument_id), table.get(instrument_id))
        if raw is None:
            return None
        if isinstance(raw, str):
            from datetime import datetime

            return datetime.fromisoformat(raw)
        return raw

    def _is_extreme(self, ctx: StrategyContext, instrument_id: int, ref: Decimal, *, want_max: bool) -> bool:
        """Is this outcome the favourite (``want_max``) or longshot of its market?

        Compares against sibling outcomes we have seen. Unknown siblings are
        ignored; with no sibling information the threshold test alone governs."""
        siblings = self.params.get("siblings") or {}
        ids = siblings.get(str(instrument_id), siblings.get(instrument_id, []))
        for sid in ids:
            snap = ctx.snapshot(int(sid))
            r = snap.reference_price if snap else None
            if r is None:
                continue
            if want_max and r > ref:
                return False
            if not want_max and r < ref:
                return False
        return True

    # -- lifecycle ----------------------------------------------------------
    def on_start(self, ctx: StrategyContext) -> None:
        self._fills: dict[int | str, int] = {}
        self._committed: dict[int | str, int] = {}
        self._abs_pos: dict[int, Decimal] = {}

    def on_event(self, ctx: StrategyContext, event: MarketEvent) -> Sequence[Intent]:
        iid = event.instrument_id
        if not self._whitelisted(iid):
            return []
        group = self._group(iid)

        # Count fills by watching our absolute position grow (fills are applied
        # before this callback). Each growth episode is one adverse-selection fill.
        abs_pos = abs(ctx.position(iid))
        if abs_pos > self._abs_pos.get(iid, ZERO):
            self._fills[group] = self._fills.get(group, 0) + 1
        self._abs_pos[iid] = abs_pos

        # Adverse-selection fill cap: once a market has filled us the capped number
        # of times, cancel the resting remainder so it cannot fill again. The
        # already-filled contracts are still held to settlement.
        if self._fills.get(group, 0) >= self._cap:
            return [CancelOrder(tag=t) for t in ctx.resting_tags(iid)]

        # Pull quotes before the scheduled event (and never enter inside it).
        event_ts = self._event_ts(iid)
        if event_ts is not None and self._blackout > 0:
            from datetime import timedelta

            if ctx.now >= event_ts - timedelta(seconds=self._blackout):
                return [CancelOrder(tag=t) for t in ctx.resting_tags(iid)]

        snap = ctx.snapshot(iid)
        ref = snap.reference_price if snap else None
        if ref is None:
            return []

        # One side per market: once we have taken (or begun quoting) a market via
        # one outcome, we only ever act on that outcome and hold it to settlement.
        committed = self._committed.get(group)
        if committed is not None and committed != iid:
            return []
        if ctx.resting_tags(iid):  # one live order per outcome at a time
            return []

        min_price, max_price = self._dec("min_price", "0.03"), self._dec("max_price", "0.97")
        if not (min_price <= ref <= max_price):
            return []

        threshold = self._dec("threshold", "0.5")
        offset = self._dec("offset", "0.02")
        tick = self._dec("tick", "0.01")
        size = self._dec("size", "10")

        if self._side_rule == BUY_FAVOURITE:
            if ref < threshold or not self._is_extreme(ctx, iid, ref, want_max=True):
                return []
            side = enums.Side.BUY
            price = (ref - offset).quantize(tick, rounding=ROUND_DOWN)
        else:  # SELL_LONGSHOT
            if ref > threshold or not self._is_extreme(ctx, iid, ref, want_max=False):
                return []
            side = enums.Side.SELL
            price = (ref + offset).quantize(tick, rounding=ROUND_UP)

        if not (ZERO < price < ONE):  # a prediction-market price must stay in (0, 1)
            return []

        self._committed[group] = iid
        n = self._fills.get(group, 0)
        return [
            PlaceOrder(
                instrument_id=iid,
                side=side,
                size=size,
                limit_price=price,
                intended_liquidity=enums.Liquidity.MAKER,
                tag=f"fl-{iid}-{n}",
                reason=f"{self._side_rule} ref={ref} -> rest {side}@{price}",
            )
        ]
