from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import delete, select

from tradingbot.db.models import Fill, FxRate, Order, Position, Strategy as StrategyRow, Trial
from tradingbot.paper import PaperEngine
from tradingbot.paper.feed import FeedCursor, live_events
from tradingbot.strategy import CancelOrder, PlaceOrder

from .conftest import Reactor


def place(s, *, side="buy", size="10", price=".4", tag="one", liquidity="maker"):
    s.strategy.intents = [PlaceOrder(s.instrument.id, side, D(size), limit_price=D(price),
                                    intended_liquidity=liquidity, tag=tag)]
    s.engine.process(s.quote())
    return s.session.scalar(select(Order).where(Order.trial_id == s.engine.trial_id).order_by(Order.id.desc()))


def fills(s):
    return list(s.session.scalars(select(Fill).where(Fill.trial_id == s.engine.trial_id).order_by(Fill.id)))


def test_later_through_partial_exact_fees_and_fx(setup):
    s = setup
    order = place(s)
    s.engine.process(s.quote(bid=D(".3"), ask=D(".4")))  # quote crosses but never fills maker
    s.engine.process(s.trade(price=".4"))  # touch
    s.engine.process(s.trade(occurred=order.submitted_ts))  # equality is not later
    s.engine.process(s.trade(occurred=order.submitted_ts - timedelta(seconds=1)))
    assert fills(s) == []
    s.engine.process(s.trade(size="4"))
    assert order.status == "partially_filled"
    s.engine.process(s.trade(size="20"))
    rows = fills(s)
    assert [r.size for r in rows] == [D(4), D(6)]
    assert [r.price for r in rows] == [D(".4"), D(".4")]
    assert [r.fee for r in rows] == [D("-.01"), D("-.02")]
    assert all(r.usd_gbp_rate == D(".8") and r.mode == "paper" for r in rows)
    assert order.status == "filled" and s.engine.ctx.position(s.instrument.id) == 10
    assert s.strategy.start_times == [s.session.get(Trial, s.engine.trial_id).data_start]


def test_sell_and_wrong_aggressor(setup):
    s = setup
    place(s, side="sell", price=".6")
    s.engine.process(s.trade(price=".61", aggressor_side="sell"))
    assert not fills(s)
    s.engine.process(s.trade(price=".61", aggressor_side="buy"))
    assert fills(s)[0].side == "sell"


def test_creating_print_cannot_fill_new_order(setup):
    s = setup
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(10), limit_price=D(".4"), tag="new")]
    s.engine.process(s.trade())
    assert not fills(s)
    s.engine.process(s.trade())
    assert len(fills(s)) == 1


def test_duplicate_rows_and_reconnect_print_do_not_reconsume_volume(setup):
    s = setup
    place(s, size="20")
    event = s.trade(size="3", trade_id="native-one")
    assert s.engine.process(event)
    assert not s.engine.process(event)
    s.engine.process(s.trade(size="3", trade_id="native-one", occurred=event.time))
    assert sum(r.size for r in fills(s)) == 3


def test_order_priority_volume_cancel_and_resume(setup):
    s = setup
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(5), limit_price=D(p), tag=t)
                          for p, t in ((".4", "low"), (".45", "high"))]
    s.engine.process(s.quote())
    s.engine.process(s.trade(size="6"))
    rows = fills(s)
    assert [(r.price, r.size) for r in rows] == [(D(".45"), D(5)), (D(".4"), D(1))]
    trial_id = s.engine.trial_id
    fresh = s.new_engine(Reactor())
    with pytest.raises(ValueError, match="restore"):
        fresh.resume(trial_id)
    fresh.resume(trial_id, strategy_state_restored=True)
    assert fresh.ctx.resting_tags() == ("low",)
    fresh.strategy.intents = [CancelOrder("low")]
    fresh.process(s.quote())
    assert fresh.ctx.resting_tags() == ()
    assert s.session.get(Trial, trial_id).status == "running"
    with pytest.raises(ValueError, match="outstanding"):
        fresh.finish()


