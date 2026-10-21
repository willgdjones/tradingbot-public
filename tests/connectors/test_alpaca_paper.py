from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector, NAME, OrderRejected, PaperAPIError
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, Incident, Order, Position, RiskHalt, Strategy, Trial

from .conftest import submit


def test_no_network_on_construction_and_explicit_budget_required(setup):
    connector, api, clock, *_ = setup
    assert not api.submissions
    with pytest.raises(OrderRejected, match="Initialize"):
        submit(setup)
    assert not api.submissions
    connector.initialize_cash(D(20))
    assert connector.cash().available == 20
    connector.initialize_cash(D("20.00"))
    with pytest.raises(ValueError, match="cannot be reset"):
        connector.initialize_cash(D(21))


def test_submit_reserves_cash_and_idempotency_survives_a_new_connector(ready):
    connector, api, clock, instrument, strategy, trial = ready
    first = submit(ready)
    assert first.status == "open"
    assert connector.cash().available == 80
    assert api.submissions[0]["qty"] == "0.2"
    assert api.submissions[0]["time_in_force"] == "day"
    assert api.submissions[0]["extended_hours"] is False
    second_connector = AlpacaPaperConnector(connector.session, api, now=lambda: clock[0])
    same = submit((second_connector, api, clock, instrument, strategy, trial))
    assert same.order_id == first.order_id
    assert len(api.submissions) == 1
    with pytest.raises(ValueError, match="different intent"):
        submit(ready, quantity="0.1")


def test_margin_buying_power_does_not_supply_cash(setup):
    connector, api, *_ = setup
    connector.initialize_cash(D(10))
    with pytest.raises(OrderRejected, match="settled cash"):
        submit(setup)
    assert not api.submissions


@pytest.mark.parametrize("field", ["cash", "buying_power"])
def test_broker_cash_and_buying_power_are_additional_ceilings(ready, field):
    connector, api, *_ = ready
    api.account_row[field] = "10"
    with pytest.raises(OrderRejected, match="settled cash"):
        submit(ready)
    assert not api.submissions


def test_partial_fill_cancel_and_repeated_activity_are_idempotent(ready):
    connector, api, clock, *_ = ready
    result = submit(ready)
    clock[0] += timedelta(seconds=1)
    api.fill("one", qty="0.1")
    assert connector.refresh(result.order_id).status == "partially_filled"
    assert connector.cash().settled == 90
    assert connector.cash().reserved == 10
    connector.refresh(result.order_id)
    assert connector.session.scalar(select(func.count()).select_from(Fill).where(Fill.order_id == result.order_id)) == 1
    assert connector.cancel(result.order_id).status == "canceled"
    assert connector.cash().available == 90
    fill = connector.session.scalar(select(Fill).where(Fill.order_id == result.order_id))
    assert fill.usd_gbp_rate == D("0.8")
    assert fill.fee == 0
    assert fill.metadata_["settlement_date"] == "2026-10-01"
    assert fill.liquidity == "unknown"


def test_cancel_ack_does_not_release_cash_and_fill_wins_race(ready):
    connector, api, clock, *_ = ready
    result = submit(ready)
    api.cancel_ack_only = True
    assert connector.cancel(result.order_id).status == "open"
    assert connector.cash().reserved == 20
    clock[0] += timedelta(seconds=1)
    api.fill("one")
    assert connector.refresh(result.order_id).status == "filled"
    assert connector.cash().settled == 80


def test_terminal_status_waits_for_delayed_fill_activities(ready):
    connector, api, clock, *_ = ready
    result = submit(ready)
    clock[0] += timedelta(seconds=1)
    activity = api.fill("one", qty="0.1")
    api.fills.clear()
    api.orders["tbp-one"]["status"] = "canceled"
    assert connector.refresh(result.order_id).status == "open"
    assert connector.cash().reserved == 20
    api.fills.append(activity)
    assert connector.refresh(result.order_id).status == "canceled"
    assert connector.cash().available == 90


@pytest.mark.parametrize("start,blocked_day,settled_day", [
    ("2026-09-30", "2026-09-30", "2026-10-01"),
    ("2026-10-09", "2026-10-12", "2026-10-13"),
])
def test_sale_proceeds_wait_for_settlement_even_with_broker_margin(setup, start, blocked_day, settled_day):
    connector, api, clock, *_ = setup
    clock[0] = timestamp(start + "T14:00:00Z")
    connector.initialize_cash(D(20))
    buy = submit(setup, "buy")
    clock[0] += timedelta(seconds=1)
    api.fill("buy")
    connector.refresh(buy.order_id)
    sell = submit(setup, "sell", side="sell")
    clock[0] += timedelta(seconds=1)
    api.fill("sell")
    connector.refresh(sell.order_id)
    clock[0] = timestamp(blocked_day + "T14:01:00Z")
    assert connector.cash().unsettled == 20
    with pytest.raises(OrderRejected, match="settled cash"):
        submit(setup, "again")
    clock[0] = timestamp(settled_day + "T14:00:00Z")
    assert connector.cash().available == 20
    assert submit(setup, "again").status == "open"


