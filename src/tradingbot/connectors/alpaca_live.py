"""Cash-account Alpaca LIVE execution on the shared ledger and risk engine (tradingbot-l3r).

Same public interface as ``AlpacaPaperConnector`` (``initialize_cash``,
``register_equity``, ``cash``, ``submit_limit``, ``refresh``, ``cancel``), with
``mode='live'`` orders/fills/positions and its own cash book in
``Venue.metadata['alpaca_live_v1']``. It is self-contained on purpose: during the
2026-10-08..15 execution freeze ``alpaca_paper.py`` and ``alpaca_api.py`` are
hashed into running paper cohorts' identities and must not change. Unify the two
behind one mode-parameterized base after the freeze.

Live-only rules on top of the paper contract (see connectors/README.md):

- **Keys:** ``ALPACA_LIVE_KEY``/``ALPACA_LIVE_SECRET`` from ``.env`` only. The
  transport refuses to construct without them, or with a paper (``PK``) key, and
  is pinned to ``https://api.alpaca.markets``. There are no transfer, withdrawal,
  funding or account-configuration methods. Keys must be trading-only (PRD §6).
- **Cash account only:** the broker account must report ``multiplier`` 1 and no
  shorting; a paper account number (``PA…``) is refused.
- **Risk:** every submission needs a running *live* trial and a positive
  allocation, and obeys the unchanged §6 ``RiskEngine`` in mode ``live``
  (−40% strategy kill, −$50 daily halt, position cap, 30 s stale data,
  5 API errors/minute). Limits are never edited here.
- **Kill switch:** ``engage_kill_switch(reason)`` persists on the venue, logs a
  ``kill_switch`` incident and cancels this connector's open live orders. Every
  submission is refused, across processes and restarts, until
  ``clear_kill_switch(note)``. Refresh and cancel stay available.
- **Dry run:** ``dry_run=True`` runs every gate and returns the payload it would
  send (``last_dry_run``) without reserving cash or calling submit.
- **Fees:** Alpaca books regulatory fees as separate FEE activities, not on
  fills. Each live fill records a conservative per-fill ceiling of the dated
  SEC/TAF/CAT schedule (``EquityFeeBook``), so local cash and P&L are never
  better than the broker's. Reconciling actual FEE activities is a follow-up.

Construction performs no network requests and no reconciliation (PRD §9).
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import re
from typing import Callable

from alpaca.common.enums import BaseURL
from alpaca.data.enums import DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.db.models import Fill, FxRate, Instrument, Market, Order, Position, Quote, Strategy, Trial, Venue
from tradingbot.ledger import Ledger
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.risk import RiskEngine
from tradingbot.risk import limits

from .alpaca_api import PaperAPI as BrokerAPI, _TimeoutAdapter
from .alpaca_paper import (ACTIVE, TERMINAL, ExecutionResult, OrderRejected, PaperAPIError,
                           PaperEvidenceUnavailable, PaperGuardContext as GuardContext,
                           PaperGuardResult as GuardResult, SettledQuotes, _transaction)
from .cash import CashBalance, CashMovement, MarketSession, NEW_YORK, amount, cash_balance, timestamp

MODE = "live"
NAME = "alpaca_live_v1"
KILL_SWITCH = "alpaca_live_kill_switch_v1"
CLIENT_PREFIX = "tbl-"
ZERO = Decimal(0)


class LiveAPIError(PaperAPIError):
    """Sanitized remote failure. Never expose the SDK's credential-bearing request."""

    def __init__(self, status_code: int | None = None):
        RuntimeError.__init__(self, "Alpaca live API request failed")
        self.status_code = status_code


class LiveEvidenceUnavailable(PaperEvidenceUnavailable):
    """Known fills were saved, but account risk evidence could not be checked."""


class KillSwitchEngaged(OrderRejected):
    """The persistent live kill switch is on; no order was sent."""


