import base64
from decimal import Decimal as D
import json

import httpx
import pytest

from tradingbot.connectors.polymarket_us_api import PolymarketUSAPI, TradingKeyPolicy, _ExactClient, exact_json
from tradingbot.connectors.polymarket_us_wire import execution_fill, order_state


def api_with_transport(handler, *, approved=True):
    api = PolymarketUSAPI("test-key", base64.b64encode(bytes(32)).decode())
    if approved:
        api.key_policy = TradingKeyPolicy(api.key_fingerprint, "test-only verification", True, False)
    api._sdk._http.close()
    api._sdk._http = _ExactClient(transport=httpx.MockTransport(handler))
    return api


def test_official_sdk_decimal_json_and_no_post_retries():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=b'{"balances":[{"currency":"USD","buyingPower":12.123456789}]}')
        assert request.content == b'{"marketSlug":"example","quantity":0.1234567890}'
        return httpx.Response(503, json={"message": "transient"})

    api = api_with_transport(handler)
    assert api.balances()["balances"][0]["buyingPower"] == D("12.123456789")
    with pytest.raises(Exception):
        api.create({"marketSlug": "example", "quantity": D(".1234567890")})
    assert len(requests) == 2 and requests[1].url.host == "api.polymarket.us"
    assert "X-PM-Signature" in requests[1].headers
    api.close()


@pytest.mark.parametrize("policy", [None, (False, False), (True, True)])
def test_unverified_or_withdrawal_capable_keys_cannot_trade(policy):
    requests = []
    api = api_with_transport(lambda request: requests.append(request), approved=False)
    if policy:
        api.key_policy = TradingKeyPolicy(api.key_fingerprint, "test", *policy)
    with pytest.raises(ValueError, match="key|permissions"):
        api.create({})
    assert requests == []
    api.close()


def test_trading_key_policy_is_bound_to_key_and_evidence():
    with pytest.raises(ValueError):
        TradingKeyPolicy("one", "source", True, False).verify("two")
    with pytest.raises(ValueError):
        TradingKeyPolicy("one", "", True, False).verify("one")


def test_float_and_nonfinite_wire_values_rejected():
    for value in (0.1, D("NaN"), D("Infinity")):
        with pytest.raises((ValueError, TypeError)):
            exact_json({"quantity": value})
    assert json.loads(exact_json({"a": [True, None, "quoted \" string", 1]}))["a"][0] is True


def test_resource_identifiers_cannot_escape_endpoint():
    api = api_with_transport(lambda request: pytest.fail("network should not be called"))
    with pytest.raises(ValueError):
        api.order("../../funding")
    api.close()


def wire_order(**kw):
    return {"id": "venue-order", "marketSlug": "example", "side": "ORDER_SIDE_BUY", "type": "ORDER_TYPE_LIMIT",
            "price": {"value": ".4", "currency": "USD"}, "quantity": 10, "cumQuantity": 4, "leavesQuantity": 6,
            "state": "ORDER_STATE_PARTIALLY_FILLED", **kw}


def wire_fill(**kw):
    return {"id": "execution-one", "tradeId": "trade-one", "order": wire_order(),
            "lastShares": "4", "lastPx": {"value": ".4", "currency": "USD"},
            "type": "EXECUTION_TYPE_PARTIAL_FILL", "aggressor": False,
            "commissionNotionalCollected": {"value": "-.01", "currency": "USD"},
            "transactTime": "2026-09-30T18:00:02Z", **kw}


def test_retail_commission_is_usd_amount_not_scaled_integer():
    fill = execution_fill(wire_fill())
    assert fill.fee == D("-.01") and fill.size == 4 and fill.liquidity == "maker"
    assert execution_fill({"type": "EXECUTION_TYPE_CANCELED"}) is None


@pytest.mark.parametrize("change", [
    {"lastShares": "0"}, {"lastShares": "5"}, {"aggressor": None}, {"tradeId": ""},
    {"lastPx": {"value": ".4", "currency": "USDC"}},
    {"commissionNotionalCollected": 100}, {"transactTime": "2026-09-30T18:00:02"},
])
def test_malformed_execution_is_not_an_accounting_record(change):
    with pytest.raises((ValueError, TypeError)):
        execution_fill(wire_fill(**change))


def test_order_cumulative_quantity_cannot_exceed_original():
    with pytest.raises(ValueError):
        order_state(wire_order(cumQuantity=11))


def test_private_socket_passes_raw_decimal_json_without_connecting():
    api = api_with_transport(lambda request: pytest.fail("No HTTP expected"))
    received = []
    socket = api.private_socket(received.append)
    assert not socket.is_connected
    raw = '{"orderSubscriptionUpdate":{"quantity":0.1234567890123456789}}'
    socket._handle_message(raw)
    assert received == [raw]
    assert json.loads(received[0], parse_float=D)["orderSubscriptionUpdate"]["quantity"] == D(".1234567890123456789")
    api.close()
