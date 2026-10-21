"""Isolated forward equity simulator; it never writes broker ledger tables.

Only marketable taker orders are supported. A fresh observed BBO supplies
execution prices and displayed-size ceilings; bars never manufacture fills.
Maker requests are rejected (the PM engine's strict trade-through rule remains
unchanged). State is JSON-serializable for atomic storage with its trial.
"""
from copy import deepcopy
from datetime import UTC, date
from decimal import Decimal as D, ROUND_DOWN

from tradingbot.connectors.cash import NEW_YORK, CashMovement, cash_balance, timestamp
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.risk import limits

ZERO = D(0)
QTY = D(".000000001")


class EquityPaperBook:
    def __init__(self, allocation, state=None):
        self.allocation = D(allocation)
        if not self.allocation.is_finite() or self.allocation <= 0:
            raise ValueError("Positive virtual allocation required")
        self.state = deepcopy(state or {"fills": [], "attempts": {}, "positions": {}})
        self.fees = EquityFeeBook()
        for fill in self.state["fills"]:
            self.fees.charge(day=timestamp(fill["at"]).astimezone(NEW_YORK).date(), side=fill["side"],
                             price=D(fill["price"]), size=D(fill["quantity"]))

    def cash(self, now):
        movements = [CashMovement(f["side"], D(f["price"])*D(f["quantity"]), D(f["fee"]),
                                 date.fromisoformat(f["settlement_date"])) for f in self.state["fills"]]
        return cash_balance(self.allocation, movements, ZERO, now)

    def entered(self, day):
        return frozenset(f["symbol"] for f in self.state["fills"]
                         if f["side"] == "buy" and timestamp(f["at"]).astimezone(NEW_YORK).date() == day)

    def net(self, quotes):
        gross = sum(((D(f["price"])*D(f["quantity"])*(1 if f["side"] == "sell" else -1)
                      - D(f["fee"])) for f in self.state["fills"]), ZERO)
        for symbol, pos in self.state["positions"].items():
            gross += D(pos["quantity"]) * D(str(quotes[symbol]["bp"]))
        return gross

    def mark_risk(self, quotes, now, *, cohort_daily=None):
        """Persist the same loss thresholds in the isolated virtual account."""
        net = self.net(quotes)
        today = timestamp(now).astimezone(UTC).date().isoformat()
        starts = self.state.setdefault("daily_start_net", {})
        starts.setdefault(today, self.state.get("last_marked_net", "0"))
        daily = net-D(starts[today])
        self.state["last_marked_net"] = str(net)
        if net <= -limits.PER_STRATEGY_KILL_FRACTION*self.allocation:
            self.state["killed"] = True
        halts = self.state.setdefault("daily_halts", [])
        if (daily <= limits.GLOBAL_DAILY_HALT_USD or
                cohort_daily is not None and cohort_daily <= limits.GLOBAL_DAILY_HALT_USD) and today not in halts:
            halts.append(today)
        return {"net": net, "daily": daily,
                "allowed": not self.state.get("killed") and today not in halts}

    def execute(self, *, identity, symbol, side, quantity, quote, now, market,
                stop_distance=None, allowed=True, liquidity="taker"):
        if identity in self.state["attempts"]:
            return self.state["attempts"][identity]
        if liquidity != "taker":
            raise ValueError("Virtual equity makers require later trade-through evidence")
        self.state["attempts"][identity] = None
        try:
            now = timestamp(now)
            when = timestamp(quote["t"])
            bid, ask = D(str(quote["bp"])), D(str(quote["ap"]))
            qty = D(quantity).quantize(QTY, rounding=ROUND_DOWN)
            depth = D(str(quote.get("as" if side == "buy" else "bs", 0)))
        except (ArithmeticError, KeyError, TypeError, ValueError):
            return None
        # Raw IEX sizes are not converted into fabricated share depth. A whole
        # positive size supports a conservative one-share lower bound whether
        # its unit is a share or a round lot. Unknown/fractional size fills zero.
        if (not allowed or side not in {"buy", "sell"} or not market.is_open(now)
                or not market.is_open(when) or not 0 <= (now-when).total_seconds() <= limits.STALE_DATA_MAX_SECONDS
                or not all(v.is_finite() for v in (bid, ask, qty, depth))
                or bid <= 0 or ask < bid or qty <= 0 or depth < 1):
            return None
        positions = self.state["positions"]
        old = positions.get(symbol)
        price = ask if side == "buy" else bid
        qty = min(qty, D(1)).quantize(QTY, rounding=ROUND_DOWN)
        if side == "buy":
            if old or symbol in self.entered(market.trade_date):
                return None
            qty = min(qty, self.allocation/price,
                      max(ZERO, self.cash(now).available-D(".01"))/price).quantize(QTY, rounding=ROUND_DOWN)
        else:
            qty = min(qty, D(old["quantity"]) if old else ZERO)
        if qty <= 0:
            return None
        fee, _ = self.fees.charge(day=market.trade_date, side=side, price=price, size=qty)
        fill = {"id": identity, "symbol": symbol, "side": side, "quantity": str(qty),
                "price": str(price), "fee": str(fee), "at": now.isoformat(),
                "settlement_date": market.settlement_date.isoformat(), "quote": deepcopy(quote)}
        self.state["fills"].append(fill)
        self.state["attempts"][identity] = fill
        if side == "buy":
            positions[symbol] = {"quantity": str(qty), "avg_price": str(price),
                                 "stop_distance": str(stop_distance) if stop_distance else None}
        else:
            remaining = D(old["quantity"])-qty
            if remaining:
                positions[symbol] = {**old, "quantity": str(remaining)}
            else:
                positions.pop(symbol)
        return fill
