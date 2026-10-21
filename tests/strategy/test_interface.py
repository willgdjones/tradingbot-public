"""Strategy interface + reference strategy, tested purely with a fake context."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tradingbot.db import enums
from tradingbot.strategy.examples import ThresholdMaker
from tradingbot.strategy.interface import (
    MarketEvent,
    MarketSnapshot,
    PlaceOrder,
    Strategy,
    StrategyContext,
)

TS = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


class FakeContext(StrategyContext):
    def __init__(self, *, positions=None, snaps=None, resting=None, params=None):
        self._positions = positions or {}
        self._snaps = snaps or {}
        self._resting = resting or {}
        self._params = params or {}

    @property
    def now(self):
        return TS

    @property
    def mode(self):
        return enums.Mode.BACKTEST

    @property
    def params(self):
        return self._params

    def position(self, instrument_id):
        return self._positions.get(instrument_id, Decimal(0))

    def snapshot(self, instrument_id):
        return self._snaps.get(instrument_id)

    def resting_tags(self, instrument_id=None):
        if instrument_id is None:
            return tuple(t for ts in self._resting.values() for t in ts)
        return tuple(self._resting.get(instrument_id, ()))


# -- MarketEvent / snapshot ------------------------------------------------
def test_reference_price_prefers_mid_then_last_then_touch():
    assert MarketSnapshot(1, TS, mid=Decimal("0.5")).reference_price == Decimal("0.5")
    assert MarketSnapshot(1, TS, last=Decimal("0.4")).reference_price == Decimal("0.4")
    assert MarketSnapshot(1, TS, bid=Decimal("0.3"), ask=Decimal("0.5")).reference_price == Decimal("0.4")
    assert MarketSnapshot(1, TS).reference_price is None


def test_market_event_constructors_and_snapshot():
    q = MarketEvent.quote(1, TS, bid=Decimal("0.4"), ask=Decimal("0.44"))
    assert q.is_quote and not q.is_trade
    assert q.as_snapshot().bid == Decimal("0.4")

    t = MarketEvent.trade(1, TS, price=Decimal("0.5"), size=Decimal("3"),
                          maker_fill_eligible=True)
    assert t.is_trade and t.maker_fill_eligible
    assert t.as_snapshot().last == Decimal("0.5")


# -- Intent validation -----------------------------------------------------
@pytest.mark.parametrize("kwargs", [
    {"side": "sideways", "size": Decimal("1"), "limit_price": Decimal("0.5")},
    {"side": enums.Side.BUY, "size": Decimal("0"), "limit_price": Decimal("0.5")},
    {"side": enums.Side.BUY, "size": Decimal("1")},  # limit order without a price
])
def test_place_order_validates(kwargs):
    with pytest.raises(ValueError):
        PlaceOrder(instrument_id=1, **kwargs)


def test_strategy_requires_a_key():
    class NoKey(Strategy):
        def on_event(self, ctx, event):
            return []

    with pytest.raises(ValueError, match="class-level `key`"):
        NoKey()


# -- ThresholdMaker reference strategy -------------------------------------
def _maker(**params):
    return ThresholdMaker({"edge": "0.10", "size": "10", **params})


def test_threshold_maker_rests_a_buy_below_reference_when_flat():
    strat = _maker(instrument_id=10)
    ctx = FakeContext(snaps={10: MarketSnapshot(10, TS, mid=Decimal("0.50"))})
    (intent,) = strat.on_event(ctx, MarketEvent.quote(10, TS, mid=Decimal("0.50")))
    assert isinstance(intent, PlaceOrder)
    assert intent.side == enums.Side.BUY
    assert intent.limit_price == Decimal("0.4500")
    assert intent.intended_liquidity == enums.Liquidity.MAKER
    assert intent.tag == "buy-10"


def test_threshold_maker_rests_a_sell_above_reference_when_long():
    strat = _maker(instrument_id=10)
    ctx = FakeContext(positions={10: Decimal("10")},
                      snaps={10: MarketSnapshot(10, TS, mid=Decimal("0.50"))})
    (intent,) = strat.on_event(ctx, MarketEvent.quote(10, TS, mid=Decimal("0.50")))
    assert intent.side == enums.Side.SELL
    assert intent.limit_price == Decimal("0.5500")
    assert intent.size == Decimal("10")


def test_threshold_maker_does_not_stack_orders_or_stray_instruments():
    strat = _maker(instrument_id=10)
    snaps = {10: MarketSnapshot(10, TS, mid=Decimal("0.50"))}
    # Already resting a buy → no new order.
    ctx = FakeContext(snaps=snaps, resting={10: {"buy-10"}})
    assert strat.on_event(ctx, MarketEvent.quote(10, TS, mid=Decimal("0.50"))) == []
    # Event for an instrument it does not track → nothing.
    ctx2 = FakeContext(snaps={11: MarketSnapshot(11, TS, mid=Decimal("0.50"))})
    assert strat.on_event(ctx2, MarketEvent.quote(11, TS, mid=Decimal("0.50"))) == []


def test_threshold_maker_needs_a_price():
    strat = _maker(instrument_id=10)
    ctx = FakeContext()  # no snapshot
    assert strat.on_event(ctx, MarketEvent.quote(10, TS)) == []
