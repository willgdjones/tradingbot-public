"""Cash-only Alpaca paper execution on the shared ledger and risk engine.

This object owns its Session's transactions: use a dedicated Session. The venue
row serializes cash/order/fill changes across connector processes. Submission
intent commits before HTTP; an uncertain response never releases reservations.
Construction performs no reconciliation or network requests (PRD §9).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from hashlib import sha256
import re
import time
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.db import enums
from tradingbot.db.models import Fill, FxRate, Instrument, Market, Order, Position, Quote, Strategy, Trial, Venue
from tradingbot.ledger import Ledger
from tradingbot.risk import RiskEngine
from tradingbot.risk import limits

from .alpaca_api import PaperAPI
from .cash import CashBalance, CashMovement, MarketSession, NEW_YORK, amount, cash_balance, timestamp

NAME = "alpaca_paper_v1"
ZERO = Decimal(0)
ACTIVE = (enums.OrderStatus.PENDING, enums.OrderStatus.OPEN, enums.OrderStatus.PARTIALLY_FILLED)
TERMINAL = {"filled": "filled", "canceled": "canceled", "expired": "expired", "rejected": "rejected"}
# Longest wait for this host's clock to reach a quote's event time. Free-IEX event
# times led this host's clock by tens of ms on 2026-10-06/07 (sntp -32 ms), so the
# freshest quotes failed every `0 <= now - t` check in _capture_quote / fresh_marks
# for services that do not already wrap their API (TOM, C05, C08). jev_intraday.py
# fixed this only for J1-J4 with its own SettledQuotes; wrapping the connector's api
# here covers the rest without moving J's identity. Mirrors jev_intraday.QUOTE_CLOCK_TOLERANCE.
QUOTE_CLOCK_TOLERANCE = timedelta(seconds=1)


class SettledQuotes:
    """Quote transport that returns only once this host's clock reaches the quote times.

    Waiting out a lead of at most ``QUOTE_CLOCK_TOLERANCE`` changes no timestamp,
    future-quote check or the 30-second stale limit; a larger lead is passed through
    and refused downstream exactly as before. Non-quote attributes are delegated
    unchanged, so order/account calls are untouched. Idempotent under double-wrapping
    (e.g. the jev Runner already wraps before constructing the connector): the second
    settle sees a non-positive lead and does not sleep.
    """

    def __init__(self, api, now, sleep=None):
        self._api, self._now, self._sleep = api, now, sleep or time.sleep

    def __getattr__(self, name):
        value = getattr(self._api, name)
        if name not in ("quote", "quotes") or not callable(value):
            return value

        def settled(*args, **kwargs):
            result = value(*args, **kwargs)
            self.settle(result.values() if name == "quotes" and isinstance(result, dict) else [result])
            return result
        return settled

    def settle(self, rows):
        now, leads = timestamp(self._now()), []
        for row in rows:
            try:
                leads.append(timestamp(row["t"]) - now)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        lead = max((d for d in leads if d <= QUOTE_CLOCK_TOLERANCE), default=timedelta(0))
        if lead > timedelta(0):
            self._sleep(lead.total_seconds())


class OrderRejected(ValueError):
    """A local pre-trade veto; no order was sent."""


class PaperEvidenceUnavailable(OrderRejected):
    """Known fills were saved, but account risk evidence could not be checked."""


class PaperAPIError(RuntimeError):
    """Sanitized remote failure. Never expose the SDK's credential-bearing request."""

    def __init__(self, status_code: int | None = None):
        super().__init__("Alpaca paper API request failed")
        self.status_code = status_code


@dataclass(frozen=True)
class ExecutionResult:
    order_id: int
    status: str
    venue_order_id: str | None
    submission_unknown: bool


@dataclass(frozen=True)
class PaperGuardContext:
    """Fresh locked account view; callbacks must not commit or perform I/O."""

    phase: str
    now: datetime
    venue: Venue
    instrument_id: int | None = None
    strategy_id: int | None = None
    trial_id: int | None = None
    side: str | None = None
    quantity: Decimal | None = None
    limit_price: Decimal | None = None
    market_session: MarketSession | None = None
    quote: Quote | None = None


