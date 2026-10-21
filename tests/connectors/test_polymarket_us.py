from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from tradingbot.connectors.polymarket_us import NAME, OrderRejected, PolymarketUSConnector, USAPIError
from tradingbot.connectors.polymarket_us_wire import timestamp
from tradingbot.db.models import Fill, FxRate, Incident, Instrument, Market, Order, Strategy, Trial, Venue


def money(value):
    return {"value": str(value), "currency": "USD"}


class FakeUS:
    key_fingerprint = "test-only"

    def __init__(self, clock, slug):
        self.clock, self.slug = clock, slug
        self.calls, self.posts, self.cancels, self.orders = [], [], [], {}
        self.permissions = True
        self.timeout = False
        self.cancel_ack_only = False
        self.power = D(100)
        self.tick, self.minimum = D(".01"), D(".01")
        self.bbo_delay = timedelta(0)
        self.bad_response = None

    def verify_trading_key(self):
        if not self.permissions:
            raise ValueError("Unverified key")
        return "test-only verification"

    def market(self, slug):
        self.calls.append("market")
        return {"market": {"slug": slug, "active": True, "closed": False, "category": "Economics",
                           "orderPriceMinTickSize": self.tick, "minimumTradeQty": self.minimum}}

    def balances(self):
        self.calls.append("balances")
        return {"balances": [{"currency": "USD", "buyingPower": self.power}]}

    def bbo(self, slug):
        self.calls.append("bbo")
        self.clock[0] += self.bbo_delay
        return {"marketData": {"marketSlug": slug, "state": "MARKET_STATE_OPEN", "bestBid": money(".39"), "bestAsk": money(".41")}}

    def create(self, payload):
        self.posts.append(deepcopy(payload))
        vid = uuid4().hex
        self.orders[vid] = {"id": vid, "marketSlug": self.slug, "side": "ORDER_SIDE_BUY" if payload["action"] == "ORDER_ACTION_BUY" else "ORDER_SIDE_SELL",
                           "type": "ORDER_TYPE_LIMIT", "price": payload["price"], "quantity": payload["quantity"],
                           "cumQuantity": D(0), "leavesQuantity": payload["quantity"], "state": "ORDER_STATE_NEW"}
        if self.timeout:
            raise TimeoutError("secret-bearing SDK request must not escape")
        return self.bad_response if self.bad_response is not None else {"id": vid}

    def order(self, vid):
        self.calls.append("order")
        return {"order": deepcopy(self.orders[vid])}

    def cancel(self, vid, slug):
        self.cancels.append(vid)
        if not self.cancel_ack_only:
            self.orders[vid]["state"] = "ORDER_STATE_CANCELED"
            self.orders[vid]["leavesQuantity"] = D(0)

    def fill(self, vid, qty="1", price=".4", fee="0", aggressor=False):
        order = self.orders[vid]
        order["cumQuantity"] += D(qty)
        order["leavesQuantity"] = order["quantity"] - order["cumQuantity"]
        order["state"] = "ORDER_STATE_FILLED" if order["leavesQuantity"] == 0 else "ORDER_STATE_PARTIALLY_FILLED"
        return {"id": uuid4().hex, "tradeId": uuid4().hex, "order": deepcopy(order), "lastShares": qty,
                "lastPx": money(price), "commissionNotionalCollected": money(fee), "aggressor": aggressor,
                "type": "EXECUTION_TYPE_FILL" if order["leavesQuantity"] == 0 else "EXECUTION_TYPE_PARTIAL_FILL",
                "transactTime": self.clock[0].isoformat()}


