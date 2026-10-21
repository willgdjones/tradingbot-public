"""Daily changes in equity, including overnight inventories and their exits."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from tradingbot.db.models import Quote
from tradingbot.ledger import Ledger
from tradingbot.risk import RiskEngine

START = datetime(2032, 2, 3, tzinfo=timezone.utc)
NOW = START + timedelta(hours=15)


def fill(session, instrument, strategy, side, size, price, at, fee="0", mode="live"):
    ledger = Ledger(session, auto_fee=False)
    order = ledger.record_order(instrument_id=instrument.id, strategy_id=strategy.id if strategy else None, mode=mode,
                                side=side, order_type="limit", size=D(size), limit_price=D(price))
    return ledger.record_fill(order=order, price=D(price), size=D(size), fee=D(fee),
                              liquidity="unknown", fill_ts=at)


def mark(session, instrument, price, at):
    session.add(Quote(instrument_id=instrument.id, time=at, mid=D(price)))
    session.flush()


def test_only_todays_change_on_a_profitable_overnight_long(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "2", "10", START-timedelta(days=2))
    mark(session, instrument, "15", START-timedelta(seconds=1))
    risk = RiskEngine(session)
    assert risk.daily_pnl("live", NOW.date(), {instrument.id: D(12)}, now=NOW) == -6
    assert risk.strategy_pnl(strategy.id, "live", {instrument.id: D(12)}) == 4


@pytest.mark.parametrize("sold, expected", [("4", "-16.03"), ("10", "-10.03")])
def test_partial_and_full_exit_do_not_rebook_prior_day_gain(session, instrument, strategy, sold, expected):
    fill(session, instrument, strategy, "buy", "10", "10", START-timedelta(days=2))
    mark(session, instrument, "12", START-timedelta(seconds=1))
    fill(session, instrument, strategy, "sell", sold, "11", NOW-timedelta(seconds=2), fee=".03")
    assert RiskEngine(session).daily_pnl("live", NOW.date(), {instrument.id: D(10)}, now=NOW) == D(expected)


def test_overnight_loss_is_not_counted_again_after_recovery(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "1", "20", START-timedelta(days=2), fee=".01")
    mark(session, instrument, "10", START-timedelta(seconds=1))
    assert RiskEngine(session).daily_pnl("live", NOW.date(), {instrument.id: D(15)}, now=NOW) == 5


def test_midnight_boundary_fees_and_future_quotes(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "2", "10", START-timedelta(days=1))
    mark(session, instrument, "12", START-timedelta(microseconds=1))
    mark(session, instrument, "11", START)
    fill(session, instrument, strategy, "buy", "1", "11", START, fee=".01")
    mark(session, instrument, "13", NOW)
    mark(session, instrument, "1000", NOW+timedelta(seconds=1))
    assert RiskEngine(session).daily_pnl("live", NOW.date(), now=NOW) == D("3.99")


def test_short_overnight_and_flip_through_zero(session, instrument, strategy):
    fill(session, instrument, strategy, "sell", "2", "10", START-timedelta(days=1))
    mark(session, instrument, "12", START-timedelta(seconds=1))
    fill(session, instrument, strategy, "buy", "3", "11", NOW-timedelta(seconds=1))
    assert RiskEngine(session).daily_pnl("live", NOW.date(), {instrument.id: D(13)}, now=NOW) == 4


def test_closed_overnight_position_needs_no_current_marks(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "2", "10", START-timedelta(days=1))
    mark(session, instrument, "12", START-timedelta(seconds=1))
    fill(session, instrument, strategy, "sell", "2", "11", NOW, fee=".01")
    assert RiskEngine(session).daily_pnl("live", NOW.date(), now=NOW) == D("-2.01")


def test_last_known_fill_fallback_and_mode_isolation(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "2", "10", START-timedelta(days=1))
    fill(session, instrument, strategy, "buy", "3", "20", NOW, mode="paper")
    assert RiskEngine(session).daily_pnl("live", NOW.date(), {instrument.id: D(9)}, now=NOW) == -2


def test_past_day_inventory_reverses_later_fills(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "2", "10", START-timedelta(days=1))
    mark(session, instrument, "12", START-timedelta(seconds=1))
    mark(session, instrument, "11", NOW)
    fill(session, instrument, strategy, "sell", "2", "20", START+timedelta(days=2))
    assert RiskEngine(session).daily_pnl("live", NOW.date(), now=NOW) == -2


def test_multiplier_and_fee_rebate_are_preserved(session, instrument, strategy):
    instrument.contract_multiplier = D(100)
    session.flush()
    fill(session, instrument, strategy, "buy", "1", "10", START-timedelta(days=1))
    mark(session, instrument, "12", START-timedelta(seconds=1))
    fill(session, instrument, strategy, "sell", "1", "11", NOW, fee="-.01")
    assert RiskEngine(session).daily_pnl("live", NOW.date(), now=NOW) == D("-99.99")


def test_unattributed_fills_are_not_mistaken_for_cash_losses(session, instrument):
    fill(session, instrument, None, "buy", "2", "10", START-timedelta(days=1))
    mark(session, instrument, "12", START-timedelta(seconds=1))
    assert RiskEngine(session).daily_pnl("live", NOW.date(), {instrument.id: D(11)}, now=NOW) == -2


def test_non_utc_runtime_clock_uses_utc_halt_day(session, instrument, strategy):
    fill(session, instrument, strategy, "buy", "100", "1", START-timedelta(days=1))
    mark(session, instrument, "1", START-timedelta(seconds=1))
    local_clock = START.astimezone(timezone(timedelta(hours=-5)))
    risk = RiskEngine(session)
    risk.refresh_halts("live", {instrument.id: D(".4")}, now=local_clock)
    assert risk.daily_halt_active("live", START.date())
    assert risk.is_globally_halted("live", now=local_clock)
