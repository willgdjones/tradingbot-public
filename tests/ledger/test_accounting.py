"""Pure position-accounting tests (no database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tradingbot.db.enums import Side
from tradingbot.ledger.accounting import (
    FillEvent,
    PositionState,
    apply_fill,
    iter_round_trips,
    settle,
)

D = Decimal
T0 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _ts(i: int) -> datetime:
    return T0 + timedelta(minutes=i)


def test_open_long_sets_avg_and_no_realized():
    r = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10"))
    assert r.state.quantity == D("10")
    assert r.state.avg_price == D("0.40")
    assert r.realized_pnl == D("0")


def test_increasing_long_weights_average():
    s = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10")).state
    s = apply_fill(s, Side.BUY, D("0.50"), D("10")).state
    assert s.quantity == D("20")
    assert s.avg_price == D("0.45")


def test_partial_then_full_close_long():
    s = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10")).state
    s = apply_fill(s, Side.BUY, D("0.50"), D("10")).state  # avg 0.45, qty 20
    r = apply_fill(s, Side.SELL, D("0.60"), D("5"))
    assert r.realized_pnl == D("0.75")  # (0.60-0.45)*5
    assert r.state.quantity == D("15")
    assert r.state.avg_price == D("0.45")
    r2 = apply_fill(r.state, Side.SELL, D("0.30"), D("15"))
    assert r2.realized_pnl == D("-2.25")  # (0.30-0.45)*15
    assert r2.state.is_flat
    assert r2.state.realized_pnl == D("-1.50")  # 0.75 - 2.25


def test_flip_long_to_short_realizes_only_closed_portion():
    s = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10")).state
    r = apply_fill(s, Side.SELL, D("0.50"), D("25"))
    assert r.realized_pnl == D("1.0")  # (0.50-0.40)*10
    assert r.state.quantity == D("-15")
    assert r.state.avg_price == D("0.50")  # remainder opens at fill price
    r2 = apply_fill(r.state, Side.BUY, D("0.20"), D("15"))
    assert r2.realized_pnl == D("4.5")  # (0.20-0.50)*15*(-1)
    assert r2.state.is_flat
    assert r2.state.realized_pnl == D("5.5")


def test_short_lifecycle():
    s = apply_fill(PositionState(), Side.SELL, D("0.60"), D("10")).state
    assert s.quantity == D("-10")
    r = apply_fill(s, Side.BUY, D("0.50"), D("4"))
    assert r.realized_pnl == D("0.40")  # (0.50-0.60)*4*(-1)
    r2 = apply_fill(r.state, Side.BUY, D("0.70"), D("6"))
    assert r2.realized_pnl == D("-0.60")  # (0.70-0.60)*6*(-1)
    assert r2.state.realized_pnl == D("-0.20")
    assert r2.state.is_flat


def test_multiplier_scales_pnl():
    s = apply_fill(PositionState(), Side.BUY, D("1.50"), D("2"), multiplier=D("100")).state
    r = apply_fill(s, Side.SELL, D("2.00"), D("2"), multiplier=D("100"))
    assert r.realized_pnl == D("100.00")  # (2.00-1.50)*2*100


def test_fees_accumulate_and_net_realized():
    s = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10"), fee=D("0.05")).state
    r = apply_fill(s, Side.SELL, D("0.60"), D("10"), fee=D("0.05"))
    assert r.state.realized_pnl == D("2.0")
    assert r.state.fees_paid == D("0.10")
    assert r.state.net_realized == D("1.90")


def test_negative_fee_is_maker_rebate():
    s = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10"), fee=D("-0.02")).state
    assert s.fees_paid == D("-0.02")
    assert s.net_realized == D("0.02")  # 0 realized - (-0.02)


def test_unrealized_long_and_short():
    long = PositionState(quantity=D("10"), avg_price=D("0.40"))
    assert long.unrealized(D("0.55")) == D("1.50")
    short = PositionState(quantity=D("-10"), avg_price=D("0.60"))
    assert short.unrealized(D("0.50")) == D("1.00")  # (0.50-0.60)*-10


def test_settle_binary_win_and_loss():
    s = apply_fill(PositionState(), Side.BUY, D("0.40"), D("10")).state
    win = settle(s, D("1"))
    assert win.realized_pnl == D("6.0")  # (1-0.40)*10
    assert win.state.is_flat
    loss = settle(s, D("0"))
    assert loss.realized_pnl == D("-4.0")

    flat = settle(PositionState(), D("1"))
    assert flat.realized_pnl == D("0")


def test_apply_fill_rejects_nonpositive_size():
    with pytest.raises(ValueError):
        apply_fill(PositionState(), Side.BUY, D("0.40"), D("0"))


def test_round_trips_two_complete_one_open():
    fills = [
        FillEvent(Side.BUY, D("0.40"), D("10"), D("0.05"), _ts(0)),
        FillEvent(Side.SELL, D("0.60"), D("10"), D("0.05"), _ts(1)),
        FillEvent(Side.BUY, D("0.50"), D("5"), D("0.02"), _ts(2)),
        FillEvent(Side.SELL, D("0.45"), D("5"), D("0.02"), _ts(3)),
        FillEvent(Side.BUY, D("0.30"), D("10"), D("0.03"), _ts(4)),  # left open
    ]
    trips = iter_round_trips(fills)
    assert len(trips) == 2
    assert trips[0].gross_pnl == D("2.0")
    assert trips[0].fees == D("0.10")
    assert trips[0].net_pnl == D("1.90")
    assert trips[0].entry_ts == _ts(0)
    assert trips[0].exit_ts == _ts(1)
    assert trips[1].net_pnl == D("-0.29")  # (-0.25) - 0.04


def test_round_trips_flip_emits_and_reopens():
    fills = [
        FillEvent(Side.BUY, D("0.40"), D("10"), D("0.01"), _ts(0)),
        FillEvent(Side.SELL, D("0.50"), D("25"), D("0.02"), _ts(1)),  # flip to -15
        FillEvent(Side.BUY, D("0.20"), D("15"), D("0.01"), _ts(2)),  # close short
    ]
    trips = iter_round_trips(fills)
    assert len(trips) == 2
    # First trip closes the long portion: gross (0.50-0.40)*10 = 1.0
    assert trips[0].gross_pnl == D("1.0")
    # Second trip closes the short: (0.20-0.50)*15*(-1) = 4.5
    assert trips[1].gross_pnl == D("4.5")
