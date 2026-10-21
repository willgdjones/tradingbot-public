"""IBS QQQ v1 with real money on its $140 slot (tradingbot-752).

Owner override, 2026-10-14 (PRD §4): the research version that passed its single
holdout (trial 8804, +$71.48 over 98 trades) goes live without a paper stage.
The §6 limits are unchanged and enforced by ``AlpacaLiveConnector``'s
``RiskEngine``.

- **Signal:** the unchanged ``strategy.ibs.Signal``, stepped once per completed
  session on Alpaca **SIP** daily bars (raw), never IEX (tradingbot-3xw). The
  trial starts flat. Its anchor is the last session completed before
  ``prepare``, and its state persists in ``Trial.metrics``.
- **Decision:** once per session, from 30 minutes before the open, using bars
  through the previous session. Every session since the last decision must have
  a bar, or nothing trades that day.
- **Orders:** from 30 s after the open until 60 minutes after it, as fractional
  marketable DAY limits through ``AlpacaLiveConnector`` (buy at ask +25 bp,
  sell at bid −25 bp, cent-rounded). Long wanted and flat: buy min(95% of
  strategy equity, $140) from settled cash, keeping a 5% reserve. Flat wanted
  and long: sell everything. A missed entry or exit retries at the next open
  while the signal still wants it (the plan's delayed-entry rule).
- **Dry run:** without live keys, or before the live cash book exists, the same
  decisions fill a virtual book at the IEX quote and nothing is sent. The
  process exits outside the order window so ``ops/with-secrets`` re-reads
  1Password, and it switches to live by itself once the keys resolve.
- **Fidelity:** every fill is compared with its session's official SIP open,
  against the backtest's 10 bp per side and the ~33 bp break-even.

    uv run python -m tradingbot.live.ibs_qqq prepare --commit SHA
    ops/with-secrets uv run python -m tradingbot.live.ibs_qqq run [--once]
    uv run python -m tradingbot.live.ibs_qqq status
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, date, datetime, time as wall, timedelta
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import json
from pathlib import Path
import sys
import time

from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from sqlalchemy import func, select, text
from sqlalchemy.orm.attributes import flag_modified

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_live import NAME as BOOK, AlpacaLiveAPI, AlpacaLiveConnector
from tradingbot.connectors.alpaca_paper import ACTIVE, OrderRejected, PaperAPIError, PaperEvidenceUnavailable
from tradingbot.connectors.cash import MarketSession, NEW_YORK, timestamp
from tradingbot.db.models import Fill, FxRate, Instrument, Order, Position, Strategy, Trial, Venue
from tradingbot.ledger import Ledger
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.risk import RiskEngine
from tradingbot.strategy.ibs import Signal

ROOT = Path(__file__).resolve().parents[3]
NAME = "ibs_qqq_live_v1"
KEY = "ibs-QQQ-live-v1"
SYMBOL = "QQQ"
MODE = "live"
ALLOCATION = D(140)
VERSION = "679b87a0f8b316994d2c19eeac4d850b63cd28e52edb8979543379168a0f0994"
RESEARCH = {"train": 8802, "final": 8804}
ZERO, CENT, NANO = D(0), D("0.01"), D("0.000000001")
CUSHION = D("0.0025")          # marketable-limit protection against the quote
BACKTEST_BP, BREAK_EVEN_BP = D(10), D(33)
DECIDE_BEFORE_OPEN = timedelta(minutes=30)
WINDOW = (timedelta(seconds=30), timedelta(minutes=60))  # after the open
BAR_DELAY = timedelta(minutes=20)  # free SIP bars are served once >15 minutes old
MAX_ATTEMPTS, RETRY_AFTER = 5, timedelta(seconds=30)
POLL_EVERY, CANCEL_AFTER = timedelta(seconds=30), timedelta(seconds=120)
MARK_EVERY, GO_LIVE_EVERY = timedelta(minutes=5), timedelta(hours=1)
LOCK = 75200


def limit_price(side: str, bid: D, ask: D) -> D:
    if side == "buy":
        return (ask * (1 + CUSHION)).quantize(CENT, rounding=ROUND_CEILING)
    return (bid * (1 - CUSHION)).quantize(CENT, rounding=ROUND_FLOOR)


def entry_size(equity: D, available: D, price: D) -> D:
    """The plan's sizing: min(95% equity, $140), 5% reserve, $0.01 buffer, 1e-9 floor, $1 minimum."""
    target, reserve = min(D(".95") * equity, ALLOCATION), D(".05") * equity
    budget = min(target, max(ZERO, available - reserve - CENT))
    qty = (budget / price).quantize(NANO, rounding=ROUND_FLOOR)
    return qty if qty * price >= 1 else ZERO