class AlpacaLiveAPI:
    """Official alpaca-py transport pinned to the live endpoint; retries disabled."""

    def __init__(self, key: str, secret: str) -> None:
        if not key or not secret:
            raise ValueError("Set ALPACA_LIVE_KEY and ALPACA_LIVE_SECRET in .env")
        if key.startswith("PK"):
            raise ValueError("ALPACA_LIVE_KEY looks like a paper key; refusing the live endpoint")
        self._trading = TradingClient(key, secret, paper=False, raw_data=True)
        if self._trading._base_url != BaseURL.TRADING_LIVE:
            raise ValueError("Live transport is not pinned to the live trading endpoint")
        self._data = StockHistoricalDataClient(key, secret, raw_data=True)
        for client in (self._trading, self._data):
            client._retry = 0
            client._session.mount("https://", _TimeoutAdapter(max_retries=0))

    @classmethod
    def from_env(cls, path: str | Path = ".env") -> "AlpacaLiveAPI":
        values = dotenv_values(path)
        return cls(values.get("ALPACA_LIVE_KEY") or "", values.get("ALPACA_LIVE_SECRET") or "")

    def account(self) -> dict:
        return self._trading.get_account()

    def asset(self, symbol: str) -> dict:
        return self._trading.get_asset(symbol)

    def calendar(self, day: date) -> list[dict]:
        # The SDK Calendar model drops settlement_date; retain the raw response.
        return self._trading.get("/calendar", {"start": day.isoformat(), "end": day.isoformat()})

    def quote(self, symbol: str) -> dict:
        quotes = self._data.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
        )
        return quotes[symbol]

    def submit(self, payload: dict) -> dict:
        # Raw POST keeps the decimal-string wire format for fractional shares.
        return self._trading.post("/orders", payload)

    def order(self, client_order_id: str) -> dict:
        return self._trading.get_order_by_client_id(client_order_id)

    def cancel(self, venue_order_id: str) -> None:
        self._trading.cancel_order_by_id(venue_order_id)

    def activities(self, after: datetime, page_token: str | None = None) -> list[dict]:
        params = {"after": after.isoformat(), "direction": "asc", "page_size": 100}
        if page_token is not None:
            params["page_token"] = page_token
        return self._trading.get("/account/activities/FILL", params)

    def close(self) -> None:
        self._trading._session.close()
        self._data._session.close()


