"""Drawdown + per-regime backtest report (tradingbot-l0v).

Pure regime-split tests, plus a DB-backed round-trip test through the ledger
(rolled back) using the tests/backtest/conftest.py fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from tradingbot.backtest.report import (
    default_regime,
    drawdown_regime_report,
    regime_breakdown,
)
from tradingbot.db import enums
from tradingbot.ledger.accounting import RoundTrip
from tradingbot.ledger.ledger import Ledger

D = Decimal


def _trip(exit_ts, net):
    # gross - fees = net; fees 0 so net_pnl == gross_pnl.
    return RoundTrip(entry_ts=exit_ts, exit_ts=exit_ts, gross_pnl=D(net), fees=D("0"))


def test_default_regime_is_calendar_month_utc():
    assert default_regime(datetime(2026, 7, 14, 5, 43, tzinfo=timezone.utc)) == "2026-07"


# -- regime_breakdown (pure) -----------------------------------------------
def test_regime_breakdown_splits_and_scores_each_regime():
    trips = [
        _trip(datetime(2026, 7, 2, tzinfo=timezone.utc), "1.00"),
        _trip(datetime(2026, 7, 20, tzinfo=timezone.utc), "-0.50"),
        _trip(datetime(2026, 8, 5, tzinfo=timezone.utc), "-2.00"),
    ]
    by = regime_breakdown(trips)
    assert set(by) == {"2026-07", "2026-08"}
    assert by["2026-07"]["trade_count"] == 2
    assert by["2026-07"]["pnl_after_fees"] == D("0.50")
    assert by["2026-07"]["max_drawdown"] == D("0.50")  # +1.00 then -0.50
    assert by["2026-08"]["pnl_after_fees"] == D("-2.00")
    assert by["2026-08"]["max_drawdown"] == D("2.00")


def test_regime_breakdown_custom_regime_fn():
    trips = [
        _trip(datetime(2026, 7, 2, tzinfo=timezone.utc), "1.00"),
        _trip(datetime(2026, 8, 5, tzinfo=timezone.utc), "-2.00"),
    ]
    by = regime_breakdown(trips, regime_fn=lambda ts: str(ts.year))
    assert set(by) == {"2026"}
    assert by["2026"]["trade_count"] == 2
    assert by["2026"]["pnl_after_fees"] == D("-1.00")


# -- drawdown_regime_report (DB-backed, rolled back) -----------------------
def _round_trip(led, *, iid, sid, buy_px, sell_px, open_ts, close_ts):
    o_open = led.record_order(
        instrument_id=iid, mode=enums.Mode.BACKTEST, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=sid,
        limit_price=D(buy_px), intended_liquidity=enums.Liquidity.MAKER,
        status=enums.OrderStatus.OPEN,
    )
    led.record_fill(order=o_open, price=D(buy_px), size=D("10"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=open_ts, fee=D("0"))
    o_close = led.record_order(
        instrument_id=iid, mode=enums.Mode.BACKTEST, side=enums.Side.SELL,
        order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=sid,
        limit_price=D(sell_px), intended_liquidity=enums.Liquidity.MAKER,
        status=enums.OrderStatus.OPEN,
    )
    led.record_fill(order=o_close, price=D(sell_px), size=D("10"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=close_ts, fee=D("0"))


def test_drawdown_regime_report_over_two_regimes(session, instrument_id, strategy_id):
    led = Ledger(session, auto_fee=False)
    # July: +$1.00 round trip; August: -$2.00 round trip (same instrument).
    _round_trip(led, iid=instrument_id, sid=strategy_id, buy_px="0.40", sell_px="0.50",
                open_ts=datetime(2026, 7, 1, tzinfo=timezone.utc),
                close_ts=datetime(2026, 7, 2, tzinfo=timezone.utc))
    _round_trip(led, iid=instrument_id, sid=strategy_id, buy_px="0.50", sell_px="0.30",
                open_ts=datetime(2026, 8, 1, tzinfo=timezone.utc),
                close_ts=datetime(2026, 8, 2, tzinfo=timezone.utc))

    rep = drawdown_regime_report(session, strategy_id=strategy_id, mode=enums.Mode.BACKTEST)
    assert rep["trade_count"] == 2
    assert rep["pnl_after_fees"] == D("-1.00")       # +1 - 2
    assert rep["max_drawdown"] == D("2.00")          # peak +1 -> -1
    assert set(rep["by_regime"]) == {"2026-07", "2026-08"}
    assert rep["by_regime"]["2026-07"]["pnl_after_fees"] == D("1.00")
    assert rep["by_regime"]["2026-08"]["max_drawdown"] == D("2.00")


def test_strategy_report_includes_max_drawdown(session, instrument_id, strategy_id):
    led = Ledger(session, auto_fee=False)
    _round_trip(led, iid=instrument_id, sid=strategy_id, buy_px="0.50", sell_px="0.30",
                open_ts=datetime(2026, 8, 1, tzinfo=timezone.utc),
                close_ts=datetime(2026, 8, 2, tzinfo=timezone.utc))
    report = led.strategy_report(strategy_id=strategy_id, mode=enums.Mode.BACKTEST)
    assert report["max_drawdown"] == D("2.00")
    assert report["pnl_after_fees"] == D("-2.00")