@pytest.fixture
def live(session):
    clock = [timestamp("2026-09-30T18:00:00Z")]
    venue = session.scalar(select(Venue).where(Venue.key == "polymarket_us"))
    strategy = Strategy(key="pm-us-test-" + uuid4().hex, name="PM US connector test", venue_id=venue.id,
                        status="live", allocation_usd=D(100))
    market = Market(venue_id=venue.id, external_id="test-" + uuid4().hex, market_type="binary", category="Economics", status="open")
    session.add_all([strategy, market])
    session.flush()
    instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=market.external_id + ":yes",
                            instrument_type="binary_yes", currency="USD", contract_multiplier=D(1))
    trial = Trial(strategy_id=strategy.id, mode="live", params={"test": True})
    proof = Trial(strategy_id=strategy.id, mode="backtest", params=trial.params, status="complete", pnl_after_fees=D(1),
                  data_start=clock[0] - timedelta(days=10), data_end=clock[0] - timedelta(days=1))
    session.add_all([instrument, trial, proof, FxRate(base="USD", quote="GBP", rate=D(".8"),
                    ts=clock[0] - timedelta(hours=1), source="pm-us-test")])
    session.flush()
    api = FakeUS(clock, market.external_id)
    connector = PolymarketUSConnector(session, api, reviewed_instrument_ids=[instrument.id], now=lambda: clock[0])
    return connector, api, clock, instrument, strategy, trial, proof


def submit(live, request_id="one", side="buy", quantity="10", price=".4", maker_only=True):
    c, api, clock, i, s, t, p = live
    return c.submit_limit(request_id=request_id, instrument_id=i.id, strategy_id=s.id, trial_id=t.id,
        proof_trial_id=p.id, side=side, quantity=D(quantity), limit_price=D(price), maker_only=maker_only)


def test_constructor_no_io_and_submission_gtc_no_expiry(live):
    c, api, *_ = live
    assert api.calls == []
    result = submit(live)
    assert result.venue_order_id and not result.submission_unknown
    payload = api.posts[0]
    assert payload["quantity"] == D(10)
    assert payload["tif"] == "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    assert payload["participateDontInitiate"] is True
    assert "goodTillTime" not in payload and "clientOrderId" not in payload
    assert submit(live).order_id == result.order_id and len(api.posts) == 1
    with pytest.raises(ValueError, match="different intent"):
        submit(live, quantity="11")


@pytest.mark.parametrize("fault", ["timeout", "malformed"])
def test_uncertain_post_never_resends_and_reserves(live, fault):
    c, api, *_ = live
    if fault == "timeout":
        api.timeout = True
    else:
        api.bad_response = {}
    first = submit(live)
    assert first.submission_unknown and first.status == "pending"
    assert submit(live).order_id == first.order_id and len(api.posts) == 1
    with pytest.raises(OrderRejected, match="uncertain"):
        submit(live, request_id="two")
    vid = next(iter(api.orders))
    repaired = c.bind_order(first.order_id, vid)
    assert repaired.venue_order_id == vid and not repaired.submission_unknown


@pytest.mark.parametrize("fault", ["key", "paper", "proof_loss", "params", "future", "unreviewed", "no_instrument"])
def test_eligibility_prevents_post(live, fault):
    c, api, clock, i, s, t, p = live
    if fault == "key": api.permissions = False
    if fault == "paper": s.status = "paper"
    if fault == "proof_loss": p.pnl_after_fees = D(0)
    if fault == "params": p.params = {"other": True}
    if fault == "future": p.data_end = clock[0] + timedelta(days=1)
    if fault == "unreviewed": c.reviewed = frozenset()
    if fault == "no_instrument": i.instrument_type = "binary_no"
    c.session.commit()
    with pytest.raises(ValueError): submit(live)
    assert api.posts == []


@pytest.mark.parametrize("fault", ["kill", "daily", "api", "stale", "cap"])
def test_all_five_risk_vetoes_before_post(live, fault):
    c, api, clock, i, s, *_ = live
    if fault == "kill": c.risk.kill_strategy(s.id, "live", D(-40), clock[0])
    if fault == "daily": c.risk.trigger_daily_halt("live", D(-50), clock[0])
    if fault == "api":
        for _ in range(5): c.risk.record_api_error(clock[0])
    if fault == "stale": api.bbo_delay = timedelta(seconds=31)
    c.session.commit()
    with pytest.raises(OrderRejected): submit(live, quantity="70" if fault == "cap" else "10")
    assert api.posts == []


