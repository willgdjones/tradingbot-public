"""Pure fill-model tests: strict trade-through and taker touch (PRD §7)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from tradingbot.backtest.fills import (
    ProposedFill,
    RestingOrder,
    match_trade_through,
    taker_fill_price,
)
from tradingbot.db import enums
from tradingbot.strategy.interface import MarketSnapshot

TS = datetime(2026, 9, 30, tzinfo=timezone.utc)


def buy(price, rem, tag="b"):
    return RestingOrder(tag, 1, 10, enums.Side.BUY, Decimal(price), Decimal(rem))


def sell(price, rem, tag="s"):
    return RestingOrder(tag, 2, 10, enums.Side.SELL, Decimal(price), Decimal(rem))


def test_buy_fills_only_when_trade_prints_strictly_below():
    assert match_trade_through([buy("0.50", "5")], trade_price=Decimal("0.49"),
                               trade_size=Decimal("5")) == [
        ProposedFill("b", 1, Decimal("5"), Decimal("0.50"))
    ]
    # Equal price does not fill (strict), nor does a print above.
    assert match_trade_through([buy("0.50", "5")], trade_price=Decimal("0.50"),
                               trade_size=Decimal("5")) == []
    assert match_trade_through([buy("0.50", "5")], trade_price=Decimal("0.51"),
                               trade_size=Decimal("5")) == []


def test_sell_fills_only_when_trade_prints_strictly_above():
    fills = match_trade_through([sell("0.50", "4")], trade_price=Decimal("0.55"),
                               trade_size=Decimal("10"))
    assert [(f.size, f.price) for f in fills] == [(Decimal("4"), Decimal("0.50"))]
    assert match_trade_through([sell("0.50", "4")], trade_price=Decimal("0.50"),
                               trade_size=Decimal("10")) == []


def test_fill_price_is_the_resting_limit_and_size_is_capped_by_the_trade():
    fills = match_trade_through([buy("0.50", "5")], trade_price=Decimal("0.40"),
                               trade_size=Decimal("3"))
    assert len(fills) == 1
    assert fills[0].price == Decimal("0.50")  # you posted it, you get it
    assert fills[0].size == Decimal("3")       # capped by the trade's size


def test_allocation_most_in_the_money_first_then_capped():
    orders = [buy("0.55", "5", "mid"), buy("0.60", "5", "top")]
    fills = match_trade_through(orders, trade_price=Decimal("0.50"), trade_size=Decimal("7"))
    # 'top' (0.60) is more in-the-money than 'mid' (0.55): it fills first.
    assert [(f.tag, f.size) for f in fills] == [("top", Decimal("5")), ("mid", Decimal("2"))]


def test_zero_remaining_order_is_ignored():
    assert match_trade_through([buy("0.50", "0")], trade_price=Decimal("0.40"),
                               trade_size=Decimal("5")) == []


def test_taker_fill_price_crosses_to_the_far_touch():
    snap = MarketSnapshot(10, TS, bid=Decimal("0.40"), ask=Decimal("0.44"), mid=Decimal("0.42"))
    assert taker_fill_price(enums.Side.BUY, snap) == Decimal("0.44")   # pays the ask
    assert taker_fill_price(enums.Side.SELL, snap) == Decimal("0.40")  # hits the bid


def test_taker_fill_price_falls_back_to_reference_then_none():
    only_mid = MarketSnapshot(10, TS, mid=Decimal("0.42"))
    assert taker_fill_price(enums.Side.BUY, only_mid) == Decimal("0.42")
    empty = MarketSnapshot(10, TS)
    assert taker_fill_price(enums.Side.BUY, empty) is None
    assert taker_fill_price(enums.Side.BUY, None) is None
