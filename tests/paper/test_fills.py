from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tradingbot.backtest.fills import RestingOrder
from tradingbot.paper.fills import SubmittedMaker, book_key, instant, maker_fills, trade_key
from tradingbot.strategy import MarketEvent

NOW = instant("2026-09-30T15:00:00Z")


def order(side="buy", price="0.50", quantity="10", submitted=None, order_id=1):
    return SubmittedMaker(RestingOrder(str(order_id), order_id, 10, side, D(price), D(quantity)),
                          submitted or NOW - timedelta(seconds=1))


def trade(price="0.49", size="10", occurred=None, received=None, side="sell"):
    return MarketEvent.trade(10, received or NOW, price=D(price), size=D(size),
                             aggressor_side=side, maker_fill_eligible=True,
                             meta={"source": "trade", "trade_time": (occurred or NOW).isoformat()})


@pytest.mark.parametrize("price,count", [("0.49", 1), ("0.50", 0), ("0.51", 0)])
def test_buy_requires_strict_price_crossing(price, count):
    fills = maker_fills([order()], trade(price), now=NOW)
    assert len(fills) == count
    if fills:
        assert fills[0].price == D("0.50")


@pytest.mark.parametrize("price,count", [("0.49", 0), ("0.50", 0), ("0.51", 1)])
def test_sell_requires_strict_price_crossing(price, count):
    assert len(maker_fills([order(side="sell")], trade(price, side="buy"), now=NOW)) == count


def test_strictly_later_execution_not_merely_later_receipt():
    posted = NOW - timedelta(seconds=1)
    for occurred in (posted, posted - timedelta(seconds=1)):
        assert not maker_fills([order(submitted=posted)], trade(occurred=occurred), now=NOW)
    assert maker_fills([order(submitted=posted)], trade(occurred=posted + timedelta(microseconds=1)), now=NOW)


def test_quotes_samples_unknown_timestamps_and_stale_prints_do_not_fill():
    assert not maker_fills([order()], MarketEvent.quote(10, NOW, ask=D("0.49")), now=NOW)
    assert not maker_fills([order()], replace(trade(), maker_fill_eligible=False), now=NOW)
    assert not maker_fills([order()], replace(trade(), meta={"source": "trade"}), now=NOW)
    assert not maker_fills([order()], trade(occurred=NOW + timedelta(seconds=1)), now=NOW)
    assert not maker_fills([order()], trade(), now=NOW + timedelta(seconds=31))


def test_opposing_aggressor_and_finite_shared_volume():
    assert not maker_fills([order()], trade(side="buy"), now=NOW)
    orders = [order(price="0.50", order_id=1), order(price="0.55", order_id=2)]
    fills = maker_fills(orders, trade(size="12"), now=NOW, consumed=D(1))
    assert [(f.order_id, f.size) for f in fills] == [(2, D(10)), (1, D(1))]
    assert not maker_fills(orders, trade(), now=NOW, consumed=D(10))


def test_reconnect_and_decimal_spelling_do_not_create_new_prints():
    event = trade()
    duplicate = replace(event, time=NOW + timedelta(seconds=2), price=D("0.490000"),
                        size=D("10.00"), meta={**event.meta, "row_id": 999})
    assert trade_key(event) == trade_key(duplicate)
    assert trade_key(event) != trade_key(trade(occurred=NOW + timedelta(microseconds=1)))


def test_heartbeat_cannot_replenish_the_same_book_depth():
    quote = MarketEvent.quote(10, NOW, bid=D("0.4"), ask=D("0.5"),
                               bid_size=D(2), ask_size=D(3), meta={"source": "market_data"})
    heartbeat = replace(quote, time=NOW + timedelta(seconds=5), meta={"source": "keepalive"})
    assert book_key(quote, "buy") == book_key(heartbeat, "buy")
    assert book_key(quote, "buy") != book_key(quote, "sell")