def step(signal_state: dict, sessions: list[date], bars: dict[date, dict]) -> tuple[dict, dict] | None:
    """Advance the persisted signal over consecutive completed sessions; None if a bar is missing."""
    if any(day not in bars for day in sessions):
        return None
    signal = Signal()
    previous = signal_state["previous"]
    signal.previous = None if previous is None else D(previous)
    signal.units = signal_state["units"]
    rows = {}
    for day in sessions:
        units = signal.update(bars[day])
        rows[day.isoformat()] = {**bars[day], "ibs": None if signal.previous is None else str(signal.previous),
                                 "units": units}
    if not sessions:
        return dict(signal_state), rows
    return {"last_bar": sessions[-1].isoformat(),
            "previous": None if signal.previous is None else str(signal.previous),
            "units": signal.units}, rows


def adverse_bp(side: str, price: D, official_open: D) -> D:
    move = price / official_open - 1 if side == "buy" else 1 - price / official_open
    return (move * 10000).quantize(D("0.01"))


def safe(exc: BaseException) -> str:
    """Never print SDK exception bodies: they can carry authenticated requests."""
    if isinstance(exc, (OrderRejected, PaperAPIError, ValueError)):
        return f"{type(exc).__name__}: {str(exc)[:200]}"
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if status else "")


def append_incident(message: str) -> None:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    with (ROOT / "logs" / "INCIDENTS.md").open("a") as log:
        log.write(f"- {stamp} ibs-live (tradingbot-752): {message}\n")


class MarketData:
    """Read-only market data on the paper key: calendar, SIP daily bars, IEX quote."""

    def __init__(self, api: AlpacaPaperAPI):
        self.api = api

    def calendar(self, start: date, end: date) -> list[MarketSession]:
        return [MarketSession.from_api(row) for row in self.api.calendar_range(start, end)]

    def daily_bars(self, start: date, end: datetime) -> dict[date, dict]:
        raw = self.api._data.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=SYMBOL, timeframe=TimeFrame.Day, feed=DataFeed.SIP, adjustment=Adjustment.RAW,
            start=datetime.combine(start, wall.min, NEW_YORK), end=end))
        return {timestamp(bar["t"]).astimezone(NEW_YORK).date():
                {name: str(bar[short]) for name, short in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}
                for bar in raw.get(SYMBOL, [])}

    def quote(self) -> dict:
        row = self.api.quote(SYMBOL)
        return {"bid": str(row["bp"]), "ask": str(row["ap"]), "time": str(row["t"])}


def research_evidence(session) -> dict:
    trials = {name: session.get(Trial, trial_id) for name, trial_id in RESEARCH.items()}
    final = trials["final"]
    if (final is None or final.status != "complete" or not final.final_holdout
            or final.strategy_version != VERSION or not final.pnl_after_fees or final.pnl_after_fees <= 0):
        raise ValueError("IBS QQQ v1 needs its complete, profitable single holdout (trial 8804)")
    train = trials["train"]
    if train is None or train.strategy_version != VERSION or not train.pnl_after_fees or train.pnl_after_fees <= 0:
        raise ValueError("IBS QQQ v1 needs its profitable training run (trial 8802)")
    return {name: {"trial": t.id, "pnl_after_fees": str(t.pnl_after_fees), "trades": t.trade_count}
            for name, t in trials.items()}


