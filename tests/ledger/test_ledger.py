"""DB-backed Ledger tests (run inside a rolled-back transaction)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradingbot.db import enums
from tradingbot.db.models import FxRate, Instrument, Market
from tradingbot.fees import PM_US_STANDARD_2026_09_25, FeeFill, PolymarketUSOrderFees
from tradingbot.ledger import Ledger

D = Decimal
TS = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)


def _make_instrument(session, venue) -> Instrument:
    suffix = uuid.uuid4().hex[:12]
    market = Market(
        venue_id=venue.id,
        external_id=f"TEST-COND-{suffix}",
        market_type=enums.MarketType.BINARY,
    )
    session.add(market)
    session.flush()
    inst = Instrument(
        venue_id=venue.id,
        market_id=market.id,
        external_id=f"TEST-TOK-{suffix}",
        instrument_type=enums.InstrumentType.BINARY_YES,
        outcome="yes",
        contract_multiplier=D("1"),
    )
    session.add(inst)
    session.flush()
    return inst


def test_record_fill_updates_order_and_position(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id,
        mode=enums.Mode.BACKTEST,
        side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT,
        size=D("10"),
        strategy_id=longshot_strategy.id,
        limit_price=D("0.40"),
        intended_liquidity=enums.Liquidity.MAKER,
    )
    led.record_fill(
        order=order, price=D("0.40"), size=D("6"),
        liquidity=enums.Liquidity.MAKER, fill_ts=TS,
    )
    assert order.status == enums.OrderStatus.PARTIALLY_FILLED
    assert order.filled_size == D("6")

    led.record_fill(
        order=order, price=D("0.42"), size=D("4"),
        liquidity=enums.Liquidity.MAKER, fill_ts=TS + timedelta(minutes=1),
    )
    assert order.status == enums.OrderStatus.FILLED
    assert order.filled_size == D("10")
    # weighted avg fill price: (0.40*6 + 0.42*4)/10 = 0.408
    assert order.avg_fill_price == D("0.408")

    pos = led.get_position(longshot_strategy.id, enums.Mode.BACKTEST, pm_instrument.id)
    assert pos.quantity == D("10")
    assert pos.avg_price == D("0.408")
    assert pos.status == enums.PositionStatus.OPEN


def test_auto_fee_matches_model(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id, mode=enums.Mode.PAPER, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("10"),
        strategy_id=longshot_strategy.id, intended_liquidity=enums.Liquidity.MAKER,
    )
    fill = led.record_fill(
        order=order, price=D("0.40"), size=D("10"),
        liquidity=enums.Liquidity.MAKER, fill_ts=TS,
    )
    expected = PolymarketUSOrderFees(schedule=PM_US_STANDARD_2026_09_25).charge(
        FeeFill(price=D("0.40"), quantity=D("10"), liquidity="maker", side="buy", executed_at=TS)
    ).net_fee
    assert fill.fee == expected


def test_cumulative_taker_fee_across_fills(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id, mode=enums.Mode.PAPER, side=enums.Side.BUY,
        order_type=enums.OrderType.MARKET, size=D("20"),
        strategy_id=longshot_strategy.id, intended_liquidity=enums.Liquidity.TAKER,
    )
    f1 = led.record_fill(order=order, price=D("0.50"), size=D("10"),
                         liquidity=enums.Liquidity.TAKER, fill_ts=TS)
    f2 = led.record_fill(order=order, price=D("0.50"), size=D("10"),
                         liquidity=enums.Liquidity.TAKER, fill_ts=TS + timedelta(seconds=1))

    # One stateful model instance charged in the same order must match the ledger.
    model = PolymarketUSOrderFees(schedule=PM_US_STANDARD_2026_09_25)
    e1 = model.charge(FeeFill(price=D("0.50"), quantity=D("10"), liquidity="taker",
                              side="buy", executed_at=TS)).net_fee
    e2 = model.charge(FeeFill(price=D("0.50"), quantity=D("10"), liquidity="taker",
                              side="buy", executed_at=TS + timedelta(seconds=1))).net_fee
    assert f1.fee == e1
    assert f2.fee == e2


def test_explicit_fee_overrides_auto(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id, mode=enums.Mode.LIVE, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=longshot_strategy.id,
    )
    fill = led.record_fill(
        order=order, price=D("0.40"), size=D("10"), liquidity=enums.Liquidity.MAKER,
        fill_ts=TS, fee=D("0.1234"),
    )
    assert fill.fee == D("0.1234")


def test_usd_gbp_rate_snapshot(session, pm_instrument, longshot_strategy):
    session.add(FxRate(ts=TS - timedelta(hours=1), base="USD", quote="GBP",
                       rate=D("0.78500000"), source="test"))
    session.flush()
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id, mode=enums.Mode.PAPER, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=longshot_strategy.id,
    )
    fill = led.record_fill(order=order, price=D("0.40"), size=D("10"),
                           liquidity=enums.Liquidity.MAKER, fill_ts=TS)
    assert fill.usd_gbp_rate == D("0.78500000")


def test_settle_position_closes_and_records(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id, mode=enums.Mode.BACKTEST, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=longshot_strategy.id,
    )
    led.record_fill(order=order, price=D("0.40"), size=D("10"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=TS)

    settle_fill = led.settle_position(
        strategy_id=longshot_strategy.id, mode=enums.Mode.BACKTEST,
        instrument_id=pm_instrument.id, settlement_price=D("1"),
        settle_ts=TS + timedelta(days=1),
    )
    assert settle_fill is not None
    assert settle_fill.fee == D("0")
    assert settle_fill.realized_pnl == D("6.0")  # (1-0.40)*10
    pos = led.get_position(longshot_strategy.id, enums.Mode.BACKTEST, pm_instrument.id)
    assert pos.status == enums.PositionStatus.CLOSED
    assert pos.quantity == D("0")

    # settling a flat position is a no-op
    assert led.settle_position(
        strategy_id=longshot_strategy.id, mode=enums.Mode.BACKTEST,
        instrument_id=pm_instrument.id, settlement_price=D("1"), settle_ts=TS,
    ) is None


def test_mark_position_unrealized(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=pm_instrument.id, mode=enums.Mode.PAPER, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=longshot_strategy.id,
    )
    led.record_fill(order=order, price=D("0.40"), size=D("10"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=TS)
    pos = led.get_position(longshot_strategy.id, enums.Mode.PAPER, pm_instrument.id)
    u = led.mark_position(pos, D("0.55"))
    assert u == D("1.50")  # (0.55-0.40)*10
    assert pos.last_price == D("0.55")


def test_strategy_report_round_trips_and_luck(session, pm_us_venue, longshot_strategy):
    led = Ledger(session)
    mode = enums.Mode.BACKTEST
    # Two instruments, each a completed round trip -> 2 net-P&L samples.
    for buy, sell in [("0.40", "0.60"), ("0.50", "0.55")]:
        inst = _make_instrument(session, pm_us_venue)
        o1 = led.record_order(instrument_id=inst.id, mode=mode, side=enums.Side.BUY,
                              order_type=enums.OrderType.LIMIT, size=D("10"),
                              strategy_id=longshot_strategy.id)
        led.record_fill(order=o1, price=D(buy), size=D("10"),
                        liquidity=enums.Liquidity.MAKER, fill_ts=TS, fee=D("0.01"))
        o2 = led.record_order(instrument_id=inst.id, mode=mode, side=enums.Side.SELL,
                              order_type=enums.OrderType.LIMIT, size=D("10"),
                              strategy_id=longshot_strategy.id)
        led.record_fill(order=o2, price=D(sell), size=D("10"),
                        liquidity=enums.Liquidity.MAKER, fill_ts=TS + timedelta(minutes=1),
                        fee=D("0.01"))

    report = led.strategy_report(strategy_id=longshot_strategy.id, mode=mode)
    assert report["trade_count"] == 2
    assert report["fill_count"] == 4
    # gross: (0.60-0.40)*10 + (0.55-0.50)*10 = 2.0 + 0.5 = 2.5
    assert report["pnl"] == D("2.5")
    assert report["fees_total"] == D("0.04")
    assert report["pnl_after_fees"] == D("2.46")
    assert report["luck_p_value"] is not None
    assert 0.0 <= report["luck_p_value"] <= 1.0


def test_realized_after_fees_matches_report(session, pm_instrument, longshot_strategy):
    led = Ledger(session)
    mode = enums.Mode.BACKTEST
    o1 = led.record_order(instrument_id=pm_instrument.id, mode=mode, side=enums.Side.BUY,
                          order_type=enums.OrderType.LIMIT, size=D("10"),
                          strategy_id=longshot_strategy.id)
    led.record_fill(order=o1, price=D("0.40"), size=D("10"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=TS, fee=D("0.02"))
    o2 = led.record_order(instrument_id=pm_instrument.id, mode=mode, side=enums.Side.SELL,
                          order_type=enums.OrderType.LIMIT, size=D("10"),
                          strategy_id=longshot_strategy.id)
    led.record_fill(order=o2, price=D("0.60"), size=D("10"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=TS + timedelta(minutes=1),
                    fee=D("0.02"))
    got = led.realized_after_fees(strategy_id=longshot_strategy.id, mode=mode)
    assert got == D("1.96")  # 2.0 gross - 0.04 fees