@dataclass(frozen=True)
class PaperGuardResult:
    """Additional evidence, never authority to relax a connector cash ceiling."""

    cash_available: Decimal | None = None
    strategy_cash: Decimal | None = None
    marks: dict[int, Decimal] = field(default_factory=dict)
    strategy_pnl_offsets: dict[int, Decimal] = field(default_factory=dict)
    daily_pnl_offset: Decimal = ZERO
    details: dict = field(default_factory=dict)
    valid_until: datetime | None = None


def _transaction(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self.session.rollback()
            raise
    return wrapped


class AlpacaPaperConnector:
    def __init__(self, session: Session, api: PaperAPI, *, now: Callable[[], datetime] | None = None,
                 execution_guard: Callable | None = None):
        self.session = session
        self.now = now or (lambda: datetime.now(timezone.utc))
        # Settle a small quote clock-lead for every service, not just J (hwm).
        # None is preserved for the read-only connectors that never request quotes.
        self.api = SettledQuotes(api, self.now) if api is not None else api
        self.ledger = Ledger(session, auto_fee=False)
        self.risk = RiskEngine(session)
        self.execution_guard = execution_guard

    def _guard(self, context: PaperGuardContext) -> PaperGuardResult | None:
        if self.execution_guard is None:
            if self._book(context.venue).get("guard_required"):
                raise OrderRejected("This paper cash book requires its account evidence guard")
            return None
        result = self.execution_guard(self, context)
        if not isinstance(result, PaperGuardResult):
            raise OrderRejected("Invalid account evidence guard result")
        values = [result.daily_pnl_offset, *result.strategy_pnl_offsets.values(), *result.marks.values()]
        values += [x for x in (result.cash_available, result.strategy_cash) if x is not None]
        if any(not isinstance(x, Decimal) or not x.is_finite() for x in values):
            raise OrderRejected("Non-finite or non-Decimal account evidence")
        if any(x <= ZERO for x in result.marks.values()):
            raise OrderRejected("Invalid account evidence mark")
        return result

    def _refresh_risk(self, evidence: PaperGuardResult | None, now: datetime,
                      marks: dict[int, Decimal] | None = None) -> None:
        now = now.astimezone(timezone.utc)
        if evidence is None:
            self.risk.refresh_halts("paper", marks=marks, now=now)
            return
        # Apply income and omitted fees BEFORE evaluating the existing triggers.
        # A baseline refresh first could irreversibly kill an ex-income holding.
        marks = {**(marks or {}), **evidence.marks}
        daily = self.risk.daily_pnl("paper", now.date(), marks, now=now) + evidence.daily_pnl_offset
        if daily <= limits.GLOBAL_DAILY_HALT_USD:
            self.risk.trigger_daily_halt("paper", daily, now)
        for strategy in self.session.scalars(select(Strategy).where(Strategy.allocation_usd > 0)):
            pnl = self.risk.strategy_pnl(strategy.id, "paper", marks) + evidence.strategy_pnl_offsets.get(strategy.id, ZERO)
            if pnl <= -limits.PER_STRATEGY_KILL_FRACTION * strategy.allocation_usd:
                self.risk.kill_strategy(strategy.id, "paper", pnl, now)

    def _call(self, method, *args):
        try:
            return method(*args)
        except Exception as exc:
            self.risk.record_api_error(self.now())
            self.session.commit()
            raise PaperAPIError(getattr(exc, "status_code", None)) from None

    def _venue(self, *, lock: bool = False) -> Venue:
        stmt = select(Venue).where(Venue.key == "alpaca")
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        venue = self.session.scalar(stmt)
        if venue is None:
            raise ValueError("Seed the Alpaca venue first")
        if lock:
            # Another connector may have committed fills since this Session last
            # read a position/order. Never gate against its identity-map cache.
            self.session.expire_all()
        return venue

    def _orders(self, venue_id: int, *, active: bool = False) -> list[Order]:
        stmt = select(Order).join(Instrument).where(
            Instrument.venue_id == venue_id, Order.mode == "paper",
        )
        if active:
            stmt = stmt.where(Order.status.in_(ACTIVE))
        return list(self.session.scalars(stmt))

    @staticmethod
    def _fingerprint(account: dict) -> str:
        return sha256(account["id"].encode()).hexdigest()

    @staticmethod
    def _account_ok(account: dict) -> None:
        if account.get("status") != "ACTIVE" or any(
            account.get(key, True) for key in ("trading_blocked", "account_blocked", "trade_suspended_by_user")
        ):
            raise OrderRejected("Paper account is not available for trading")
        amount(account["cash"])
        amount(account["buying_power"])

    @staticmethod
    def _asset_ok(asset: dict, symbol: str) -> None:
        if (asset.get("symbol") != symbol or asset.get("class") != "us_equity"
                or asset.get("status") != "active" or asset.get("tradable") is not True):
            raise OrderRejected("Only active tradable US equities are supported")

    def _book(self, venue: Venue) -> dict:
        book = (venue.metadata_ or {}).get(NAME)
        if not book:
            raise OrderRejected("Initialize an explicit simulated settled-cash budget first")
        return book

    @_transaction
    def initialize_cash(self, initial_cash: Decimal) -> CashBalance:
        """Once-only virtual budget; never resets/funds the broker account.

        Caller supplies the intended paper allocation, never the broker's default
        $100k or leveraged buying power. Existing books cannot be increased here.
        """
        initial_cash = amount(initial_cash, positive=True)
        if initial_cash != initial_cash.quantize(Decimal("0.000001")):
            raise ValueError("Cash budget supports at most six decimal places")
        account = self._call(self.api.account)
        self._account_ok(account)
        venue = self._venue(lock=True)
        old = (venue.metadata_ or {}).get(NAME)
        fingerprint = self._fingerprint(account)
        if old:
            if amount(old["initial_cash"]) != initial_cash or old["account"] != fingerprint:
                raise ValueError("Existing paper cash book cannot be reset or increased")
        else:
            if self._orders(venue.id):
                raise ValueError("Existing Alpaca paper orders need an explicit migration before initialization")
            if initial_cash > min(amount(account["cash"]), amount(account["buying_power"])):
                raise OrderRejected("Simulated budget exceeds broker cash/buying_power")
            venue.metadata_ = {**(venue.metadata_ or {}), NAME: {
                "initial_cash": str(initial_cash), "account": fingerprint,
                "started_at": self.now().isoformat(),
            }}
            self.session.flush()
        balance = self._balance(venue, self.now())
        self.session.commit()
        return balance

    @_transaction
    def register_equity(self, symbol: str) -> int:
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", symbol):
            raise ValueError("Use a normalized US equity symbol")
        asset = self._call(self.api.asset, symbol)
        self._asset_ok(asset, symbol)
        venue = self._venue(lock=True)
        instrument = self.session.scalar(select(Instrument).where(
            Instrument.venue_id == venue.id, Instrument.external_id == asset["id"],
        ))
        if instrument is None:
            market = self.session.scalar(select(Market).where(
                Market.venue_id == venue.id, Market.external_id == symbol,
            ))
            if market is None:
                market = Market(venue_id=venue.id, external_id=symbol, title=symbol, market_type="equity")
                self.session.add(market)
                self.session.flush()
            instrument = Instrument(venue_id=venue.id, market_id=market.id,
                                    external_id=asset["id"], symbol=symbol,
                                    instrument_type="equity", currency="USD",
                                    contract_multiplier=Decimal(1))
            self.session.add(instrument)
            self.session.flush()
        result = instrument.id
        self.session.commit()
        return result

    def _balance(self, venue: Venue, now: datetime) -> CashBalance:
        book = self._book(venue)
        orders = self._orders(venue.id)
        if any((order.metadata_ or {}).get("connector") != NAME for order in orders):
            raise ValueError("Unmanaged Alpaca paper orders are outside this cash book")
        reserved = sum((
            (order.size - order.filled_size) * order.limit_price
            for order in orders if order.status in ACTIVE and order.side == "buy"
        ), ZERO)
        movements = []
        for fill in self.session.scalars(select(Fill).join(Instrument).where(
            Instrument.venue_id == venue.id, Fill.mode == "paper",
        )):
            metadata = fill.metadata_ or {}
            if metadata.get("connector") != NAME:
                raise ValueError("Unmanaged Alpaca paper fills are outside this cash book")
            movements.append(CashMovement(fill.side, fill.price * fill.size, fill.fee,
                                          date.fromisoformat(metadata["settlement_date"])))
        return cash_balance(amount(book["initial_cash"]), movements, reserved, now)

    @_transaction
    def cash(self) -> CashBalance:
        venue = self._venue(lock=True)
        result = self._balance(venue, self.now())
        self.session.commit()
        return result

    def _calendar(self, day: date) -> MarketSession:
        rows = self._call(self.api.calendar, day)
        if len(rows) != 1 or rows[0].get("date") != day.isoformat():
            raise OrderRejected("No matching trading/settlement session")
        return MarketSession.from_api(rows[0])

    def _capture_quote(self, instrument: Instrument) -> Quote:
        row = self._call(self.api.quote, instrument.symbol)
        # Market-data JSON numbers are quote observations. Order/fill/account
        # money uses decimal strings and never passes through float conversion.
        bid, ask = amount(str(row["bp"]), positive=True), amount(str(row["ap"]), positive=True)
        when = timestamp(row["t"])
        if ask < bid or when > self.now():
            raise OrderRejected("Invalid or future-dated quote")
        quote = Quote(instrument_id=instrument.id, time=when, bid=bid, ask=ask,
                      metadata_={"connector": NAME, "feed": "iex", "kind": "live_quote"})
        self.session.add(quote)
        self.session.flush()
        return quote

    def _existing(self, venue_id: int, client_id: str) -> Order | None:
        return self.session.scalar(select(Order).join(Instrument).where(
            Instrument.venue_id == venue_id, Order.mode == "paper",
            Order.metadata_["connector"].as_string() == NAME,
            Order.metadata_["client_order_id"].as_string() == client_id,
        ))

    @staticmethod
    def _result(order: Order) -> ExecutionResult:
        return ExecutionResult(order.id, order.status, order.venue_order_id,
                               bool((order.metadata_ or {}).get("submission_unknown")))

    @_transaction
    def submit_limit(self, *, request_id: str, instrument_id: int, strategy_id: int,
                     trial_id: int, side: str, quantity: Decimal, limit_price: Decimal) -> ExecutionResult:
        """Submit a regular-session, marketable DAY limit, including fractional qty.

        The strategy supplies a stable request_id. A repeated intent returns its
        original local order and never resends HTTP, even after an uncertain POST.
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,44}", request_id) or side not in ("buy", "sell"):
            raise ValueError("Invalid request ID or side")
        qty, price = amount(quantity, positive=True), amount(limit_price, positive=True)
        if qty != qty.quantize(Decimal("0.000000001")):
            raise ValueError("Alpaca quantity supports at most nine decimal places")
        tick = Decimal("0.01") if price >= 1 else Decimal("0.0001")
        if price != price.quantize(tick):
            raise ValueError("Limit price does not align with Alpaca's price increment")
        client_id = "tbp-" + request_id
        venue = self._venue(lock=True)
        existing = self._existing(venue.id, client_id)
        if existing:
            if (existing.instrument_id, existing.strategy_id, existing.trial_id, existing.side,
                existing.size, existing.limit_price) != (instrument_id, strategy_id, trial_id, side, qty, price):
                raise ValueError("Request ID already belongs to a different intent")
            result = self._result(existing)
            self.session.commit()
            return result
        # Release before network reads, then take a fresh lock for the gate and reservation.
        self.session.commit()
        instrument = self.session.get(Instrument, instrument_id)
        if (instrument is None or instrument.venue_id != venue.id or instrument.instrument_type != "equity"
                or instrument.currency != "USD" or instrument.contract_multiplier != 1):
            raise OrderRejected("Instrument must be an Alpaca USD equity")
        account = self._call(self.api.account)
        self._account_ok(account)
        asset = self._call(self.api.asset, instrument.symbol)
        self._asset_ok(asset, instrument.symbol)
        if instrument.external_id != asset["id"]:
            raise OrderRejected("Instrument does not match Alpaca asset ID")
        if qty != qty.to_integral_value() and asset.get("fractionable") is not True:
            raise OrderRejected("Asset does not support fractional shares")
        market_session = self._calendar(self.now().astimezone(NEW_YORK).date())
        quote = self._capture_quote(instrument)
        venue = self._venue(lock=True)
        # A second process may have reserved this id while the reads were in flight.
        if self._existing(venue.id, client_id) is not None:
            self.session.commit()
            return self.submit_limit(request_id=request_id, instrument_id=instrument_id,
                                     strategy_id=strategy_id, trial_id=trial_id, side=side,
                                     quantity=qty, limit_price=price)
        now = self.now()
        book = self._book(venue)
        if book["account"] != self._fingerprint(account):
            raise OrderRejected("Paper account differs from the initialized cash book")
        strategy = self.session.get(Strategy, strategy_id, populate_existing=True)
        trial = self.session.get(Trial, trial_id, populate_existing=True)
        if strategy is None or strategy.venue_id != venue.id or strategy.allocation_usd <= 0:
            raise OrderRejected("A positive paper strategy allocation is required for risk accounting")
        if (trial is None or trial.strategy_id != strategy_id or trial.mode != "paper"
                or trial.status != "running"):
            raise OrderRejected("A running paper trial is required")
        marks = {instrument_id: (quote.bid + quote.ask) / 2}
        evidence = self._guard(PaperGuardContext(
            phase="submit", now=now, venue=venue, instrument_id=instrument_id,
            strategy_id=strategy_id, trial_id=trial_id, side=side, quantity=qty,
            limit_price=price, market_session=market_session, quote=quote,
        ))
        self._refresh_risk(evidence, now, marks)
        decision = self.risk.evaluate_order(instrument_id=instrument_id, mode="paper", side=side,
                                           size=qty, price=price, strategy_id=strategy_id, now=now)
        if not decision.allowed:
            self.session.commit()  # retain kills/incidents even though no HTTP order follows
            raise OrderRejected("; ".join(decision.reasons))
        if not market_session.is_open(now):
            raise OrderRejected("Only the regular trading session is supported")
        if not 0 <= (now - quote.time).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
            raise OrderRejected("Quote is stale")
        if (side == "buy" and price < quote.ask) or (side == "sell" and price > quote.bid):
            raise OrderRejected("This adapter supports marketable limits only; resting makers need the paper engine")
        pending = self._orders(venue.id, active=True)
        balance = self._balance(venue, now)
        positions = list(self.session.scalars(select(Position).join(Instrument).where(
            Instrument.venue_id == venue.id, Position.mode == "paper",
        )))
        if any(p.quantity < 0 for p in positions):
            raise OrderRejected("Cash book contains a short position")
        held = sum((p.quantity for p in positions if p.strategy_id == strategy_id and p.instrument_id == instrument_id), ZERO)
        reserved_sells = sum((o.size - o.filled_size for o in pending
                              if o.side == "sell" and o.strategy_id == strategy_id and o.instrument_id == instrument_id), ZERO)
        if side == "sell" and qty > held - reserved_sells:
            raise OrderRejected("Sell exceeds unreserved owned shares; cash account cannot short")
        if side == "buy":
            ceiling = min(balance.available, amount(account["cash"]), amount(account["buying_power"]))
            if evidence is not None and evidence.cash_available is not None:
                ceiling = min(ceiling, evidence.cash_available)
            if qty * price > ceiling:
                raise OrderRejected("Insufficient settled cash or buying_power")
            cost = sum((p.cost_basis or ZERO for p in positions if p.strategy_id == strategy_id), ZERO)
            reserved = sum(((o.size - o.filled_size) * o.limit_price for o in pending
                            if o.side == "buy" and o.strategy_id == strategy_id), ZERO)
            strategy_cash = strategy.allocation_usd + self.ledger.realized_after_fees(
                strategy_id=strategy_id, mode="paper") - cost - reserved
            if evidence is not None and evidence.strategy_cash is not None:
                strategy_cash = min(strategy_cash, evidence.strategy_cash)
            if qty * price > strategy_cash:
                raise OrderRejected("Order exceeds this strategy's available allocation")
            # The foundation gate sees filled strategy positions. Include other
            # strategies and pending buys here so several orders cannot each use
            # the full approved asset-class cap independently.
            total_held = sum((p.quantity for p in positions if p.instrument_id == instrument_id), ZERO)
            buys = [o for o in pending if o.side == "buy" and o.instrument_id == instrument_id]
            exposure = total_held * max(price, quote.ask) + qty * price + sum(
                ((o.size - o.filled_size) * max(o.limit_price, quote.ask) for o in buys), ZERO)
            if exposure > self.risk.position_cap_usd(strategy_id, instrument_id):
                raise OrderRejected("Position plus pending buys exceed the per-market cap")
        payload = {"symbol": instrument.symbol, "side": side, "type": "limit",
                   "qty": str(qty), "limit_price": str(price), "time_in_force": "day",
                   "extended_hours": False, "client_order_id": client_id}
        if evidence is not None and evidence.valid_until is not None and self.now() >= evidence.valid_until:
            raise OrderRejected("Account evidence submission window expired")
        order = self.ledger.record_order(instrument_id=instrument_id, mode="paper", side=side,
                                        order_type="limit", size=qty, limit_price=price,
                                        strategy_id=strategy_id, trial_id=trial_id, status="pending",
                                        metadata={"connector": NAME, "client_order_id": client_id,
                                                  "payload": payload, "submission_unknown": True,
                                                  **({"account_evidence": evidence.details} if evidence is not None else {})})
        order.created_ts = now
        result = self._result(order)
        self.session.commit()  # durable reservation BEFORE any POST
        try:
            response = self._call(self.api.submit, payload)
        except PaperAPIError:
            self.risk.log_incident(severity="warning", category="connectivity", mode="paper",
                                   strategy_id=strategy_id, instrument_id=instrument_id,
                                   message="Alpaca paper submit outcome unknown; reservation retained",
                                   details={"order_id": result.order_id})
            self.session.commit()
            return result
        self._venue(lock=True)
        order = self._owned(result.order_id)
        try:
            self._apply_response(order, response)
        except (ValueError, KeyError, TypeError):
            self.session.rollback()
            self.risk.record_api_error(self.now())
            self.risk.log_incident(severity="warning", category="connectivity", mode="paper",
                                   strategy_id=strategy_id, instrument_id=instrument_id,
                                   message="Alpaca paper submit response inconsistent; reservation retained",
                                   details={"order_id": result.order_id})
            self.session.commit()
            return result
        result = self._result(order)
        self.session.commit()
        return result

    def _owned(self, order_id: int) -> Order:
        order = self.session.get(Order, order_id, populate_existing=True)
        if order is None or order.mode != "paper" or (order.metadata_ or {}).get("connector") != NAME:
            raise ValueError("Not an order owned by this paper connector")
        return order

    def _validate_response(self, order: Order, row: dict) -> None:
        payload = order.metadata_["payload"]
        for key in ("client_order_id", "symbol", "side", "type", "time_in_force"):
            if row.get(key) != payload[key]:
                raise ValueError("Remote order does not match durable intent")
        if amount(row["qty"]) != order.size or amount(row["limit_price"]) != order.limit_price:
            raise ValueError("Remote quantity/limit does not match intent")
        if order.venue_order_id is not None and order.venue_order_id != row["id"]:
            raise ValueError("Remote order ID changed")
        reported_qty = amount(row["filled_qty"])
        if reported_qty > order.size:
            raise ValueError("Remote filled quantity exceeds order size")

    def _apply_response(self, order: Order, row: dict) -> None:
        self._validate_response(order, row)
        reported_qty = amount(row["filled_qty"])
        order.venue_order_id = row["id"]
        order.submitted_ts = timestamp(row["submitted_at"]) if row.get("submitted_at") else order.submitted_ts
        status = row["status"]
        order.metadata_ = {**order.metadata_, "submission_unknown": False,
                           "venue_status": status, "reported_filled_qty": str(reported_qty)}
        # Aggregate order fields do not create synthetic fills. Keep reserving
        # until individual activity records catch up, including cancel/fill races.
        if order.status in ACTIVE:
            if status in TERMINAL and reported_qty == order.filled_size:
                if status == "filled" and reported_qty != order.size:
                    raise ValueError("Filled status has an incomplete quantity")
                order.status = TERMINAL[status]
                order.closed_ts = self.now()
            else:
                order.status = "partially_filled" if order.filled_size else "open"

    def _activities(self, venue_order_id: str, created_ts: datetime) -> list[dict]:
        token, seen, result = None, set(), []
        while True:
            page = self._call(self.api.activities, created_ts - timedelta(minutes=1), token)
            result.extend(row for row in page if row.get("order_id") == venue_order_id)
            if len(page) < 100:
                break
            token = page[-1]["id"]
            if token in seen:
                raise ValueError("Activity pagination repeated a cursor")
            seen.add(token)
        return sorted(result, key=lambda row: (timestamp(row["transaction_time"]), amount(row["cum_qty"])))

    def _record_activity(self, order: Order, row: dict, calendar: MarketSession) -> None:
        fill_time = timestamp(row["transaction_time"])
        price, qty = amount(row["price"], positive=True), amount(row["qty"], positive=True)
        if (row.get("activity_type") != "FILL" or row.get("type") not in ("fill", "partial_fill")
                or row["side"] != order.side or row["symbol"] != order.metadata_["payload"]["symbol"]
                or row["order_id"] != order.venue_order_id):
            raise ValueError("Fill activity does not match the order")
        existing = self.session.scalar(select(Fill).where(Fill.order_id == order.id, Fill.venue_fill_id == row["id"]))
        if existing:
            if (existing.price, existing.size, existing.fill_ts) != (price, qty, fill_time):
                raise ValueError("Repeated fill ID has changed contents")
            return
        if (fill_time > self.now() or fill_time < order.created_ts
                or fill_time.astimezone(NEW_YORK).date() != calendar.trade_date):
            raise ValueError("Fill timestamp is inconsistent with the order/calendar")
        if (order.side == "buy" and price > order.limit_price) or (order.side == "sell" and price < order.limit_price):
            raise ValueError("Fill violates the limit price")
        if qty + order.filled_size > order.size or amount(row["cum_qty"]) != qty + order.filled_size:
            raise ValueError("Fill activity has a gap or exceeds the order quantity")
        if price != price.quantize(Decimal("0.00000001")) or qty != qty.quantize(Decimal("0.000000001")):
            raise ValueError("Fill precision exceeds supported ledger precision")
        fx = self.session.scalar(select(FxRate.rate).where(
            FxRate.base == "USD", FxRate.quote == "GBP", FxRate.ts <= fill_time,
        ).order_by(FxRate.ts.desc()).limit(1))
        if fx is None or fx <= 0:
            raise ValueError("A dated USD/GBP rate is required before recording fills")
        self.ledger.record_fill(order=order, price=price, size=qty, fill_ts=fill_time,
                                liquidity="unknown", fee=ZERO, usd_gbp_rate=fx,
                                venue_fill_id=row["id"], metadata={
                                    "connector": NAME, "settlement_date": calendar.settlement_date.isoformat(),
                                    "fee_source": "alpaca-paper-omits-regulatory-fees",
                                    "fill_source": "alpaca-paper-activity", "cum_qty": row["cum_qty"],
                                })

    @_transaction
    def refresh(self, order_id: int) -> ExecutionResult:
        """Explicit polling for one known intent; never called on startup."""
        order = self._owned(order_id)
        account = self._call(self.api.account)
        if self._book(self._venue())["account"] != self._fingerprint(account):
            raise ValueError("Paper account differs from the initialized cash book")
        response = self._call(self.api.order, order.metadata_["client_order_id"])
        # Validate identity before consuming any remote executions.
        self._validate_response(order, response)
        rows = self._activities(response["id"], order.created_ts)
        calendars = {day: self._calendar(day) for day in {
            timestamp(row["transaction_time"]).astimezone(NEW_YORK).date() for row in rows
        }}
        venue = self._venue(lock=True)
        order = self._owned(order_id)
        self._validate_response(order, response)
        order.venue_order_id = response["id"]
        for row in rows:
            day = timestamp(row["transaction_time"]).astimezone(NEW_YORK).date()
            self._record_activity(order, row, calendars[day])
        self._apply_response(order, response)
        result = self._result(order)
        if self.execution_guard is None and not self._book(venue).get("guard_required"):
            self._refresh_risk(None, self.now())
            self.session.commit()
            return result
        # Fill evidence must survive a missing mark or failed account review.
        # Reconciliation stays possible even while new submissions are held.
        self.session.commit()
        venue = self._venue(lock=True)
        try:
            evidence = self._guard(PaperGuardContext(phase="refresh", now=self.now(), venue=venue))
            self._refresh_risk(evidence, self.now())
        except Exception:
            self.session.rollback()
            self.risk.log_incident(severity="warning", category="connectivity", mode="paper",
                                   message="Paper fill recorded; account risk evidence unavailable",
                                   details={"order_id": result.order_id})
            self.session.commit()
            raise PaperEvidenceUnavailable("Paper fill recorded; account risk evidence unavailable") from None
        self.session.commit()
        return result

    @_transaction
    def cancel(self, order_id: int) -> ExecutionResult:
        """Cancel only this connector's order; release nothing on a DELETE ack."""
        # Resolve identity, account fingerprint and fills before cancellation.
        # Cancellation remains available even while submission risk gates veto.
        try:
            self.refresh(order_id)
        except PaperEvidenceUnavailable:
            pass  # evidence holds must never prevent cancellation of a known intent
        order = self._owned(order_id)
        if order.status in ACTIVE:
            self._call(self.api.cancel, order.venue_order_id)
        try:
            return self.refresh(order_id)
        except PaperEvidenceUnavailable:
            return self._result(self._owned(order_id))