def prepare(session, market: MarketData, *, commit: str, evidence: dict, now: datetime | None = None) -> int:
    """Create the live strategy and trial, anchored flat on the last completed session. Sends nothing."""
    now = now or datetime.now(UTC)
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY).with_for_update())
    if strategy is None:
        strategy = Strategy(key=KEY, name="IBS mean reversion, QQQ v1 (live)", venue_id=venue.id,
                            status="live", allocation_usd=ALLOCATION,
                            description="Owner override 2026-10-14: live without paper (PRD §4). tradingbot-752.",
                            config={"symbol": SYMBOL, "research_version": VERSION, "research": evidence})
        session.add(strategy)
        session.flush()
    elif strategy.status == "killed":
        raise ValueError("The live IBS strategy was killed (PRD §6); it is permanent")
    if session.scalar(select(Trial.id).where(Trial.strategy_id == strategy.id, Trial.mode == MODE,
                                             Trial.status == "running")):
        raise ValueError("A running live IBS trial exists; resume it")
    today = now.astimezone(NEW_YORK).date()
    done = [s for s in market.calendar(today - timedelta(days=10), today) if s.closes_at + BAR_DELAY <= now]
    anchor = done[-1]
    bars = market.daily_bars(anchor.trade_date, anchor.closes_at + BAR_DELAY)
    if anchor.trade_date not in bars:
        raise ValueError(f"No SIP bar for the anchor session {anchor.trade_date}")
    signal = Signal()
    signal.update(bars[anchor.trade_date])
    state = {"signal": {"last_bar": anchor.trade_date.isoformat(), "units": 0,
                        "previous": None if signal.previous is None else str(signal.previous)},
             "bars": {anchor.trade_date.isoformat(): {**bars[anchor.trade_date], "anchor": True}},
             "decisions": {}, "days": {}, "notes": {},
             "virtual": {"cash": str(ALLOCATION), "qty": "0", "trades": []},
             "live": {"since": None, "instrument_id": None, "go_live_attempted_at": None}}
    trial = Trial(strategy_id=strategy.id, mode=MODE, code_version=NAME, git_commit=commit,
                  strategy_version=VERSION, data_start=now, params={
                      "symbol": SYMBOL, "allocation_usd": str(ALLOCATION), "research": evidence,
                      "approval": "owner override 2026-10-14 (PRD §4): live without a paper stage",
                      "signal_source": "Alpaca SIP daily bars, raw", "limit_cushion": str(CUSHION),
                      "window_after_open_s": [int(w.total_seconds()) for w in WINDOW]},
                  metrics={NAME: state}, notes="Starts flat; first decision uses the bar after the anchor.")
    session.add(trial)
    session.commit()
    return trial.id


