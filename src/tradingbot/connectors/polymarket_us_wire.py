"""Strict retail Amount/order/execution decoding (not institutional scales)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tradingbot.fees.core import aware, decimal_input

ZERO = Decimal(0)
FILL_TYPES = {"EXECUTION_TYPE_PARTIAL_FILL", "EXECUTION_TYPE_FILL"}
STATES = {"ORDER_STATE_NEW": "open", "ORDER_STATE_PENDING_NEW": "pending",
          "ORDER_STATE_PENDING_REPLACE": "pending", "ORDER_STATE_PENDING_CANCEL": "pending",
          "ORDER_STATE_PENDING_RISK": "pending", "ORDER_STATE_PARTIALLY_FILLED": "partially_filled",
          "ORDER_STATE_FILLED": "filled", "ORDER_STATE_CANCELED": "canceled",
          "ORDER_STATE_REJECTED": "rejected", "ORDER_STATE_EXPIRED": "expired"}


def amount(value, *, positive=False, places=10):
    number = decimal_input(value)
    if positive and number <= 0:
        raise ValueError("Expected positive amount")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise ValueError("Amount exceeds ledger precision")
    return number


def usd(value):
    if not isinstance(value, dict) or value.get("currency") != "USD" or "value" not in value:
        raise ValueError("Expected a retail USD Amount")
    return amount(value["value"], places=8)


def timestamp(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    aware(when)
    return when


@dataclass(frozen=True)
class OrderState:
    id: str
    slug: str
    side: str
    price: Decimal
    quantity: Decimal
    filled: Decimal
    remaining: Decimal
    state: str


def order_state(raw: dict) -> OrderState:
    side = {"ORDER_SIDE_BUY": "buy", "ORDER_SIDE_SELL": "sell"}[raw["side"]]
    if not raw.get("id") or not raw.get("marketSlug") or raw.get("type") != "ORDER_TYPE_LIMIT":
        raise ValueError("Expected identified limit order")
    price, qty = usd(raw["price"]), amount(raw["quantity"], positive=True)
    filled, remaining = amount(raw.get("cumQuantity", 0)), amount(raw.get("leavesQuantity", 0))
    state = STATES[raw["state"]]
    if (not 0 < price < 1 or not 0 <= filled <= qty or not 0 <= remaining <= qty - filled
            or (state == "filled" and filled != qty)):
        raise ValueError("Inconsistent order quantities/price")
    return OrderState(raw["id"], raw["marketSlug"], side, price, qty, filled, remaining, state)


@dataclass(frozen=True)
class ExecutionFill:
    id: str
    trade_id: str
    order: OrderState
    price: Decimal
    size: Decimal
    fee: Decimal
    liquidity: str
    time: datetime


def execution_fill(raw: dict) -> ExecutionFill | None:
    if raw.get("type") not in FILL_TYPES:
        return None
    order = order_state(raw["order"])
    size, price = amount(raw["lastShares"], positive=True), usd(raw["lastPx"])
    if (not raw.get("id") or not raw.get("tradeId") or type(raw.get("aggressor")) is not bool
            or not 0 < price < 1 or size > order.filled):
        raise ValueError("Execution is missing identity, quantities or liquidity evidence")
    # Commission is an Amount in retail API, already denominated in USD.
    # It is not the institutional scaled integer field with the same name.
    fee = usd(raw["commissionNotionalCollected"])
    if fee != fee.quantize(Decimal(".000001")):
        raise ValueError("Commission exceeds ledger precision")
    return ExecutionFill(raw["id"], raw["tradeId"], order, price, size, fee,
                         "taker" if raw["aggressor"] else "maker", timestamp(raw["transactTime"]))