class AlpacaLiveConnector:
    def __init__(self, session: Session, api: BrokerAPI | None, *, now: Callable[[], datetime] | None = None,
                 execution_guard: Callable | None = None, dry_run: bool = False):
        self.session = session
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.api = SettledQuotes(api, self.now) if api is not None else api
        self.ledger = Ledger(session, auto_fee=False)
        self.risk = RiskEngine(session)
        self.execution_guard = execution_guard
        self.dry_run = dry_run
        self.last_dry_run: dict | None = None

    # -- kill switch ---------------------------------------------------------
    @staticmethod
    def _kill_state(venue: Venue) -> dict:
        return (venue.metadata_ or {}).get(KILL_SWITCH) or {}

    def _require_unkilled(self, venue: Venue) -> None:
        state = self._kill_state(venue)
        if state.get("active"):
            raise KillSwitchEngaged("Live kill switch engaged: " + state.get("reason", ""))

    @_transaction
    def kill_switch(self) -> dict:
        state = self._kill_state(self._venue())
        self.session.commit()
        return dict(state)

    @_transaction
    def engage_kill_switch(self, reason: str) -> dict:
        """Refuse every new live order until cleared; cancel this connector's open orders."""
        if not reason or not reason.strip():
            raise ValueError("A kill-switch reason is required")
        venue = self._venue(lock=True)
        now = self.now()
        if not self._kill_state(venue).get("active"):
            venue.metadata_ = {**(venue.metadata_ or {}), KILL_SWITCH: {
                "active": True, "reason": reason.strip(), "engaged_at": now.isoformat()}}
            self.risk.log_incident(severity="critical", category="kill_switch", mode=MODE,
                                   message="Live kill switch engaged: " + reason.strip(),
                                   details={"connector": NAME})
        self.session.commit()
        open_ids = [o.id for o in self._orders(venue.id, active=True)]
        cancelled, failed = [], []
        for order_id in open_ids:
            try:
                if self.api is None:
                    raise RuntimeError("no transport")
                self.cancel(order_id)
                cancelled.append(order_id)
            except Exception:
                self.session.rollback()
                failed.append(order_id)
        if failed:
            self.risk.log_incident(severity="critical", category="kill_switch", mode=MODE,
                                   message="Kill switch could not cancel live orders; cancel them in Alpaca",
                                   details={"order_ids": failed})
            self.session.commit()
        return {"active": True, "cancel_requested": cancelled, "cancel_failed": failed}

    @_transaction
    def clear_kill_switch(self, note: str) -> dict:
        if not note or not note.strip():
            raise ValueError("Clearing the kill switch requires a note (who, why)")
        venue = self._venue(lock=True)
        state = self._kill_state(venue)
        if state.get("active"):
            venue.metadata_ = {**(venue.metadata_ or {}), KILL_SWITCH: {
                **state, "active": False, "cleared_at": self.now().isoformat(), "cleared_note": note.strip()}}
            self.risk.log_incident(severity="info", category="kill_switch", mode=MODE,
                                   message="Live kill switch cleared: " + note.strip(),
                                   details={"connector": NAME, "engaged": state})
        result = dict(self._kill_state(venue))
        self.session.commit()
        return result

    # -- shared plumbing (mirrors AlpacaPaperConnector with mode='live') ------
    def _guard(self, context: GuardContext) -> GuardResult | None:
        if self.execution_guard is None:
            if self._book(context.venue).get("guard_required"):
                raise OrderRejected("This live cash book requires its account evidence guard")
            return None
        result = self.execution_guard(self, context)
        if not isinstance(result, GuardResult):
            raise OrderRejected("Invalid account evidence guard result")
        values = [result.daily_pnl_offset, *result.strategy_pnl_offsets.values(), *result.marks.values()]
        values += [x for x in (result.cash_available, result.strategy_cash) if x is not None]
        if any(not isinstance(x, Decimal) or not x.is_finite() for x in values):
            raise OrderRejected("Non-finite or non-Decimal account evidence")
        if any(x <= ZERO for x in result.marks.values()):
            raise OrderRejected("Invalid account evidence mark")
        return result

    def _refresh_risk(self, evidence: GuardResult | None, now: datetime,
                      marks: dict[int, Decimal] | None = None) -> None:
        now = now.astimezone(timezone.utc)
        if evidence is None:
            self.risk.refresh_halts(MODE, marks=marks, now=now)
            return
        marks = {**(marks or {}), **evidence.marks}
        daily = self.risk.daily_pnl(MODE, now.date(), marks, now=now) + evidence.daily_pnl_offset
        if daily <= limits.GLOBAL_DAILY_HALT_USD:
            self.risk.trigger_daily_halt(MODE, daily, now)
        for strategy in self.session.scalars(select(Strategy).where(Strategy.allocation_usd > 0)):
            pnl = self.risk.strategy_pnl(strategy.id, MODE, marks) + evidence.strategy_pnl_offsets.get(strategy.id, ZERO)
            if pnl <= -limits.PER_STRATEGY_KILL_FRACTION * strategy.allocation_usd:
                self.risk.kill_strategy(strategy.id, MODE, pnl, now)

    def _call(self, method, *args):
        try:
            return method(*args)
        except Exception as exc:
            self.risk.record_api_error(self.now())
            self.session.commit()
            raise LiveAPIError(getattr(exc, "status_code", None)) from None

    def _venue(self, *, lock: bool = False) -> Venue:
        stmt = select(Venue).where(Venue.key == "alpaca")
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        venue = self.session.scalar(stmt)
        if venue is None:
            raise ValueError("Seed the Alpaca venue first")
        if lock:
            self.session.expire_all()
        return venue

    def _orders(self, venue_id: int, *, active: bool = False) -> list[Order]:
        stmt = select(Order).join(Instrument).where(Instrument.venue_id == venue_id, Order.mode == MODE)
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
            raise OrderRejected("Live account is not available for trading")
        if str(account.get("account_number", "")).startswith("PA"):
            raise OrderRejected("Paper account behind the live connector")
        if str(account.get("multiplier")) != "1" or account.get("shorting_enabled") is True:
            raise OrderRejected("Live trading requires a cash account (multiplier 1, no shorting)")
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
            raise OrderRejected("Initialize an explicit settled-cash live budget first")
        return book

    @_transaction
    def initialize_cash(self, initial_cash: Decimal) -> CashBalance:
        """Once-only live budget; never funds or transfers. Cannot be reset or increased here.

        The caller supplies the owner-approved live capital for this book, never
        more than the broker's settled cash.
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
                raise ValueError("Existing live cash book cannot be reset or increased")
        else:
            if self._orders(venue.id):
                raise ValueError("Existing Alpaca live orders need an explicit migration before initialization")
            if initial_cash > min(amount(account["cash"]), amount(account["buying_power"])):
                raise OrderRejected("Live budget exceeds broker cash/buying_power")
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
            raise ValueError("Unmanaged Alpaca live orders are outside this cash book")
        reserved = sum((
            (order.size - order.filled_size) * order.limit_price
            for order in orders if order.status in ACTIVE and order.side == "buy"
        ), ZERO)
        movements = []
        for fill in self.session.scalars(select(Fill).join(Instrument).where(
            Instrument.venue_id == venue.id, Fill.mode == MODE,
        )):
            metadata = fill.metadata_ or {}
            if metadata.get("connector") != NAME:
                raise ValueError("Unmanaged Alpaca live fills are outside this cash book")
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
            Instrument.venue_id == venue_id, Order.mode == MODE,
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

        A repeated intent returns its original local order and never resends.
        With ``dry_run`` every gate runs and nothing is reserved or sent.
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,44}", request_id) or side not in ("buy", "sell"):
            raise ValueError("Invalid request ID or side")
        qty, price = amount(quantity, positive=True), amount(limit_price, positive=True)
        if qty != qty.quantize(Decimal("0.000000001")):
            raise ValueError("Alpaca quantity supports at most nine decimal places")
        tick = Decimal("0.01") if price >= 1 else Decimal("0.0001")
        if price != price.quantize(tick):
            raise ValueError("Limit price does not align with Alpaca's price increment")
        client_id = CLIENT_PREFIX + request_id
        venue = self._venue(lock=True)
        existing = self._existing(venue.id, client_id)
        if existing:
            if (existing.instrument_id, existing.strategy_id, existing.trial_id, existing.side,
                existing.size, existing.limit_price) != (instrument_id, strategy_id, trial_id, side, qty, price):
                raise ValueError("Request ID already belongs to a different intent")
            result = self._result(existing)
            self.session.commit()
            return result
        self._require_unkilled(venue)
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
        if self._existing(venue.id, client_id) is not None:
            self.session.commit()
            return self.submit_limit(request_id=request_id, instrument_id=instrument_id,
                                     strategy_id=strategy_id, trial_id=trial_id, side=side,
                                     quantity=qty, limit_price=price)
        # Another process may have engaged the switch while the reads were in flight.
        self._require_unkilled(venue)
        now = self.now()
        book = self._book(venue)
        if book["account"] != self._fingerprint(account):
            raise OrderRejected("Live account differs from the initialized cash book")
        strategy = self.session.get(Strategy, strategy_id, populate_existing=True)
        trial = self.session.get(Trial, trial_id, populate_existing=True)
        if strategy is None or strategy.venue_id != venue.id or strategy.allocation_usd <= 0:
            raise OrderRejected("A positive live strategy allocation is required for risk accounting")
        if (trial is None or trial.strategy_id != strategy_id or trial.mode != MODE
                or trial.status != "running"):
            raise OrderRejected("A running live trial is required")
        marks = {instrument_id: (quote.bid + quote.ask) / 2}
        evidence = self._guard(GuardContext(
            phase="submit", now=now, venue=venue, instrument_id=instrument_id,
            strategy_id=strategy_id, trial_id=trial_id, side=side, quantity=qty,
            limit_price=price, market_session=market_session, quote=quote,
        ))
        self._refresh_risk(evidence, now, marks)
        decision = self.risk.evaluate_order(instrument_id=instrument_id, mode=MODE, side=side,
                                           size=qty, price=price, strategy_id=strategy_id, now=now)
        if not decision.allowed:
            self.session.commit()  # retain kills/incidents even though no HTTP order follows
            raise OrderRejected("; ".join(decision.reasons))
        if not market_session.is_open(now):
            raise OrderRejected("Only the regular trading session is supported")
        if not 0 <= (now - quote.time).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
            raise OrderRejected("Quote is stale")
        if (side == "buy" and price < quote.ask) or (side == "sell" and price > quote.bid):
            raise OrderRejected("This adapter supports marketable limits only")
        pending = self._orders(venue.id, active=True)
        balance = self._balance(venue, now)
        positions = list(self.session.scalars(select(Position).join(Instrument).where(
            Instrument.venue_id == venue.id, Position.mode == MODE,
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
                strategy_id=strategy_id, mode=MODE) - cost - reserved
            if evidence is not None and evidence.strategy_cash is not None:
                strategy_cash = min(strategy_cash, evidence.strategy_cash)
            if qty * price > strategy_cash:
                raise OrderRejected("Order exceeds this strategy's available allocation")
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
        if self.dry_run:
            self.last_dry_run = payload
            self.session.commit()  # quote and any risk trips only; no reservation
            return ExecutionResult(0, "dry_run", None, False)
        order = self.ledger.record_order(instrument_id=instrument_id, mode=MODE, side=side,
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
        except LiveAPIError:
            self.risk.log_incident(severity="critical", category="connectivity", mode=MODE,
                                   strategy_id=strategy_id, instrument_id=instrument_id,
                                   message="Alpaca live submit outcome unknown; reservation retained",
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
            self.risk.log_incident(severity="critical", category="connectivity", mode=MODE,
                                   strategy_id=strategy_id, instrument_id=instrument_id,
                                   message="Alpaca live submit response inconsistent; reservation retained",
                                   details={"order_id": result.order_id})
            self.session.commit()
            return result
        result = self._result(order)
        self.session.commit()
        return result

    def _owned(self, order_id: int) -> Order:
        order = self.session.get(Order, order_id, populate_existing=True)
        if order is None or order.mode != MODE or (order.metadata_ or {}).get("connector") != NAME:
            raise ValueError("Not an order owned by this live connector")
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
        if amount(row["filled_qty"]) > order.size:
            raise ValueError("Remote filled quantity exceeds order size")

    def _apply_response(self, order: Order, row: dict) -> None:
        self._validate_response(order, row)
        reported_qty = amount(row["filled_qty"])
        order.venue_order_id = row["id"]
        order.submitted_ts = timestamp(row["submitted_at"]) if row.get("submitted_at") else order.submitted_ts
        status = row["status"]
        order.metadata_ = {**order.metadata_, "submission_unknown": False,
                           "venue_status": status, "reported_filled_qty": str(reported_qty)}
        # Aggregate order fields never create synthetic fills; keep reserving
        # until individual activity records catch up.
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
        # A fresh book per fill ceils each fee to the cent: never below Alpaca's daily total.
        fee, evidence = EquityFeeBook().charge(day=calendar.trade_date, side=order.side, price=price, size=qty)
        self.ledger.record_fill(order=order, price=price, size=qty, fill_ts=fill_time,
                                liquidity="unknown", fee=fee, usd_gbp_rate=fx,
                                venue_fill_id=row["id"], metadata={
                                    "connector": NAME, "settlement_date": calendar.settlement_date.isoformat(),
                                    "fee_source": "estimated-per-fill-ceiling; actual FEE activities unreconciled",
                                    "fee_evidence": evidence,
                                    "fill_source": "alpaca-live-activity", "cum_qty": row["cum_qty"],
                                })

    @_transaction
    def refresh(self, order_id: int) -> ExecutionResult:
        """Explicit polling for one known intent; never called on startup."""
        order = self._owned(order_id)
        account = self._call(self.api.account)
        if self._book(self._venue())["account"] != self._fingerprint(account):
            raise ValueError("Live account differs from the initialized cash book")
        response = self._call(self.api.order, order.metadata_["client_order_id"])
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
        self.session.commit()
        venue = self._venue(lock=True)
        try:
            evidence = self._guard(GuardContext(phase="refresh", now=self.now(), venue=venue))
            self._refresh_risk(evidence, self.now())
        except Exception:
            self.session.rollback()
            self.risk.log_incident(severity="warning", category="connectivity", mode=MODE,
                                   message="Live fill recorded; account risk evidence unavailable",
                                   details={"order_id": result.order_id})
            self.session.commit()
            raise LiveEvidenceUnavailable("Live fill recorded; account risk evidence unavailable") from None
        self.session.commit()
        return result

    @_transaction
    def cancel(self, order_id: int) -> ExecutionResult:
        """Cancel only this connector's order; release nothing on a DELETE ack."""
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