@pytest.mark.parametrize("limit", ["cap", "stale", "api", "daily", "kill"])
def test_existing_risk_vetoes_placement(setup, limit):
    s = setup
    event = s.quote()
    if limit == "stale":
        s.clock[0] += timedelta(seconds=31)
    if limit == "api":
        for _ in range(5):
            s.engine.risk.record_api_error(s.clock[0])
    if limit == "daily":
        s.engine.risk.trigger_daily_halt("paper", D(-50), s.clock[0])
    if limit == "kill":
        s.row.status = "killed"
    s.session.commit()
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(100 if limit == "cap" else 10), limit_price=D(".4"))]
    s.engine.process(event)
    order = s.session.scalar(select(Order).where(Order.trial_id == s.engine.trial_id))
    assert order.status == "rejected" and order.reason
    assert not fills(s)


def test_resting_orders_remain_but_cannot_fill_during_halt(setup):
    s = setup
    order = place(s)
    s.engine.risk.trigger_daily_halt("paper", D(-50), s.clock[0])
    s.session.commit()
    s.engine.process(s.trade())
    s.engine.tick()
    assert not fills(s) and order.status == "open"


def test_pending_orders_reserve_market_cap(setup):
    s = setup
    one = place(s, size="40")  # $16
    two = place(s, size="40", tag="two")
    assert one.status == "open" and two.status == "rejected"
    assert "resting" in two.reason


def test_stale_or_future_trade_never_fills(setup):
    s = setup
    place(s)
    event = s.trade()
    s.clock[0] += timedelta(seconds=31)
    s.engine.process(event)
    s.engine.process(s.trade(occurred=s.clock[0] + timedelta(hours=1)))
    assert not fills(s)


def test_taker_depth_and_repeated_book_budget(setup):
    s = setup
    one = place(s, price=".65", size="30", liquidity="taker")
    assert one.status == "canceled" and one.filled_size == 20
    assert fills(s)[0].price == D(".6") and fills(s)[0].fee == D(".33")
    two = place(s, price=".65", size="10", tag="two", liquidity="taker")
    assert two.status == "canceled" and two.filled_size == 0
    assert len(fills(s)) == 1


def test_trade_does_not_freshen_old_taker_book(setup):
    s = setup
    s.engine.process(s.quote())
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(2), limit_price=D(".65"), intended_liquidity="taker")]
    s.engine.process(s.trade(seconds=31))
    order = s.session.scalar(select(Order).where(Order.trial_id == s.engine.trial_id))
    assert order.status == "rejected" and not fills(s)


def test_missing_depth_is_not_executable(setup):
    s = setup
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(2), limit_price=D(".65"), intended_liquidity="taker")]
    s.engine.process(s.quote(ask_size=None))
    assert not fills(s)


def test_maker_cannot_cross_book(setup):
    s = setup
    assert place(s, price=".6").status == "rejected"


def test_fill_and_event_cursor_rollback_on_missing_fx(setup):
    s = setup
    order = place(s)
    s.session.execute(delete(FxRate))
    s.session.commit()
    event = s.trade()
    with pytest.raises(ValueError, match="USD/GBP"):
        s.engine.process(event)
    assert not fills(s) and order.status == "open"
    trial = s.session.get(Trial, s.engine.trial_id)
    assert trial.status == "failed" and trial.metrics["pm_us_paper_v1"]["trade_id"] == 0


def test_strategy_failure_logged_without_partial_orders(setup):
    s = setup
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(2), limit_price=D(".4")), object()]
    with pytest.raises(TypeError):
        s.engine.process(s.quote())
    assert not list(s.session.scalars(select(Order).where(Order.trial_id == s.engine.trial_id)))
    assert s.session.get(Trial, s.engine.trial_id).status == "failed"


def test_poll_reads_live_only_and_commits_cursor(setup):
    s = setup
    s.quote(source="history")
    s.trade(source="historical", trade_id="history")
    event = s.quote()
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(5), limit_price=D(".4"), tag="poll")]
    assert s.engine.poll() == 1
    assert s.engine.ctx.resting_tags() == ("poll",)
    s.trade(size="2")
    assert s.engine.poll() == 1
    assert s.engine.poll() == 0
    assert fills(s)[0].size == 2


def test_finish_empty_trial_records_report(setup):
    s = setup
    s.engine.finish()
    trial = s.session.get(Trial, s.engine.trial_id)
    assert trial.status == "complete" and trial.trade_count == 0