class Runner:
    def __init__(self, session, trial_id: int, market: MarketData, live_api=None, *, now=None,
                 incident=append_incident, log=print):
        self.session, self.trial_id, self.market = session, trial_id, market
        self.now = now or (lambda: datetime.now(UTC))
        self.connector = AlpacaLiveConnector(session, live_api, now=self.now) if live_api is not None else None
        self.ledger, self.risk = Ledger(session, auto_fee=False), RiskEngine(session)
        self.incident, self.log = incident, log
        self.polled: dict[int, datetime] = {}
        self.marked: datetime | None = None
        self._sessions: dict[date, MarketSession | None] = {}

    # -- persisted state ----------------------------------------------------
    def trial(self) -> Trial:
        return self.session.get(Trial, self.trial_id, populate_existing=True)

    def state(self) -> dict:
        return deepcopy(self.trial().metrics[NAME])

    def save(self, state: dict) -> None:
        trial = self.trial()
        trial.metrics = {**trial.metrics, NAME: state}
        flag_modified(trial, "metrics")
        self.session.commit()

    def note_once(self, state: dict, key: str, message: str, *, severity="warning", owner=True) -> None:
        """Record an incident at most once per key (DB always; INCIDENTS.md when the owner should see it)."""
        if key in state["notes"]:
            return
        state["notes"][key] = self.now().isoformat()
        self.risk.log_incident(severity=severity, category="other", mode=MODE, message="IBS QQQ live: " + message,
                               strategy_id=self.trial().strategy_id, details={"trial": self.trial_id, "key": key})
        self.save(state)
        if owner:
            self.incident(message)

    @property
    def live(self) -> bool:
        if self.connector is None:
            return False
        state = self.state()["live"]
        return bool(state["since"] and state["instrument_id"])

    def session_for(self, day: date) -> MarketSession | None:
        if day not in self._sessions:
            rows = [s for s in self.market.calendar(day, day) if s.trade_date == day]
            self._sessions[day] = rows[0] if rows else None
        return self._sessions[day]

    def in_order_window(self) -> bool:
        now = self.now()
        today = self.session_for(now.astimezone(NEW_YORK).date())
        return today is not None and today.opens_at - DECIDE_BEFORE_OPEN - timedelta(minutes=5) <= now < (
            today.opens_at + WINDOW[1] + timedelta(minutes=5))

    # -- one loop iteration ---------------------------------------------------
    def tick(self) -> None:
        now = self.now()
        trial = self.trial()
        if trial.status != "running" or trial.mode != MODE:
            raise SystemExit(f"Trial {self.trial_id} is not a running live trial")
        if self.connector is not None and not self.live:
            self.go_live(now)
        today = self.session_for(now.astimezone(NEW_YORK).date())
        if self.live:
            self.poll(now)
        if today is None:
            return
        window = (today.opens_at + WINDOW[0], today.opens_at + WINDOW[1])
        decision = self.state()["decisions"].get(today.trade_date.isoformat())
        if decision is None and today.opens_at - DECIDE_BEFORE_OPEN <= now < window[1]:
            decision = self.decide(today, now)
        if decision is None and now >= window[1] and now < today.closes_at:
            self.note_once(self.state(), f"no-decision:{today.trade_date}",
                           f"no decision for {today.trade_date}: SIP daily bars incomplete; nothing traded today")
        if decision is not None and window[0] <= now < window[1]:
            if self.live:
                self.act(today, decision["units"], now)
            elif self.state()["live"]["since"]:
                # Once live, a missing key must never fall back to the virtual book.
                self.note_once(self.state(), f"keys-missing:{today.trade_date}",
                               f"live keys did not resolve on {today.trade_date}; the real QQQ position is unmanaged "
                               "today (check 1Password / ops/with-secrets)")
            else:
                self.act_virtual(today, decision["units"], now)
        if self.live and today.is_open(now):
            self.mark(now)

    def decide(self, today: MarketSession, now: datetime) -> dict | None:
        state = self.state()
        last = date.fromisoformat(state["signal"]["last_bar"])
        start, end = last + timedelta(days=1), today.trade_date - timedelta(days=1)
        # Alpaca refuses an inverted range; on the session after the anchor there is nothing to step.
        sessions = [s for s in self.market.calendar(start, end)
                    if last < s.trade_date < today.trade_date] if start <= end else []
        bars = {}
        if sessions:
            end = sessions[-1].closes_at + BAR_DELAY
            if now < end:
                return None
            bars = self.market.daily_bars(sessions[0].trade_date, end)
        result = step(state["signal"], [s.trade_date for s in sessions], bars)
        if result is None:
            return None
        state["signal"], rows = result
        state["bars"].update(rows)
        decision = {"units": state["signal"]["units"], "through": state["signal"]["last_bar"],
                    "ibs": state["signal"]["previous"], "decided_at": now.isoformat()}
        state["decisions"][today.trade_date.isoformat()] = decision
        state["fidelity"] = self.fidelity(state)
        self.save(state)
        self.log(f"{now.isoformat()} decision {today.trade_date}: units {decision['units']} "
                 f"(IBS {decision['ibs']} through {decision['through']}){'' if self.live else ' [dry run]'}")
        self.refresh_fx(now)
        return decision

    # -- live ---------------------------------------------------------------
    def go_live(self, now: datetime) -> None:
        state = self.state()
        attempted = state["live"]["go_live_attempted_at"]
        if attempted and now - timestamp(attempted) < GO_LIVE_EVERY:
            return
        state["live"]["go_live_attempted_at"] = now.isoformat()
        self.save(state)
        try:
            venue = self.connector._venue()
            if not (venue.metadata_ or {}).get(BOOK):
                self.connector.initialize_cash(ALLOCATION)
            iid = self.connector.register_equity(SYMBOL)
        except (OrderRejected, PaperAPIError, ValueError) as exc:
            self.session.rollback()
            self.log(f"{now.isoformat()} live keys present but not ready: {safe(exc)}; staying in dry run")
            self.note_once(self.state(), f"go-live-blocked:{now.astimezone(NEW_YORK).date()}",
                           f"live keys resolve but the live book is not ready ({safe(exc)}); still dry run")
            return
        state = self.state()
        state["live"].update(since=now.isoformat(), instrument_id=iid)
        self.save(state)
        self.incident("live keys resolved; the $140 IBS QQQ book is initialized and real-money orders are enabled "
                      "(owner override 2026-10-14)")
        self.log(f"{now.isoformat()} LIVE: real-money orders enabled on instrument {iid}")

    def held(self) -> D:
        state = self.state()
        return self.session.scalar(select(func.coalesce(func.sum(Position.quantity), 0)).where(
            Position.strategy_id == self.trial().strategy_id, Position.mode == MODE,
            Position.instrument_id == state["live"]["instrument_id"])) or ZERO

    def active_orders(self) -> list[Order]:
        return list(self.session.scalars(select(Order).where(
            Order.trial_id == self.trial_id, Order.mode == MODE, Order.status.in_(ACTIVE))))

    def poll(self, now: datetime) -> None:
        for order in self.active_orders():
            if now - self.polled.get(order.id, datetime.min.replace(tzinfo=UTC)) < POLL_EVERY:
                continue
            self.polled[order.id] = now
            try:
                result = self.connector.refresh(order.id)
                if result.status in ACTIVE and now - order.created_ts >= CANCEL_AFTER and not result.submission_unknown:
                    self.connector.cancel(order.id)
            except PaperEvidenceUnavailable:
                pass
            except (PaperAPIError, ValueError) as exc:
                self.session.rollback()
                self.log(f"{now.isoformat()} poll of order {order.id} failed: {safe(exc)}")
                if now - order.created_ts > timedelta(minutes=15):
                    self.note_once(self.state(), f"unresolved-order:{order.id}",
                                   f"live order {order.id} unresolved after 15 min ({safe(exc)}); check Alpaca")

    def act(self, today: MarketSession, units: int, now: datetime) -> None:
        if self.active_orders():
            return
        held = self.held()
        side = "buy" if units and held == 0 else "sell" if not units and held > 0 else None
        if side is None:
            return
        state = self.state()
        day = state["days"].setdefault(today.trade_date.isoformat(), {"attempts": []})
        tries = [a for a in day["attempts"] if a["side"] == side]
        if len(tries) >= MAX_ATTEMPTS:
            self.note_once(state, f"attempts:{today.trade_date}:{side}",
                           f"{side} for {today.trade_date} failed {MAX_ATTEMPTS} times; retrying at the next open")
            return
        if tries and now - timestamp(tries[-1]["at"]) < RETRY_AFTER:
            return
        if self.connector.kill_switch().get("active"):
            self.note_once(state, f"kill-switch:{today.trade_date}",
                           f"live kill switch engaged; {side} for {today.trade_date} not sent", owner=False)
            return
        strategy = self.session.get(Strategy, self.trial().strategy_id, populate_existing=True)
        if strategy.status == "killed":
            if held > 0:
                self.note_once(state, "killed-with-position",
                               f"strategy killed (PRD §6) while holding {held} QQQ; the risk engine refuses every "
                               "order, so close the position in Alpaca")
            return
        try:
            quote = self.connector._call(self.connector.api.quote, SYMBOL)
            bid, ask = D(str(quote["bp"])), D(str(quote["ap"]))
            price = limit_price(side, bid, ask)
            if side == "sell":
                qty = held
            else:
                equity = ALLOCATION + self.ledger.realized_after_fees(strategy_id=strategy.id, mode=MODE)
                qty = entry_size(equity, self.connector.cash().available, price)
        except (OrderRejected, PaperAPIError, ValueError) as exc:
            self.session.rollback()
            self.log(f"{now.isoformat()} {side} preparation failed: {safe(exc)}")
            return
        if qty <= 0:
            if "skip" not in day:
                day["skip"] = {"at": now.isoformat(), "reason": "cash/target below $1"}
                self.save(state)
            return
        request_id = f"ibs{today.trade_date:%Y%m%d}{side[0]}{len(tries) + 1}"
        attempt = {"side": side, "request_id": request_id, "at": now.isoformat(), "qty": str(qty),
                   "limit": str(price), "quote": {"bid": str(bid), "ask": str(ask), "time": str(quote["t"])}}
        day["attempts"].append(attempt)
        self.save(state)  # durable attempt before any submission
        try:
            result = self.connector.submit_limit(request_id=request_id, instrument_id=state["live"]["instrument_id"],
                                                 strategy_id=strategy.id, trial_id=self.trial_id, side=side,
                                                 quantity=qty, limit_price=price)
            outcome = {"order_id": result.order_id, "status": result.status}
        except (OrderRejected, PaperAPIError, ValueError) as exc:
            self.session.rollback()
            outcome = {"error": safe(exc)}
        state = self.state()
        state["days"][today.trade_date.isoformat()]["attempts"][-1].update(outcome)
        self.save(state)
        self.log(f"{now.isoformat()} {side} {qty} {SYMBOL} limit {price}: {outcome}")

    def mark(self, now: datetime) -> None:
        if self.marked and now - self.marked < MARK_EVERY:
            return
        self.marked = now
        state = self.state()
        if self.held() <= 0:
            return
        iid = state["live"]["instrument_id"]
        try:
            quote = self.connector._capture_quote(self.session.get(Instrument, iid))
            self.connector._refresh_risk(None, now, {iid: (quote.bid + quote.ask) / 2})
            self.session.commit()
        except (OrderRejected, PaperAPIError, ValueError) as exc:
            self.session.rollback()
            self.log(f"{now.isoformat()} mark failed: {safe(exc)}")
            return
        strategy = self.session.get(Strategy, self.trial().strategy_id, populate_existing=True)
        if strategy.status == "killed":
            self.note_once(self.state(), "killed-with-position",
                           f"strategy killed (PRD §6) while holding {self.held()} QQQ; the risk engine refuses "
                           "every order, so close the position in Alpaca")

    # -- dry run --------------------------------------------------------------
    def act_virtual(self, today: MarketSession, units: int, now: datetime) -> None:
        state = self.state()
        book = state["virtual"]
        cash, qty = D(book["cash"]), D(book["qty"])
        side = "buy" if units and qty == 0 else "sell" if not units and qty > 0 else None
        if side is None or any(t["date"] == today.trade_date.isoformat() for t in book["trades"]):
            return
        quote = self.market.quote()
        price = D(quote["ask"]) if side == "buy" else D(quote["bid"])
        size = qty if side == "sell" else entry_size(cash, cash, price)
        if size <= 0:
            return
        fee, _ = EquityFeeBook().charge(day=today.trade_date, side=side, price=price, size=size)
        cash += -(price * size + fee) if side == "buy" else price * size - fee
        book.update(cash=str(cash), qty=str(qty + size if side == "buy" else ZERO))
        book["trades"].append({"date": today.trade_date.isoformat(), "side": side, "qty": str(size),
                               "price": str(price), "fee": str(fee), "at": now.isoformat(), "quote": quote})
        self.save(state)
        self.log(f"{now.isoformat()} [dry run] virtual {side} {size} {SYMBOL} at {price}; virtual cash {cash}")

    # -- evidence -------------------------------------------------------------
    def fills(self) -> list[Fill]:
        return list(self.session.scalars(select(Fill).join(Order, Fill.order_id == Order.id).where(
            Order.trial_id == self.trial_id, Fill.mode == MODE).order_by(Fill.fill_ts)))

    def fidelity(self, state: dict) -> dict:
        rows = []
        for fill in self.fills():
            day = fill.fill_ts.astimezone(NEW_YORK).date().isoformat()
            bar = state["bars"].get(day)
            rows.append({"day": day, "side": fill.side, "qty": str(fill.size), "price": str(fill.price),
                         "fee": str(fill.fee), "official_open": bar and bar["open"],
                         "adverse_bp": bar and str(adverse_bp(fill.side, fill.price, D(bar["open"])))})
        for trade in state["virtual"]["trades"]:
            bar = state["bars"].get(trade["date"])
            trade["official_open"] = bar and bar["open"]
            trade["adverse_bp"] = bar and str(adverse_bp(trade["side"], D(trade["price"]), D(bar["open"])))
        measured = [D(r["adverse_bp"]) for r in rows if r["adverse_bp"] is not None]
        return {"fills": rows, "mean_adverse_bp": str(sum(measured) / len(measured)) if measured else None,
                "backtest_bp": str(BACKTEST_BP), "break_even_bp": str(BREAK_EVEN_BP)}

    def refresh_fx(self, now: datetime) -> None:
        latest = self.session.scalar(select(func.max(FxRate.ts)).where(FxRate.base == "USD", FxRate.quote == "GBP"))
        if latest is not None and now - latest < timedelta(days=3):
            return
        try:  # live fills need a dated USD/GBP rate; the TOM runner normally keeps these current
            from tradingbot.forward.turn_of_month import fetch_fx, import_fx
            import_fx(self.session, fetch_fx(), now)
        except Exception as exc:
            self.session.rollback()
            self.log(f"{now.isoformat()} FX refresh failed: {safe(exc)}")