@pytest.mark.parametrize("fault", ["tick", "minimum", "cross", "cash", "allocation"])
def test_venue_and_budget_vetoes(live, fault):
    c, api, clock, i, s, *_ = live
    if fault == "minimum": api.minimum = D(11)
    if fault == "cash": api.power = D(3)
    if fault == "allocation":
        s.allocation_usd = D(3)
        c.session.commit()
    with pytest.raises(OrderRejected): submit(live, price=".405" if fault == "tick" else ".42" if fault == "cross" else ".4")
    assert not api.posts


def test_pending_orders_and_short_liability_count(live):
    submit(live, quantity="40")
    with pytest.raises(OrderRejected, match="cap"): submit(live, request_id="two", quantity="30")
    with pytest.raises(OrderRejected, match="cap"): submit(live, request_id="short", side="sell", quantity="30", price=".1", maker_only=False)


def test_fractional_partial_fills_deduplicate_and_use_reported_commission(live):
    c, api, clock, *_ = live
    result = submit(live, quantity="1.5")
    fill = api.fill(result.venue_order_id, qty=".5", fee="-.01")
    assert c.ingest_execution(fill) and c.ingest_execution(fill)
    rows = list(c.session.scalars(select(Fill).where(Fill.order_id == result.order_id)))
    assert len(rows) == 1 and rows[0].fee == D("-.01") and rows[0].usd_gbp_rate == D(".8")
    assert c.ingest_execution(api.fill(result.venue_order_id, qty="1"))
    assert c.refresh(result.order_id).status == "filled"


def test_reported_fill_recorded_despite_risk_halt_or_bad_price_liquidity(live):
    c, api, clock, i, s, *_ = live
    result = submit(live)
    c.risk.kill_strategy(s.id, "live", D(-40), clock[0])
    c.risk.trigger_daily_halt("live", D(-50), clock[0])
    c.session.commit()
    assert c.ingest_execution(api.fill(result.venue_order_id, price=".45", aggressor=True, fee=".03"))
    fill = c.session.scalar(select(Fill).where(Fill.order_id == result.order_id))
    assert fill.price == D(".45") and fill.fee == D(".03") and fill.liquidity == "taker"


def test_cancel_ack_and_execution_gap_do_not_release(live):
    c, api, *_ = live
    result = submit(live)
    api.cancel_ack_only = True
    assert c.cancel(result.order_id).status == "open"
    fill = api.fill(result.venue_order_id, qty="2")
    api.cancel_ack_only = False
    result = c.cancel(result.order_id)
    assert result.status == "pending" and result.execution_gap
    with pytest.raises(OrderRejected, match="executions"): submit(live, request_id="blocked")
    assert c.ingest_execution(fill)
    assert c.refresh(result.order_id).status == "canceled"


def test_old_open_state_does_not_reopen_canceled(live):
    c, api, *_ = live
    result = submit(live)
    old = api.order(result.venue_order_id)["order"]
    assert c.cancel(result.order_id).status == "canceled"
    assert c.ingest_execution({"type": "EXECUTION_TYPE_NEW", "order": old})
    assert c.session.get(Order, result.order_id).status == "canceled"


@pytest.mark.parametrize("fault", ["fx", "commission", "identity", "future", "conflict"])
def test_bad_execution_preserved_for_explicit_repair(live, fault):
    c, api, clock, *_ = live
    result = submit(live)
    fill = api.fill(result.venue_order_id)
    if fault == "fx": fill["transactTime"] = "1900-01-01T00:00:00Z"
    if fault == "commission": del fill["commissionNotionalCollected"]
    if fault == "identity": fill["order"]["quantity"] = 20
    if fault == "future": fill["transactTime"] = (clock[0] + timedelta(days=1)).isoformat()
    if fault == "conflict":
        assert c.ingest_execution(fill)
        fill["lastPx"] = money(".39")
    assert not c.ingest_execution(fill)
    order = c.session.get(Order, result.order_id)
    assert order.metadata_["pending_executions"] and order.metadata_["execution_gap"]
    assert c.session.scalar(select(Fill.id).where(Fill.order_id == order.id)) is None if fault != "conflict" else True