def test_short_sales_and_duplicate_sell_reservations_are_rejected(ready):
    connector, api, clock, *_ = ready
    with pytest.raises(OrderRejected, match="cannot short"):
        submit(ready, "short", side="sell")
    buy = submit(ready, "buy")
    clock[0] += timedelta(seconds=1)
    api.fill("buy")
    connector.refresh(buy.order_id)
    submit(ready, "sell", side="sell")
    with pytest.raises(OrderRejected, match="unreserved"):
        submit(ready, "sell2", side="sell", quantity="0.01")


def test_pending_buys_share_approved_equity_cap_across_strategies(setup):
    connector, api, clock, instrument, strategy, trial = setup
    api.account_row["cash"] = "300"
    connector.initialize_cash(D(300))
    # The approved equity cap is the $100 fixture allocation, not $25.
    submit(setup, quantity="0.9")
    with pytest.raises(OrderRejected, match="allocation"):
        submit(setup, "two", quantity="0.2")
    other = Strategy(key=strategy.key + "other", name="Other", venue_id=strategy.venue_id,
                     status="paper", allocation_usd=D(100))
    connector.session.add(other)
    connector.session.flush()
    other_trial = Trial(strategy_id=other.id, mode="paper")
    connector.session.add(other_trial)
    connector.session.flush()
    with pytest.raises(OrderRejected, match="pending buys"):
        submit((connector, api, clock, instrument, other, other_trial), "three", quantity="0.2")
    assert len(api.submissions) == 1


@pytest.mark.parametrize("veto", ["stale", "killed", "daily", "cap", "errors"])
def test_every_existing_risk_veto_prevents_http_orders(ready, veto):
    connector, api, clock, instrument, strategy, trial = ready
    quantity = "0.2"
    if veto == "stale":
        api.quote_age = timedelta(seconds=31)
    elif veto == "killed":
        strategy.status = "killed"
        connector.session.commit()
    elif veto == "daily":
        connector.risk.trigger_daily_halt("paper", D(-50), clock[0])
        connector.session.commit()
    elif veto == "cap":
        quantity = "1.01"
    elif veto == "errors":
        for _ in range(5):
            connector.risk.record_api_error(clock[0])
        connector.session.commit()
    with pytest.raises(OrderRejected):
        submit(ready, quantity=quantity)
    assert not api.submissions


def test_unknown_post_keeps_reservation_never_resubmits_and_can_be_polled(ready):
    connector, api, *_ = ready
    api.timeout_submit = True
    first = submit(ready)
    assert first.submission_unknown
    assert first.status == "pending"
    assert connector.cash().reserved == 20
    assert submit(ready).order_id == first.order_id
    assert len(api.submissions) == 1
    refreshed = connector.refresh(first.order_id)
    assert refreshed.status == "open"
    assert not refreshed.submission_unknown
    messages = list(connector.session.scalars(select(Incident.message).where(Incident.mode == "paper")))
    assert any("reservation retained" in msg for msg in messages)
    assert not any("credentials" in msg for msg in messages)


def test_api_failures_feed_the_existing_five_error_gate(ready, monkeypatch):
    connector, api, *_ = ready
    good = api.account
    def fail():
        raise RuntimeError("sensitive upstream exception")
    monkeypatch.setattr(api, "account", fail)
    for i in range(5):
        with pytest.raises(PaperAPIError, match="Alpaca paper API request failed"):
            submit(ready, str(i))
    monkeypatch.setattr(api, "account", good)
    with pytest.raises(OrderRejected, match="API error halt"):
        submit(ready, "after-errors")
    assert not api.submissions


