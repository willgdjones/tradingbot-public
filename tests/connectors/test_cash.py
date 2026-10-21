from datetime import date, datetime
from decimal import Decimal as D

import pytest

from tradingbot.connectors.cash import CashMovement, MarketSession, cash_balance, timestamp


def test_settlement_holiday_is_not_the_next_trading_day():
    session = MarketSession.from_api({
        "date": "2026-10-09", "open": "09:30", "close": "16:00",
        "settlement_date": "2026-10-13",
    })
    flows = [CashMovement("buy", D(20), D(0), session.settlement_date),
             CashMovement("sell", D(21), D(0), session.settlement_date)]
    before = cash_balance(D(20), flows, D(0), timestamp("2026-10-12T16:00:00Z"))
    after = cash_balance(D(20), flows, D(0), timestamp("2026-10-13T13:30:00Z"))
    assert (before.available, before.unsettled) == (D(0), D(21))
    assert (after.available, after.unsettled) == (D(21), D(0))


def test_reservations_and_fees_reduce_spendable_cash():
    balance = cash_balance(D(50), [CashMovement("buy", D(10), D("0.01"), date(2026, 10, 1))],
                           D(25), timestamp("2026-09-30T15:00:00Z"))
    assert balance.available == D("14.99")


def test_settlement_uses_new_york_date_not_utc_midnight():
    flow = CashMovement("sell", D(10), D(0), date(2026, 10, 1))
    assert cash_balance(D(0), [flow], D(0), timestamp("2026-10-01T01:00:00Z")).available == 0
    assert cash_balance(D(0), [flow], D(0), timestamp("2026-10-01T04:00:00Z")).available == 10


def test_calendar_requires_explicit_settlement_and_handles_early_close_dst():
    row = {"date": "2026-11-27", "open": "09:30", "close": "13:00", "settlement_date": "2026-11-30"}
    market = MarketSession.from_api(row)
    assert market.is_open(timestamp("2026-11-27T17:59:59Z"))
    assert not market.is_open(timestamp("2026-11-27T18:00:00Z"))
    del row["settlement_date"]
    with pytest.raises(KeyError):
        MarketSession.from_api(row)
    with pytest.raises(ValueError, match="timezone-aware"):
        market.is_open(datetime(2026, 11, 27))


@pytest.mark.parametrize("bad", [float("nan"), 1.1, True, "Infinity", "-1"])
def test_cash_rejects_invalid_money(bad):
    with pytest.raises((ValueError, TypeError)):
        cash_balance(bad, [], D(0), timestamp("2026-09-30T15:00:00Z"))