def test_missing_fx_can_be_retried_without_resubmitting(live):
    c, api, clock, *_ = live
    result = submit(live)
    c.session.execute(delete(FxRate).where(FxRate.base == "USD", FxRate.quote == "GBP"))
    c.session.commit()  # inside the fixture's outer rollback transaction
    fill = api.fill(result.venue_order_id)
    assert not c.ingest_execution(fill)
    c.session.add(FxRate(base="USD", quote="GBP", rate=D(".8"), ts=clock[0], source="pm-us-test"))
    c.session.commit()
    assert c.retry_pending(result.order_id) == 1
    assert not c.refresh(result.order_id).execution_gap
    assert len(api.posts) == 1


def test_initial_snapshot_ignored_unknown_execution_logged(live):
    c, api, *_ = live
    assert not c.handle_private_message('{"orderSubscriptionSnapshot":{"orders":[],"eof":true}}')
    assert not c.ingest_execution({"id": "unbound", "order": {"id": "unknown"}})
    assert c.session.scalar(select(Incident.id).where(Incident.message.contains("Unbound PM US")))
    assert api.posts == []


def test_unknown_execution_blocks_new_orders_until_explicit_binding(live):
    c, api, *_ = live
    api.timeout = True
    result = submit(live)
    vid = next(iter(api.orders))
    fill = api.fill(vid)
    assert not c.ingest_execution(fill)
    with pytest.raises(OrderRejected, match="Unbound"): submit(live, request_id="two")
    c.bind_order(result.order_id, vid)
    assert c.ingest_execution(fill)
    assert not c.refresh(result.order_id).execution_gap


def test_terminal_state_then_out_of_order_fill_and_duplicate(live):
    c, api, *_ = live
    result = submit(live, quantity="2")
    first = api.fill(result.venue_order_id)
    second = api.fill(result.venue_order_id)
    assert c.ingest_execution(second)
    assert c.refresh(result.order_id).execution_gap
    assert c.ingest_execution(first)
    assert c.ingest_execution(second)
    assert c.refresh(result.order_id).status == "filled"


def test_key_change_requires_explicit_ledger_migration(live):
    c, api, *_ = live
    result = submit(live)
    c.cancel(result.order_id)
    api.key_fingerprint = "other-key"
    with pytest.raises(OrderRejected, match="different key"): submit(live, request_id="two")


def test_stream_errors_are_counted_and_sanitized(live):
    c, api, clock, *_ = live
    for _ in range(5):
        assert not c.handle_private_message('{bad json')
    assert c.risk.api_error_rate_exceeded(clock[0])
    with pytest.raises(OrderRejected, match="API error"): submit(live)
    assert not api.posts


def test_synchronous_evidence_survives_interrupted_processing(live, monkeypatch):
    c, api, *_ = live
    create = api.create
    def synchronous(payload):
        response = create(payload)
        response["executions"] = [api.fill(response["id"], qty="1")]
        return response
    api.create = synchronous
    original = c.ingest_execution
    def crash(raw):
        raise RuntimeError("simulated worker interruption")
    monkeypatch.setattr(c, "ingest_execution", crash)
    with pytest.raises(RuntimeError, match="interruption"): submit(live)
    order = c.session.scalar(select(Order).where(Order.metadata_["request_id"].as_string() == "one",
                                                Order.metadata_["connector"].as_string() == NAME))
    assert order.venue_order_id and order.metadata_["pending_executions"]
    monkeypatch.setattr(c, "ingest_execution", original)
    assert c.retry_pending(order.id) == 1
    assert not c.refresh(order.id).execution_gap
    assert len(api.posts) == 1