@pytest.mark.parametrize("fault", ["missing_fx", "overfill", "limit", "gap", "wrong_symbol", "future"])
def test_bad_fills_never_partially_change_the_ledger(ready, fault):
    connector, api, clock, *_ = ready
    result = submit(ready)
    clock[0] += timedelta(seconds=1)
    row = api.fill("one", qty="0.1")
    if fault == "missing_fx":
        from sqlalchemy import delete
        connector.session.execute(delete(FxRate))
        connector.session.commit()
    elif fault == "overfill":
        row["qty"], row["cum_qty"] = "0.3", "0.3"
    elif fault == "limit":
        row["price"] = "101"
    elif fault == "gap":
        row["cum_qty"] = "0.2"
    elif fault == "wrong_symbol":
        row["symbol"] = "QQQ"
    elif fault == "future":
        row["transaction_time"] = (clock[0] + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        connector.refresh(result.order_id)
    assert connector.session.scalar(select(func.count()).select_from(Fill).where(Fill.order_id == result.order_id)) == 0
    assert connector.cash().reserved == 20


@pytest.mark.parametrize("fault", ["resting", "after_close", "blocked", "fractional", "account_changed", "trial", "allocation"])
def test_preflight_contract_failures(ready, fault):
    connector, api, clock, instrument, strategy, trial = ready
    price = "100"
    if fault == "resting":
        price = "99"
    elif fault == "after_close":
        clock[0] = timestamp("2026-09-30T20:00:00Z")
    elif fault == "blocked":
        api.account_row["trading_blocked"] = True
    elif fault == "fractional":
        api.asset_row["fractionable"] = False
    elif fault == "account_changed":
        api.account_row["id"] = "different-account"
    elif fault == "trial":
        trial.status = "complete"
        connector.session.commit()
    elif fault == "allocation":
        strategy.allocation_usd = D(10)
        connector.session.commit()
    with pytest.raises(OrderRejected):
        submit(ready, limit_price=price)
    assert not api.submissions


def test_activity_pagination_ignores_other_orders_and_preserves_execution_ids(ready):
    connector, api, clock, *_ = ready
    result = submit(ready)
    clock[0] += timedelta(seconds=1)
    api.fills.extend({"id": f"unrelated-{n}", "order_id": "someone-else",
                      "transaction_time": clock[0].isoformat()} for n in range(100))
    row = api.fill("one")
    assert connector.refresh(result.order_id).status == "filled"
    fills = list(connector.session.scalars(select(Fill).where(Fill.order_id == result.order_id)))
    assert len(fills) == 1
    assert fills[0].venue_fill_id == row["id"]


def test_changed_activity_id_contents_are_rejected(ready):
    connector, api, clock, *_ = ready
    result = submit(ready)
    clock[0] += timedelta(seconds=1)
    row = api.fill("one", qty="0.1")
    connector.refresh(result.order_id)
    row["price"] = "99"
    with pytest.raises(ValueError, match="changed contents"):
        connector.refresh(result.order_id)
    assert connector.cash().settled == 90


def test_unknown_response_cannot_match_another_intent(ready, monkeypatch):
    connector, api, *_ = ready
    original = api.submit
    def mismatch(payload):
        row = original(payload)
        row["side"] = "sell"
        return row
    monkeypatch.setattr(api, "submit", mismatch)
    first = submit(ready)
    assert first.submission_unknown
    existing = submit(ready)
    assert existing.status == "pending" and existing.submission_unknown
    assert connector.cash().reserved == 20
    assert len(api.submissions) == 1


def test_unrealized_loss_refreshes_and_persists_strategy_kill(ready, monkeypatch):
    connector, api, clock, _, strategy, _ = ready
    strategy.allocation_usd = D(25)
    connector.session.commit()
    result = submit(ready)
    clock[0] += timedelta(seconds=1)
    api.fill("one")
    connector.refresh(result.order_id)
    monkeypatch.setattr(api, "quote", lambda symbol: {"bp": 50, "ap": 50, "t": clock[0].isoformat()})
    with pytest.raises(OrderRejected, match="permanently killed"):
        submit(ready, "loss", quantity="0.1", limit_price="50")
    assert connector.session.get(Strategy, strategy.id, populate_existing=True).status == "killed"
    assert connector.session.scalar(select(RiskHalt.id).where(RiskHalt.strategy_id == strategy.id)) is not None
    assert len(api.submissions) == 1


def test_asset_registration_reuses_broker_asset_identity(ready):
    connector, api, _, instrument, *_ = ready
    assert connector.register_equity("SPY") == instrument.id
    assert connector.register_equity("SPY") == instrument.id


def test_second_session_fills_invalidate_cached_reservations(ready):
    from sqlalchemy.orm import Session
    connector, api, clock, *_ = ready
    result = submit(ready)
    cached = connector.session.get(Order, result.order_id)
    connector.session.commit()
    clock[0] += timedelta(seconds=1)
    api.fill("one", qty="0.05")
    with Session(bind=connector.session.get_bind(), expire_on_commit=False,
                 join_transaction_mode="create_savepoint") as second:
        AlpacaPaperConnector(second, api, now=lambda: clock[0]).refresh(result.order_id)
    assert cached.filled_size == 0  # demonstrate stale identity-map state
    assert connector.cash().reserved == 15
    assert connector.cash().available == 80
