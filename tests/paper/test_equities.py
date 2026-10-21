from datetime import timedelta
from decimal import Decimal as D

import pytest

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.paper.equities import EquityPaperBook


AT = timestamp("2026-10-02T14:00:00Z")
MARKET = MarketSession.from_api({"date": "2026-10-02", "open": "09:30", "close": "16:00",
                                 "settlement_date": "2026-10-05"})
QUOTE = {"bp": "100", "ap": "101", "bs": 1, "as": 10, "t": AT.isoformat()}


def execute(book, **kwargs):
    return book.execute(**{**dict(identity="one", symbol="SPY", side="buy", quantity=D(".2"),
        quote=QUOTE, now=AT, market=MARKET), **kwargs})


def test_bbo_price_fee_and_resume_are_exact_and_idempotent():
    book = EquityPaperBook(D(35))
    fill = execute(book, stop_distance=D(2))
    assert fill["price"] == "101" and fill["fee"] == "0.01"
    assert book.cash(AT).available == D("14.79")
    resumed = EquityPaperBook(D(35), book.state)
    assert execute(resumed) == fill and len(resumed.state["fills"]) == 1
    assert resumed.state["positions"]["SPY"]["stop_distance"] == "2"


@pytest.mark.parametrize("change", [
    {"t": (AT-timedelta(seconds=31)).isoformat()}, {"t": (AT+timedelta(seconds=1)).isoformat()},
    {"ap": "99"}, {"bp": "0"}, {"as": 0}, {"as": ".5"}, {"as": "NaN"}, {"as": None},
])
def test_stale_future_crossed_and_missing_depth_never_fill(change):
    book = EquityPaperBook(D(35))
    assert execute(book, quote={**QUOTE, **change}) is None
    assert book.cash(AT).available == 35 and not book.state["fills"]


def test_one_share_lower_bound_does_not_interpret_raw_lots_as_shares():
    book = EquityPaperBook(D(500))
    fill = execute(book, quantity=D(4))
    assert D(fill["quantity"]) == 1


def test_sale_cash_waits_for_dated_t_plus_one_over_weekend():
    book = EquityPaperBook(D(35))
    execute(book)
    sold = execute(book, identity="sell", side="sell", quote={**QUOTE, "t": (AT+timedelta(seconds=1)).isoformat()},
                   now=AT+timedelta(seconds=1))
    assert D(sold["quantity"]) == D(".2")
    assert book.cash(AT+timedelta(days=1)).unsettled == D(20)
    assert book.cash(AT+timedelta(days=3)).available == book.cash(AT).available+D(20)
    assert execute(book, identity="second-entry") is None


def test_no_short_no_maker_no_risk_override():
    book = EquityPaperBook(D(35))
    assert execute(book, side="sell") is None
    assert execute(book, identity="risk", allowed=False) is None
    with pytest.raises(ValueError, match="trade-through"):
        execute(book, identity="maker", liquidity="maker")
    assert not book.state["fills"]


def test_cash_cap_includes_buy_fee_and_partial_exit_retains_position():
    book = EquityPaperBook(D(10))
    fill = execute(book)
    assert D(fill["quantity"])*D(fill["price"])+D(fill["fee"]) <= 10
    execute(book, identity="partial-sell", side="sell", quantity=D(".01"))
    assert D(book.state["positions"]["SPY"]["quantity"]) == D(fill["quantity"])-D(".01")


def test_virtual_strategy_kill_is_permanent_and_uses_unrealized_pnl():
    book = EquityPaperBook(D(35))
    assert book.mark_risk({}, AT)["allowed"]
    execute(book)
    risk = book.mark_risk({"SPY": {"bp": "20"}}, AT)
    assert risk["net"] < D(-14) and not risk["allowed"]
    resumed = EquityPaperBook(D(35), book.state)
    assert not resumed.mark_risk({"SPY": {"bp": "200"}}, AT+timedelta(days=1))["allowed"]


def test_virtual_cohort_daily_halt_persists_then_resets_next_day():
    book = EquityPaperBook(D(100))
    assert not book.mark_risk({}, AT, cohort_daily=D(-50))["allowed"]
    assert not book.mark_risk({}, AT+timedelta(hours=1), cohort_daily=D(1))["allowed"]
    assert book.mark_risk({}, AT+timedelta(days=1), cohort_daily=D(1))["allowed"]
