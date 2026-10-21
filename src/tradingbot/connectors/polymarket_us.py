"""Explicit PM US live execution, using a dedicated transaction-owning Session.

No constructor I/O, startup reconciliation, automatic retry or order expiry.
Local intent commits before POST. Only individual reported executions create
fills; unaccounted execution evidence keeps reservations and blocks new orders.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from functools import wraps
import json
import re

from sqlalchemy import select

from tradingbot.db.models import Fill, FxRate, Instrument, Market, Order, Position, Quote, Strategy, Trial, Venue
from tradingbot.fees import FeeFill, PM_US_STANDARD_2026_09_25, PolymarketUSOrderFees
from tradingbot.ledger import Ledger
from tradingbot.risk import RiskEngine, limits

from .polymarket_us_api import USAPI, exact_json
from .polymarket_us_wire import amount, execution_fill, order_state, timestamp, usd

NAME = "polymarket_us_live_v1"
ZERO = Decimal(0)
ACTIVE = ("pending", "open", "partially_filled")
TERMINAL = ("filled", "canceled", "expired", "rejected")


class OrderRejected(ValueError):
    """Local veto: this request did not reach the venue."""


class USAPIError(RuntimeError):
    def __init__(self, status_code=None):
        super().__init__("Polymarket US API request failed")
        self.status_code = status_code


@dataclass(frozen=True)
class ExecutionResult:
    order_id: int
    status: str
    venue_order_id: str | None
    submission_unknown: bool
    execution_gap: bool


def transaction(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self.session.rollback()
            raise
    return wrapped


def evidence(raw):
    # JSONB stores decimal evidence as strings, never binary floating point.
    return json.loads(exact_json(raw), parse_float=str)


class PolymarketUSConnector:
    def __init__(self, session, api: USAPI, *, reviewed_instrument_ids, now=None):
        self.session, self.api = session, api
        self.reviewed = frozenset(reviewed_instrument_ids)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ledger, self.risk = Ledger(session, auto_fee=False), RiskEngine(session)

    def _call(self, method, *args):
        try:
            return method(*args)
        except Exception as exc:
            self.risk.record_api_error(self.now())
            self.session.commit()
            raise USAPIError(getattr(exc, "status_code", None)) from None

    def _lock(self):
        venue = self.session.scalar(select(Venue).where(Venue.key == "polymarket_us")
                 .with_for_update().execution_options(populate_existing=True))
        if venue is None:
            raise ValueError("Seed Polymarket US first")
        self.session.expire_all()
        return venue

    def _orders(self, venue_id, *, active=False):
        query = select(Order).join(Instrument).where(Instrument.venue_id == venue_id, Order.mode == "live")
        if active:
            query = query.where(Order.status.in_(ACTIVE))
        return list(self.session.scalars(query))

    @staticmethod
    def _result(order):
        meta = order.metadata_ or {}
        return ExecutionResult(order.id, order.status, order.venue_order_id,
                               bool(meta.get("submission_unknown")), bool(meta.get("execution_gap")))

    def _owned(self, order_id):
        order = self.session.get(Order, order_id, populate_existing=True)
        meta = order.metadata_ if order else {}
        if (not order or order.mode != "live" or (meta or {}).get("connector") != NAME
                or meta.get("key_fingerprint") != self.api.key_fingerprint):
            raise ValueError("Order is outside this connector/key")
        return order

    def _incident(self, message, order=None, *, details=None):
        self.risk.log_incident(severity="warning", category="reconciliation", mode="live",
            strategy_id=order.strategy_id if order else None,
            instrument_id=order.instrument_id if order else None,
            message=message, details=details, ts=self.now())

    def _refresh_risk(self):
        marks = {}
        for iid in self.session.scalars(select(Position.instrument_id).where(
                Position.mode == "live", Position.status == "open").distinct()):
            quote = self.session.scalar(select(Quote).where(Quote.instrument_id == iid, Quote.time <= self.now())
                         .order_by(Quote.time.desc(), Quote.id.desc()).limit(1))
            if quote:
                mark = quote.mid if quote.mid is not None else quote.last
                if mark is None and quote.bid is not None and quote.ask is not None:
                    mark = (quote.bid + quote.ask) / 2
                if mark is not None:
                    marks[iid] = mark
        self.risk.refresh_halts("live", marks, now=self.now())

    @transaction
    def tick(self):
        self._lock()
        self._refresh_risk()
        self.session.commit()

    def _instrument(self, iid, venue_id):
        instrument = self.session.get(Instrument, iid)
        market = self.session.get(Market, instrument.market_id) if instrument else None
        if (iid not in self.reviewed or not instrument or instrument.venue_id != venue_id
                or instrument.instrument_type != "binary_yes" or instrument.currency != "USD"
                or instrument.contract_multiplier != 1 or not market or market.market_type != "binary"
                or market.status != "open" or not market.category or "sport" in market.category.lower()
                or instrument.external_id != market.external_id + ":yes"
                or (market.close_ts and market.close_ts <= self.now())
                or (instrument.expiry_ts and instrument.expiry_ts <= self.now())):
            raise OrderRejected("Only reviewed open standard non-sports PM US YES instruments are supported")
        return instrument, market

    def _proof(self, strategy_id, trial_id, proof_id, venue_id):
        strategy = self.session.get(Strategy, strategy_id, populate_existing=True)
        trial = self.session.get(Trial, trial_id, populate_existing=True)
        proof = self.session.get(Trial, proof_id, populate_existing=True)
        if not strategy or strategy.status != "live" or strategy.venue_id != venue_id or strategy.allocation_usd <= 0:
            raise OrderRejected("Existing live strategy and allocation required")
        if not trial or trial.strategy_id != strategy_id or trial.mode != "live" or trial.status != "running":
            raise OrderRejected("Running live trial required")
        if (not proof or proof.strategy_id != strategy_id or proof.mode != "backtest" or proof.status != "complete"
                or proof.params != trial.params or proof.pnl_after_fees is None or proof.pnl_after_fees <= 0
                or not proof.data_start or not proof.data_end or proof.data_end < proof.data_start
                or proof.data_end > self.now()):
            raise OrderRejected("Same-parameter profitable historical backtest required (PRD §4)")
        return strategy

    def _budget(self, venue, strategy, iid, side, qty, price, buying_power):
        binding = (venue.metadata_ or {}).get(NAME, {}).get("key_fingerprint")
        if binding is not None and binding != self.api.key_fingerprint:
            raise OrderRejected("Venue ledger belongs to a different key; explicit migration required")
        if (venue.metadata_ or {}).get(NAME, {}).get("unbound_executions"):
            raise OrderRejected("Unbound venue executions require explicit repair")
        orders = self._orders(venue.id, active=True)
        all_orders = self._orders(venue.id)
        if any((o.metadata_ or {}).get("execution_gap") or (o.metadata_ or {}).get("pending_executions")
               for o in all_orders):
            raise OrderRejected("Unresolved venue executions require explicit repair")
        if any((o.metadata_ or {}).get("connector") != NAME or (o.metadata_ or {}).get("submission_unknown")
               for o in orders):
            raise OrderRejected("Unmanaged or uncertain venue order requires explicit investigation")
        positions = list(self.session.scalars(select(Position).join(Instrument).where(
            Instrument.venue_id == venue.id, Position.mode == "live")))
        # Endpoints cover either side filling alone. Reserve by strategy first;
        # another strategy's position cannot finance this strategy's short.
        buckets = {}
        def bucket(sid, instrument_id):
            return buckets.setdefault((sid, instrument_id), [ZERO, ZERO, ZERO, price, price])
        for row in positions:
            b = bucket(row.strategy_id, row.instrument_id)
            b[0] += row.quantity
            b[3], b[4] = max(b[3], row.avg_price or price), min(b[4], row.avg_price or price)
        fee_reserve = {}
        for row in orders:
            b = bucket(row.strategy_id, row.instrument_id)
            b[1 if row.side == "buy" else 2] += row.size - row.filled_size
            b[3], b[4] = max(b[3], row.limit_price), min(b[4], row.limit_price)
            fee_reserve[row.strategy_id] = fee_reserve.get(row.strategy_id, ZERO) + self._fee_reserve(row.size - row.filled_size)
        b = bucket(strategy.id, iid)
        b[1 if side == "buy" else 2] += qty
        b[3], b[4] = max(b[3], price), min(b[4], price)
        fee_reserve[strategy.id] = fee_reserve.get(strategy.id, ZERO) + self._fee_reserve(qty)
        market_id = self.session.get(Instrument, iid).market_id
        market_exposure, allocation_exposure, pending_cost = ZERO, ZERO, ZERO
        for (sid, instrument_id), (held, buys, sells, high, low) in buckets.items():
            exposure = max(max(ZERO, held + buys) * high, max(ZERO, sells - held) * (1 - low))
            current = max(ZERO, held) * high + max(ZERO, -held) * (1 - low)
            pending_cost += max(ZERO, exposure - current)
            if sid == strategy.id:
                allocation_exposure += exposure
            if self.session.get(Instrument, instrument_id).market_id == market_id:
                market_exposure += exposure
        if market_exposure > limits.PER_MARKET_POSITION_MAX_USD:
            raise OrderRejected("Position and pending orders exceed the per-market cap")
        if allocation_exposure + fee_reserve[strategy.id] > strategy.allocation_usd + self.ledger.realized_after_fees(strategy_id=strategy.id, mode="live"):
            raise OrderRejected("Collateral and fee reserve exceed strategy allocation")
        if pending_cost + sum(fee_reserve.values(), ZERO) > buying_power:
            raise OrderRejected("Insufficient USD buying power after global pending reservations")

    @staticmethod
    def _fee_reserve(qty):
        # The published cumulative taker cap bounds fees at p(1-p) <= 1/4.
        # Reserve even for intended makers; never finance an order with a rebate.
        return (qty * PM_US_STANDARD_2026_09_25.taker_coefficient / 4).quantize(Decimal(".01"), rounding=ROUND_CEILING)

    @transaction
    def submit_limit(self, *, request_id, instrument_id, strategy_id, trial_id, proof_trial_id,
                     side, quantity, limit_price, maker_only=True):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id) or side not in ("buy", "sell") or type(maker_only) is not bool:
            raise ValueError("Invalid order intent")
        qty, price = amount(quantity, positive=True), amount(limit_price, positive=True, places=8)
        if not 0 < price < 1:
            raise ValueError("Binary limit must lie strictly between zero and one")
        venue = self._lock()
        def existing():
            return next((o for o in self._orders(venue.id) if (o.metadata_ or {}).get("connector") == NAME
                         and o.metadata_.get("request_id") == request_id), None)
        old = existing()
        if old:
            if ((old.instrument_id, old.strategy_id, old.trial_id, old.side, old.size, old.limit_price,
                 old.metadata_.get("maker_only"), old.metadata_.get("proof_trial_id"), old.metadata_.get("key_fingerprint"))
                != (instrument_id, strategy_id, trial_id, side, qty, price, maker_only, proof_trial_id, self.api.key_fingerprint)):
                raise ValueError("Request ID already names a different intent")
            result = self._result(old)
            self.session.commit()
            return result
        self._instrument(instrument_id, venue.id)
        self._proof(strategy_id, trial_id, proof_trial_id, venue.id)
        key_evidence = self.api.verify_trading_key()
        self.session.commit()
        _, market = self._instrument(instrument_id, venue.id)
        slug = market.external_id
        remote = self._call(self.api.market, slug)["market"]
        if (remote.get("slug") != slug or remote.get("active") is not True or remote.get("closed") is not False
                or not remote.get("category") or "sport" in remote["category"].lower()):
            raise OrderRejected("Venue market is not active non-sports")
        tick, minimum = amount(remote["orderPriceMinTickSize"], positive=True), amount(remote["minimumTradeQty"], positive=True)
        if price % tick or qty < minimum:
            raise OrderRejected("Price tick or minimum quantity does not match venue")
        balances = self._call(self.api.balances).get("balances", [])
        balances = [b for b in balances if b.get("currency") == "USD"]
        if len(balances) != 1:
            raise OrderRejected("Exactly one USD buying-power balance required")
        power = amount(balances[0]["buyingPower"])
        requested_at = timestamp(self.now())
        book = self._call(self.api.bbo, slug)["marketData"]
        bid, ask = usd(book["bestBid"]), usd(book["bestAsk"])
        if book.get("marketSlug") != slug or book.get("state") != "MARKET_STATE_OPEN" or not 0 < bid <= ask < 1:
            raise OrderRejected("Invalid/open market BBO required")
        venue = self._lock()
        if existing():
            self.session.commit()
            return self.submit_limit(request_id=request_id, instrument_id=instrument_id, strategy_id=strategy_id,
                trial_id=trial_id, proof_trial_id=proof_trial_id, side=side, quantity=qty, limit_price=price, maker_only=maker_only)
        self._instrument(instrument_id, venue.id)
        strategy = self._proof(strategy_id, trial_id, proof_trial_id, venue.id)
        self.session.add(Quote(instrument_id=instrument_id, time=requested_at, bid=bid, ask=ask,
                               metadata_={"connector": NAME, "source": "rest_bbo", "clock": "request_started"}))
        self.session.flush()
        self._refresh_risk()
        decision = self.risk.evaluate_order(instrument_id=instrument_id, strategy_id=strategy_id, mode="live",
                        side=side, size=qty, price=price, now=self.now())
        if not decision.allowed:
            self.session.commit()
            raise OrderRejected("; ".join(decision.reasons))
        if not 0 <= (self.now() - requested_at).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
            raise OrderRejected("BBO request is stale")
        if maker_only and ((side == "buy" and price >= ask) or (side == "sell" and price <= bid)):
            raise OrderRejected("Maker-only order would cross")
        self._budget(venue, strategy, instrument_id, side, qty, price, power)
        book_state = dict((venue.metadata_ or {}).get(NAME, {}))
        book_state["key_fingerprint"] = self.api.key_fingerprint
        venue.metadata_ = {**(venue.metadata_ or {}), NAME: book_state}
        payload = {"marketSlug": slug, "type": "ORDER_TYPE_LIMIT", "price": {"value": str(price), "currency": "USD"},
            "quantity": qty, "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL", "participateDontInitiate": maker_only,
            "outcomeSide": "OUTCOME_SIDE_YES", "action": "ORDER_ACTION_BUY" if side == "buy" else "ORDER_ACTION_SELL",
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC", "synchronousExecution": True, "maxBlockTime": "1"}
        order = self.ledger.record_order(instrument_id=instrument_id, strategy_id=strategy_id, trial_id=trial_id,
            mode="live", side=side, size=qty, limit_price=price, order_type="limit", status="pending",
            intended_liquidity="maker" if maker_only else "taker", metadata={"connector": NAME, "request_id": request_id,
            "slug": slug, "maker_only": maker_only, "proof_trial_id": proof_trial_id,
            "key_fingerprint": self.api.key_fingerprint, "key_permission_evidence": key_evidence,
            "fee_schedule": PM_US_STANDARD_2026_09_25.schedule_id, "submission_unknown": True})
        order.created_ts = order.submitted_ts = self.now()
        local_id = order.id
        self.session.commit()
        try:
            response = self._call(self.api.create, payload)
            venue_id = response["id"]
            if not isinstance(venue_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", venue_id):
                raise ValueError("Invalid venue order ID")
            executions = response.get("executions", [])
            if not isinstance(executions, list):
                raise ValueError("Invalid execution list")
            self._lock()
            order = self._owned(local_id)
            self._bind(order, venue_id)
            order.metadata_ = {**order.metadata_, "pending_executions": evidence(executions),
                               "execution_gap": bool(executions)}
            self.session.commit()  # ID and synchronous execution evidence survive a crash
        except Exception as exc:
            self.session.rollback()
            self._lock()
            order = self._owned(local_id)
            self._incident("PM US submit outcome unknown; no automatic resend", order, details={"error_type": type(exc).__name__})
            result = self._result(order)
            self.session.commit()
            return result
        for execution in response.get("executions", []):
            self.ingest_execution(execution)
        return self._result(self._owned(local_id))

    @transaction
    def bind_order(self, local_id, venue_id):
        """Explicit operator repair of unknown POST; never heuristic matching.

        GET must match the complete local intent. Identity equality is necessary,
        but the operator must establish that this is the actual submitted order.
        """
        raw = self._call(self.api.order, venue_id)["order"]
        self._lock()
        order = self._owned(local_id)
        self._identity(order, order_state(raw), expected_id=venue_id)
        self._bind(order, venue_id)
        self._state(order, order_state(raw))
        self.session.commit()
        return self._result(order)

    def _bind(self, order, venue_id):
        if order.venue_order_id and order.venue_order_id != venue_id:
            raise ValueError("Cannot rebind known venue order")
        collision = self.session.scalar(select(Order.id).where(Order.mode == "live", Order.venue_order_id == venue_id, Order.id != order.id))
        if collision:
            raise ValueError("Venue order is already bound")
        order.venue_order_id = venue_id
        order.metadata_ = {**order.metadata_, "submission_unknown": False}

    @staticmethod
    def _identity(order, state, expected_id=None):
        if ((expected_id or order.venue_order_id), order.metadata_["slug"], order.side, order.limit_price, order.size) != (
                state.id, state.slug, state.side, state.price, state.quantity):
            raise ValueError("Venue order identity differs from local intent")

    def _state(self, order, state):
        self._identity(order, state)
        meta = dict(order.metadata_)
        highest = max(amount(meta.get("reported_filled", 0)), state.filled)
        terminal = meta.get("terminal_state")
        if state.state in TERMINAL:
            terminal = state.state
        meta.update(reported_filled=str(highest), terminal_state=terminal)
        gap = highest != order.filled_size or bool(meta.get("pending_executions"))
        meta["execution_gap"] = gap
        order.metadata_ = meta
        if gap:
            order.status = "pending"  # retain reservation until individual executions arrive
        elif order.filled_size >= order.size:
            order.status = "filled"
        elif terminal:
            order.status = terminal
        else:
            order.status = "partially_filled" if order.filled_size else state.state
        if order.status in TERMINAL:
            order.closed_ts = self.now()

    @transaction
    def refresh(self, local_id):
        order = self._owned(local_id)
        if not order.venue_order_id:
            raise ValueError("Unknown POST requires explicit venue-ID repair")
        raw = self._call(self.api.order, order.venue_order_id)["order"]
        self._lock()
        order = self._owned(local_id)
        self._state(order, order_state(raw))
        result = self._result(order)
        self.session.commit()
        return result

    @transaction
    def cancel(self, local_id):
        self.api.verify_trading_key()
        order = self._owned(local_id)
        if not order.venue_order_id:
            raise ValueError("Cannot cancel an unknown venue order")
        self._call(self.api.cancel, order.venue_order_id, order.metadata_["slug"])
        return self.refresh(local_id)  # cancel acknowledgment alone releases nothing

    @transaction
    def ingest_execution(self, raw):
        """Explicit private-stream/synchronous execution; no snapshot reconciliation.

        Persist evidence first, including executions whose FX/fee data is missing.
        Replay that evidence explicitly with retry_pending() after repair.
        """
        venue = self._lock()
        venue_id = (raw.get("order") or {}).get("id")
        order = self.session.scalar(select(Order).where(Order.mode == "live", Order.venue_order_id == venue_id)) if venue_id else None
        if order is None:
            state = dict((venue.metadata_ or {}).get(NAME, {}))
            pending = list(state.get("unbound_executions", []))
            if evidence(raw) not in pending:
                pending.append(evidence(raw))
            state["unbound_executions"] = pending
            venue.metadata_ = {**(venue.metadata_ or {}), NAME: state}
            self._incident("Unbound PM US execution requires explicit assignment", details={"execution": evidence(raw)})
            self.session.commit()
            return False
        order = self._owned(order.id)
        saved = evidence(raw)
        pending = list(order.metadata_.get("pending_executions", []))
        if saved not in pending:
            pending.append(saved)
        order.metadata_ = {**order.metadata_, "pending_executions": pending, "execution_gap": True}
        self.session.commit()
        local_id = order.id
        try:
            self._lock()
            order = self._owned(local_id)
            state = order_state(raw["order"])
            self._identity(order, state)
            fill = execution_fill(raw)
            if fill:
                if fill.time > self.now():
                    raise ValueError("Future execution timestamp")
                old = self.session.scalar(select(Fill).where(Fill.order_id == order.id,
                    (Fill.venue_fill_id == fill.id) | (Fill.metadata_["trade_id"].as_string() == fill.trade_id)))
                if old:
                    if (old.price, old.size, old.fee, old.liquidity, old.fill_ts, old.metadata_["trade_id"]) != (
                            fill.price, fill.size, fill.fee, fill.liquidity, fill.time, fill.trade_id):
                        raise ValueError("Duplicate execution has conflicting economics")
                else:
                    if order.filled_size + fill.size > order.size:
                        raise ValueError("Execution total exceeds local order quantity")
                    rate = self.session.scalar(select(FxRate.rate).where(FxRate.base == "USD", FxRate.quote == "GBP",
                        FxRate.ts <= fill.time).order_by(FxRate.ts.desc()).limit(1))
                    if rate is None or rate <= 0:
                        raise ValueError("Dated USD/GBP rate missing")
                    model = PolymarketUSOrderFees(PM_US_STANDARD_2026_09_25)
                    for previous in self.session.scalars(select(Fill).where(Fill.order_id == order.id).order_by(Fill.fill_ts, Fill.id)):
                        model.charge(FeeFill(price=previous.price, quantity=previous.size, liquidity=previous.liquidity,
                                             side=previous.side, executed_at=previous.fill_ts))
                    expected = model.charge(FeeFill(price=fill.price, quantity=fill.size, liquidity=fill.liquidity,
                                             side=order.side, executed_at=fill.time)).net_fee
                    if expected != fill.fee:
                        self._incident("PM US reported commission differs from fee model", order,
                                       details={"expected": str(expected), "reported": str(fill.fee)})
                    if ((order.side == "buy" and fill.price > order.limit_price) or
                        (order.side == "sell" and fill.price < order.limit_price) or
                        (order.metadata_["maker_only"] and fill.liquidity != "maker")):
                        self._incident("PM US execution differs from order price/liquidity intent", order)
                    # A venue execution already happened. Risk cannot undo it.
                    self.ledger.record_fill(order=order, price=fill.price, size=fill.size, fee=fill.fee,
                        liquidity=fill.liquidity, fill_ts=fill.time, usd_gbp_rate=rate, venue_fill_id=fill.id,
                        metadata={"connector": NAME, "trade_id": fill.trade_id, "expected_fee": str(expected), "execution": saved})
            remaining = [item for item in order.metadata_.get("pending_executions", []) if item != saved]
            order.metadata_ = {**order.metadata_, "pending_executions": remaining}
            self._state(order, state)
            venue = self._lock()
            book = dict((venue.metadata_ or {}).get(NAME, {}))
            book["unbound_executions"] = [item for item in book.get("unbound_executions", []) if item != saved]
            venue.metadata_ = {**(venue.metadata_ or {}), NAME: book}
            self._refresh_risk()
            self.session.commit()
            return True
        except Exception as exc:
            self.session.rollback()
            self._lock()
            order = self._owned(local_id)
            self._incident("PM US execution quarantined; evidence retained for explicit repair", order,
                           details={"error_type": type(exc).__name__})
            self.session.commit()
            return False

    def retry_pending(self, local_id):
        order = self._owned(local_id)
        pending = list(order.metadata_.get("pending_executions", []))
        return sum(self.ingest_execution(raw) for raw in pending)

    @transaction
    def stream_error(self):
        """Sanitized callback for an explicit stream driver's error/disconnect."""
        self.risk.record_api_error(self.now())
        self._incident("PM US private stream interrupted; resting orders remain live")
        self.session.commit()

    def handle_private_message(self, raw_json):
        try:
            message = json.loads(raw_json, parse_float=Decimal)
            if not isinstance(message, dict):
                raise ValueError("Object required")
        except (ValueError, TypeError):
            self.stream_error()
            return False
        if message.get("error"):
            self.risk.record_api_error(self.now())
            self._incident("PM US private stream reported an error")
            self.session.commit()
            return False
        update = message.get("orderSubscriptionUpdate")
        if update is not None:
            return self.ingest_execution(update["execution"])
        # The API sends an initial order snapshot. Deliberately ignore it: PRD §9.
        return False
