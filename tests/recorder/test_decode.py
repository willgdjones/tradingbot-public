"""Pure decoder tests: no DB, no async, deterministic clock."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tradingbot.db import enums
from tradingbot.recorder.decode import (
    decode_market_data,
    decode_market_data_lite,
    decode_trade,
    parse_amount,
)

TS = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def amount(value: str) -> dict:
    return {"value": value, "currency": "USD"}


def test_parse_amount_forms_and_exact_decimal():
    assert parse_amount(amount("0.1234567890123456789")) == Decimal("0.1234567890123456789")
    assert parse_amount("0.5") == Decimal("0.5")
    assert parse_amount(None) is None
    assert parse_amount({"value": "", "currency": "USD"}) is None
    assert parse_amount({"value": None}) is None
    assert parse_amount("not-a-number") is None


def test_market_data_best_of_book_from_unsorted_levels():
    payload = {
        "marketSlug": "will-x",
        "bids": [
            {"px": amount("0.40"), "qty": "100"},
            {"px": amount("0.42"), "qty": "250"},  # best bid (highest)
            {"px": amount("0.41"), "qty": "10"},
        ],
        "offers": [
            {"px": amount("0.47"), "qty": "80"},
            {"px": amount("0.45"), "qty": "60"},  # best ask (lowest)
        ],
        "state": "MARKET_STATE_OPEN",
        "transactTime": "2026-09-30T11:59:59Z",
        "stats": {"lastTradePx": amount("0.44"), "sharesTraded": "9999", "openInterest": "12"},
    }
    obs = decode_market_data(payload, recv_ts=TS)
    assert obs.market_slug == "will-x"
    assert obs.recv_ts == TS
    assert (obs.bid, obs.bid_size) == (Decimal("0.42"), Decimal("250"))
    assert (obs.ask, obs.ask_size) == (Decimal("0.45"), Decimal("60"))
    assert obs.mid == Decimal("0.435")
    assert obs.last == Decimal("0.44")
    assert obs.meta == {
        "source": "market_data",
        "state": "MARKET_STATE_OPEN",
        "transact_time": "2026-09-30T11:59:59Z",
        "shares_traded": "9999",
        "open_interest": "12",
    }


def test_market_data_one_sided_book_has_no_mid():
    obs = decode_market_data(
        {"marketSlug": "m", "bids": [{"px": amount("0.30"), "qty": "5"}], "offers": []},
        recv_ts=TS,
    )
    assert obs.bid == Decimal("0.30")
    assert obs.ask is None
    assert obs.ask_size is None
    assert obs.mid is None


def test_market_data_empty_book_is_all_none():
    obs = decode_market_data({"marketSlug": "m"}, recv_ts=TS)
    assert (obs.bid, obs.ask, obs.mid, obs.last) == (None, None, None, None)
    assert obs.meta == {"source": "market_data"}


def test_market_data_lite_has_prices_but_no_sizes():
    obs = decode_market_data_lite(
        {"marketSlug": "m", "bestBid": amount("0.20"), "bestAsk": amount("0.24"),
         "lastTradePx": amount("0.22")},
        recv_ts=TS,
    )
    assert (obs.bid, obs.ask, obs.mid, obs.last) == (
        Decimal("0.20"), Decimal("0.24"), Decimal("0.22"), Decimal("0.22"))
    assert obs.bid_size is None and obs.ask_size is None
    assert obs.meta == {"source": "market_data_lite"}


def test_trade_decodes_price_size_aggressor_and_venue_time():
    payload = {
        "marketSlug": "m",
        "price": amount("0.51"),
        "quantity": amount("30"),
        "tradeTime": "2026-09-30T11:59:58Z",
        "taker": {"side": "SIDE_BUY", "intent": "INTENT_OPEN"},
        "maker": {"side": "SIDE_SELL", "intent": "INTENT_CLOSE"},
    }
    obs = decode_trade(payload, recv_ts=TS)
    assert obs.price == Decimal("0.51")
    assert obs.size == Decimal("30")
    assert obs.aggressor_side == enums.Side.BUY
    assert obs.external_trade_id is None
    assert obs.meta["source"] == "trade"
    assert obs.meta["trade_time"] == "2026-09-30T11:59:58Z"
    assert obs.meta["taker"]["side"] == "SIDE_BUY"
    assert obs.meta["maker"]["side"] == "SIDE_SELL"


def test_trade_unknown_side_is_none_not_an_error():
    obs = decode_trade(
        {"marketSlug": "m", "price": amount("0.5"), "quantity": amount("1"),
         "taker": {"side": "SIDE_UNSPECIFIED"}},
        recv_ts=TS,
    )
    assert obs.aggressor_side is None


@pytest.mark.parametrize("payload", [
    {"marketSlug": "m", "quantity": amount("1")},            # no price
    {"marketSlug": "m", "price": amount("0.5")},             # no quantity
    {"marketSlug": "m", "price": amount(""), "quantity": amount("1")},  # blank price
])
def test_trade_missing_price_or_size_raises(payload):
    with pytest.raises(ValueError):
        decode_trade(payload, recv_ts=TS)