def test_cross_strategy_volume_and_pending_cap(setup):
    s = setup
    place(s, size="30")
    other_row = StrategyRow(key=s.row.key + "-other", name="other", venue_id=s.venue.id,
                           status="paper", allocation_usd=D(100))
    s.session.add(other_row)
    s.session.commit()
    strategy = Reactor()
    engine = PaperEngine(s.session, strategy, strategy_id=other_row.id,
                         instrument_ids=[s.instrument.id], now=lambda: s.clock[0])
    engine.start()
    strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(30), limit_price=D(".4"), tag="other")]
    event = s.quote()
    s.engine.process(event)
    engine.process(event)
    strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(10), limit_price=D(".4"), tag="over-cap")]
    engine.process(s.quote())
    rejected = s.session.scalar(select(Order).where(Order.trial_id == engine.trial_id, Order.status == "rejected"))
    assert rejected is not None
    event = s.trade(size="40")
    s.engine.process(event)
    engine.process(event)
    all_fills = list(s.session.scalars(select(Fill).where(Fill.instrument_id == s.instrument.id)))
    assert sum(row.size for row in all_fills) == 40
    assert s.engine.ctx.position(s.instrument.id) == 30 and engine.ctx.position(s.instrument.id) == 10


@pytest.mark.parametrize("cause", ["api", "kill", "stale", "closed"])
def test_vetoes_rechecked_before_each_fill(setup, cause):
    s = setup
    order = place(s)
    event = s.trade()
    if cause == "api":
        for _ in range(5):
            s.engine.risk.record_api_error(s.clock[0])
    elif cause == "kill":
        s.row.status = "killed"
    elif cause == "stale":
        s.clock[0] += timedelta(seconds=31)
    elif cause == "closed":
        s.market.status = "closed"
    s.session.commit()
    s.engine.process(event)
    assert not fills(s) and order.status == "open"


def test_fresh_mark_during_quiet_tick_trips_existing_kill(setup):
    s = setup
    s.row.allocation_usd = D(5)
    s.session.commit()
    place(s, size="10")
    s.engine.process(s.trade(size="10"))
    s.quote(bid=D(".09"), ask=D(".11"), mid=D(".1"))
    # New recorder quote need not wait for a callback to affect risk monitoring.
    s.engine.tick()
    assert s.row.status == "killed"


def test_new_trial_cannot_steal_old_resting_orders(setup):
    s = setup
    order = place(s)
    next_engine = s.new_engine(Reactor())
    with pytest.raises(ValueError, match="Existing"):
        next_engine.start()
    assert s.session.get(Trial, next_engine.trial_id).status == "failed"
    assert order.status == "open"


def test_bad_strategy_parameters_or_resume_identity_fail_closed(setup):
    s = setup
    s.strategy.intents = [PlaceOrder(s.instrument.id, "buy", D(2), limit_price=D(".400000001"))]
    with pytest.raises(ValueError, match="precision"):
        s.engine.process(s.quote())
    assert s.session.get(Trial, s.engine.trial_id).status == "failed"


def test_resume_does_not_repeat_start_hook_or_consumed_event(setup):
    s = setup
    event = s.quote()
    s.engine.process(event)
    reactor = Reactor()
    fresh = s.new_engine(reactor)
    fresh.resume(s.engine.trial_id, strategy_state_restored=True)
    assert reactor.start_times == [] and not fresh.process(event)


def test_binary_short_liability_cannot_bypass_market_cap(setup):
    s = setup
    s.strategy.intents = [PlaceOrder(s.instrument.id, "sell", D(100), limit_price=D(".01"))]
    s.engine.process(s.quote(bid=D(".005"), ask=D(".02"), mid=D(".01")))
    order = s.session.scalar(select(Order).where(Order.trial_id == s.engine.trial_id))
    assert order.status == "rejected" and "cap" in order.reason
    assert not fills(s)


def test_new_variant_cannot_inherit_unsettled_position(setup):
    s = setup
    place(s)
    s.engine.process(s.trade())
    other = s.new_engine(Reactor())
    with pytest.raises(ValueError, match="positions"):
        other.start()
    assert s.session.get(Trial, other.trial_id).status == "failed"
    assert s.engine.ctx.position(s.instrument.id) == 10