def main() -> None:
    """Read-only live check and kill-switch control. No CLI order placement."""
    import argparse
    import json

    from tradingbot.db.session import SessionLocal

    parser = argparse.ArgumentParser(description=main.__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Read live account, asset, quote and calendar (needs live keys)")
    check.add_argument("--symbol", default="SPY")
    kill = commands.add_parser("kill", help="Engage the live kill switch and cancel open live orders")
    kill.add_argument("--reason", required=True)
    clear = commands.add_parser("clear-kill", help="Clear the live kill switch")
    clear.add_argument("--note", required=True)
    commands.add_parser("status", help="Show the live kill-switch state")
    args = parser.parse_args()
    if args.command == "check":
        try:
            api = AlpacaLiveAPI.from_env()
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        try:
            account, asset, quote = api.account(), api.asset(args.symbol), api.quote(args.symbol)
            now = datetime.now(timezone.utc)
            print(json.dumps({
                "endpoint": "live", "account_active": account.get("status") == "ACTIVE",
                "cash_account": str(account.get("multiplier")) == "1" and account.get("shorting_enabled") is not True,
                "trading_blocked": account.get("trading_blocked"), "symbol": args.symbol,
                "tradable": asset.get("tradable"), "fractionable": asset.get("fractionable"),
                "quote_fresh": 0 <= (now - timestamp(quote["t"])).total_seconds() <= limits.STALE_DATA_MAX_SECONDS,
                "calendar": api.calendar(now.astimezone(NEW_YORK).date()),
            }, indent=2))
        except Exception as exc:
            # SDK exceptions can carry authenticated request objects; do not print them.
            raise SystemExit(f"Live check failed ({type(exc).__name__})") from None
        finally:
            api.close()
        return
    api = None
    if args.command == "kill":
        try:
            api = AlpacaLiveAPI.from_env()
        except ValueError:
            api = None  # the switch still engages; open orders (if any) are reported
    try:
        with SessionLocal() as session:
            connector = AlpacaLiveConnector(session, api)
            if args.command == "kill":
                result = connector.engage_kill_switch(args.reason)
            elif args.command == "clear-kill":
                result = connector.clear_kill_switch(args.note)
            else:
                result = connector.kill_switch()
        print(json.dumps(result, indent=2, default=str))
    finally:
        if api is not None:
            api.close()


if __name__ == "__main__":
    main()
