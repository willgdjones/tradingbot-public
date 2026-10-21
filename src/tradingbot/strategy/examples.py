"""Reference strategies — templates that exercise the interface end to end.

These are *not* the PRD §5 strategies (those get their own files and beads). They
show the shape of a strategy and are used to test the backtester's one-code-path
plumbing.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from ..db import enums
from .interface import Intent, MarketEvent, PlaceOrder, Strategy, StrategyContext
from .registry import register


@register
class ThresholdMaker(Strategy):
    """Rest a maker buy below the reference price when flat; once long, rest a
    maker sell above cost to take profit. One resting order per side at a time.

    Params: ``edge`` (fraction, default 0.05), ``size`` (shares, default 10),
    ``instrument_id`` (optional filter; otherwise trades every instrument seen).
    """

    key = "ref_threshold_maker"

    def _edge(self) -> Decimal:
        return Decimal(str(self.params.get("edge", "0.05")))

    def _size(self) -> Decimal:
        return Decimal(str(self.params.get("size", "10")))

    def _tracks(self, instrument_id: int) -> bool:
        want = self.params.get("instrument_id")
        return want is None or want == instrument_id

    def on_event(
        self, ctx: StrategyContext, event: MarketEvent
    ) -> Sequence[Intent]:
        iid = event.instrument_id
        if not self._tracks(iid):
            return []
        snap = ctx.snapshot(iid)
        ref = snap.reference_price if snap else None
        if ref is None or ref <= 0:
            return []

        edge, size = self._edge(), self._size()
        position = ctx.position(iid)
        resting = ctx.resting_tags(iid)

        if position == 0:
            buy_tag = f"buy-{iid}"
            if buy_tag not in resting:
                price = (ref * (1 - edge)).quantize(Decimal("0.0001"))
                if price > 0:
                    return [PlaceOrder(
                        instrument_id=iid, side=enums.Side.BUY, size=size,
                        limit_price=price, intended_liquidity=enums.Liquidity.MAKER,
                        tag=buy_tag, reason="threshold entry",
                    )]
        elif position > 0:
            sell_tag = f"sell-{iid}"
            if sell_tag not in resting:
                price = (ref * (1 + edge)).quantize(Decimal("0.0001"))
                return [PlaceOrder(
                    instrument_id=iid, side=enums.Side.SELL, size=position,
                    limit_price=price, intended_liquidity=enums.Liquidity.MAKER,
                    tag=sell_tag, reason="threshold exit",
                )]
        return []
