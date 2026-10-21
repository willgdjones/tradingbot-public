"""End-to-end backtester tests over the real DB feed, the live risk gate and the
ledger (rolled back). Proves the one-code-path plumbing and PRD §6/§7 fidelity."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from tradingbot.backtest import Backtester, Settlement, market_events
from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db import enums
from tradingbot.db.models import Order, Trial
from tradingbot.strategy.interface import Intent, MarketEvent, PlaceOrder, Strategy

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
SPLIT = HoldoutSplit("test-backtester-fixture", T0, T0 + timedelta(seconds=100))


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


class OneShot(Strategy):
    """Buy once (maker) when flat, then rest a maker sell while long. One round trip."""

    key = "test_oneshot"

    def __init__(self, instrument_id, buy_px, sell_px, size):
        super().__init__({})
        self.iid = instrument_id
        self.buy_px = Decimal(buy_px)
        self.sell_px = Decimal(sell_px)
        self.size = Decimal(size)
        self._placed_buy = False

    def on_event(self, ctx, event) -> Sequence[Intent]:
        if event.instrument_id != self.iid:
            return []
        pos = ctx.position(self.iid)
        resting = ctx.resting_tags(self.iid)
        if pos == 0 and not self._placed_buy and "b" not in resting:
            self._placed_buy = True
            return [PlaceOrder(instrument_id=self.iid, side=enums.Side.BUY, size=self.size,
                               limit_price=self.buy_px, tag="b")]
        if pos > 0 and "s" not in resting:
            return [PlaceOrder(instrument_id=self.iid, side=enums.Side.SELL, size=pos,
                               limit_price=self.sell_px, tag="s")]
        return []


def test_maker_round_trip_through_the_db_feed(session, instrument_id, strategy_id,
                                              add_quote, add_trade):
    # Book sets a 0.45 mid; a print at 0.40 fills the resting buy@0.45; a print at
    # 0.60 fills the resting sell@0.55. Round trip: +0.10 * 10 = +$1.00 gross.
    add_quote(instrument_id, at(0), bid=Decimal("0.40"), ask=Decimal("0.50"), mid=Decimal("0.45"))
    add_trade(instrument_id, at(1), price=Decimal("0.40"), size=Decimal("10"))
    add_trade(instrument_id, at(2), price=Decimal("0.60"), size=Decimal("10"))

    strat = OneShot(instrument_id, "0.45", "0.55", "10")
    bt = Backtester(session, strategy=strat, strategy_id=strategy_id)
    result = bt.run(market_events(session, [instrument_id]), split=SPLIT)

    assert result.orders_placed == 2 and result.orders_rejected == 0
    assert result.fills == 2
    assert result.report["trade_count"] == 1        # one completed round trip
    assert result.report["pnl"] == Decimal("1.00")  # gross realized
    assert result.report["pnl_after_fees"] == result.report["pnl"] - result.report["fees_total"]

    trial = session.get(Trial, result.trial_id)
    assert trial.status == enums.TrialStatus.COMPLETE
    assert trial.trade_count == 1
    assert trial.strategy_id == strategy_id and trial.mode == enums.Mode.BACKTEST


def test_trade_exactly_at_the_limit_does_not_fill(session, instrument_id, strategy_id,
                                                  add_quote, add_trade):
    add_quote(instrument_id, at(0), bid=Decimal("0.40"), ask=Decimal("0.50"), mid=Decimal("0.45"))
    add_trade(instrument_id, at(1), price=Decimal("0.45"), size=Decimal("10"))  # equal → no fill

    strat = OneShot(instrument_id, "0.45", "0.55", "10")
    result = Backtester(session, strategy=strat, strategy_id=strategy_id).run(
        market_events(session, [instrument_id]), split=SPLIT)

    assert result.orders_placed == 1 and result.fills == 0
    assert result.report["trade_count"] == 0


def test_risk_engine_vetoes_orders_over_the_25_dollar_cap(session, instrument_id, strategy_id,
                                                          add_quote):
    add_quote(instrument_id, at(0), bid=Decimal("0.40"), ask=Decimal("0.50"), mid=Decimal("0.50"))
    # 100 @ 0.50 = $50 notional > $25 cap (PRD §6): the risk gate must reject it.
    strat = OneShot(instrument_id, "0.50", "0.60", "100")
    result = Backtester(session, strategy=strat, strategy_id=strategy_id).run(
        market_events(session, [instrument_id]), split=SPLIT)

    assert result.orders_placed == 0 and result.orders_rejected == 1 and result.fills == 0
    rejected = session.scalar(
        select(Order).where(Order.trial_id == result.trial_id,
                            Order.status == enums.OrderStatus.REJECTED))
    assert rejected is not None and "per-market position cap" in (rejected.reason or "")


def test_settlement_closes_a_held_position(session, instrument_id, strategy_id, add_quote, add_trade):
    # Buy fills, no exit trade; settle the held long at 1.00.
    add_quote(instrument_id, at(0), bid=Decimal("0.40"), ask=Decimal("0.50"), mid=Decimal("0.45"))
    add_trade(instrument_id, at(1), price=Decimal("0.40"), size=Decimal("10"))

    strat = OneShot(instrument_id, "0.45", "0.99", "10")  # sell never fills
    bt = Backtester(session, strategy=strat, strategy_id=strategy_id)
    result = bt.run(
        market_events(session, [instrument_id]),
        split=SPLIT,
        settlements=[Settlement(instrument_id, Decimal("1.00"), at(10))],
    )
    # Bought 10 @ 0.45, settled 10 @ 1.00 -> +$5.50 gross round trip.
    assert result.report["trade_count"] == 1
    assert result.report["pnl"] == Decimal("5.50")
    settlement_order = session.scalar(select(Order).where(Order.trial_id == result.trial_id, Order.reason == 'settlement'))
    assert settlement_order.created_ts == at(10)


def test_display_price_quotes_do_not_fill_makers(session, instrument_id, strategy_id, add_quote):
    # A historical display-price observation: NULL BBO columns, price in metadata,
    # maker_fill_eligible false. It is a mark, not an executable trade.
    add_quote(instrument_id, at(0),
              metadata={"historical": {"kind": "display_price", "price": "0.45",
                                       "maker_fill_eligible": False}})
    strat = OneShot(instrument_id, "0.45", "0.55", "10")
    result = Backtester(session, strategy=strat, strategy_id=strategy_id).run(
        market_events(session, [instrument_id]), split=SPLIT)
    # The strategy can place a buy off the mark, but nothing fills it (no trades).
    assert result.fills == 0 and result.report["trade_count"] == 0


def test_same_timestamp_print_cannot_fill_a_new_order(session, instrument_id, strategy_id, add_trade):
    # Database id/input ordering is not evidence that the second print is later.
    add_trade(instrument_id, at(0), price=Decimal('.60'), size=Decimal('10'))
    add_trade(instrument_id, at(0), price=Decimal('.40'), size=Decimal('10'))
    add_trade(instrument_id, at(1), price=Decimal('.40'), size=Decimal('10'))
    result = Backtester(session, strategy=OneShot(instrument_id, '.45', '.99', '10'),
                        strategy_id=strategy_id).run(market_events(session, [instrument_id]), split=SPLIT)
    from tradingbot.db.models import Fill
    fills = session.scalars(select(Fill).where(Fill.trial_id == result.trial_id)).all()
    assert result.fills == 1 and fills[0].fill_ts == at(1)
    buy = session.scalar(select(Order).where(Order.trial_id == result.trial_id, Order.side == 'buy'))
    assert buy.created_ts == at(0)


def test_settlement_is_applied_before_later_events_and_cancels_orders(
        session, instrument_id, strategy_id, add_trade):
    add_trade(instrument_id, at(0), price=Decimal('.60'), size=Decimal('10'))
    add_trade(instrument_id, at(1), price=Decimal('.40'), size=Decimal('10'))

    class WatchSettlement(OneShot):
        def on_event(self, ctx, event):
            if event.instrument_id == 0:
                self.quantity_at_marker = ctx.position(self.iid)
                self.resting_at_marker = ctx.resting_tags(self.iid)
            return super().on_event(ctx, event)

    strategy = WatchSettlement(instrument_id, '.45', '.99', '10')
    events = list(market_events(session, [instrument_id])) + [
        MarketEvent.quote(0, at(10), mid=Decimal('.5')),
        MarketEvent.trade(instrument_id, at(11), price=Decimal('1'), size=Decimal('10'), maker_fill_eligible=True),
    ]
    result = Backtester(session, strategy=strategy, strategy_id=strategy_id).run(
        events, split=SPLIT, settlements=[Settlement(instrument_id, Decimal(1), at(10))])
    assert strategy.quantity_at_marker == 0 and strategy.resting_at_marker == ()
    assert result.fills == 1 and result.report['trade_count'] == 1
    sell = session.scalar(select(Order).where(Order.trial_id == result.trial_id, Order.metadata_['tag'].astext == 's'))
    assert sell.status == 'canceled' and sell.closed_ts == at(10)