def running_trial(session) -> int:
    trial_id = session.scalar(select(Trial.id).join(Strategy).where(
        Strategy.key == KEY, Trial.mode == MODE, Trial.status == "running"))
    if trial_id is None:
        raise SystemExit("No running live IBS trial; run prepare first")
    return trial_id


def status(session) -> dict:
    trial = session.get(Trial, running_trial(session))
    state = trial.metrics[NAME]
    strategy = session.get(Strategy, trial.strategy_id)
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    book = (venue.metadata_ or {}).get(BOOK)
    decisions = sorted(state["decisions"].items())[-5:]
    return {"trial": trial.id, "strategy": strategy.key, "strategy_status": strategy.status,
            "live_since": state["live"]["since"], "live_book": book and book["initial_cash"],
            "kill_switch": ((venue.metadata_ or {}).get("alpaca_live_kill_switch_v1") or {}).get("active", False),
            "signal": state["signal"], "recent_decisions": dict(decisions),
            "realized_after_fees": str(Ledger(session, auto_fee=False).realized_after_fees(
                strategy_id=strategy.id, mode=MODE)),
            "fidelity": state.get("fidelity"), "virtual": state["virtual"], "notes": state["notes"]}


def run(*, once: bool, max_minutes: int) -> None:
    from tradingbot.db.session import SessionLocal, get_engine

    started = time.monotonic()
    market_api = AlpacaPaperAPI.from_env(ROOT / ".env")
    try:
        live_api = AlpacaLiveAPI.from_env(ROOT / ".env")
    except ValueError as exc:
        live_api = None
        print(f"{datetime.now(UTC).isoformat()} dry run: {exc}", flush=True)
    lock = get_engine().connect()
    try:
        with SessionLocal() as session:
            trial_id = running_trial(session)
            if not lock.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": LOCK, "b": trial_id}).scalar():
                raise SystemExit("Another IBS live runner holds the lock")
            runner = Runner(session, trial_id, MarketData(market_api), live_api,
                            log=lambda line: print(line, flush=True))
            while True:
                try:
                    runner.tick()
                except SystemExit:
                    raise
                except Exception as exc:
                    session.rollback()
                    print(f"{datetime.now(UTC).isoformat()} tick failed: {safe(exc)}", flush=True)
                if once:
                    return
                # A dry run restarts outside the order window so with-secrets re-reads 1Password.
                if not runner.live and time.monotonic() - started > max_minutes * 60 and not runner.in_order_window():
                    return
                time.sleep(10)
    finally:
        lock.close()
        market_api.close()
        if live_api is not None:
            live_api.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="IBS QQQ v1 live runner (tradingbot-752)")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Create the live strategy/trial (sends nothing)")
    prep.add_argument("--commit", required=True)
    go = commands.add_parser("run", help="Decide pre-open and trade at the open (dry run without live keys)")
    go.add_argument("--once", action="store_true")
    go.add_argument("--max-minutes", type=int, default=25)
    commands.add_parser("status", help="Show signal, decisions, fills and fidelity")
    args = parser.parse_args()
    from tradingbot.db.session import SessionLocal

    if args.command == "run":
        run(once=args.once, max_minutes=args.max_minutes)
        return
    with SessionLocal() as session:
        if args.command == "status":
            print(json.dumps(status(session), indent=2, default=str))
            return
        api = AlpacaPaperAPI.from_env(ROOT / ".env")
        try:
            trial_id = prepare(session, MarketData(api), commit=args.commit, evidence=research_evidence(session))
        finally:
            api.close()
        print(json.dumps({"trial": trial_id}))


if __name__ == "__main__":
    sys.exit(main())
