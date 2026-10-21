"""Scheduled SPY paper experiment. No live transport or account-wide reconcile.

Preparation creates a durable trial and calendar; run explicitly resumes it.
The same pure TurnOfMonth reactor generated historical trial 849's intents.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time as clock
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import select, text

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import (
    ACTIVE, AlpacaPaperConnector, OrderRejected, PaperAPIError, PaperEvidenceUnavailable, PaperGuardContext,
)
from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.data.alpaca_history import monthly_cycles
from tradingbot.db.models import Fill, FxRate, Instrument, Order, Position, Quote, Strategy, Trial
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.risk import limits
from tradingbot.strategy import MarketEvent, StrategyContext
from tradingbot.strategy.turn_of_month import TurnOfMonth

NAME = "alpaca_tom_forward_v1"
FX_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
ZERO = D(0)


def plan(rows, *, start: datetime, through: date, instrument_id: int):
    sessions = [MarketSession.from_api(row) for row in rows]
    dates = [s.trade_date for s in sessions]
    if dates != sorted(set(dates)) or not dates or dates[0] > start.date() or dates[-1] < through:
        raise ValueError("Calendar must be ordered, unique and cover the requested interval")
    # A full month on either side is requested from the official calendar.
    # Reject missing intermediate months instead of joining nonadjacent months.
    for left, right in zip(dates, dates[1:]):
        if (right - left).days > 7:
            raise ValueError("Calendar has a gap requiring review")
    by_day = {s.trade_date: s for s in sessions}
    pairs = [(a, b) for a, b in monthly_cycles(rows, through)
             if by_day[date.fromisoformat(a["date"])].closes_at - timedelta(seconds=60) >= start]
    if not pairs:
        raise ValueError("No complete future cycles in the calendar")
    actions = {row["date"]: side for a, b in pairs for row, side in ((a, "buy"), (b, "sell"))}
    return {"instrument_id": instrument_id, "entry_notional": "24.90", "seconds_before_close": 60,
            "schedule": actions, "session_closes": {d: by_day[date.fromisoformat(d)].closes_at.strftime("%H:%M:%S") for d in actions},
            "calendar": rows, "calendar_sha256": sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            "start": start.isoformat(), "through": through.isoformat(), "primary_trial": 849,
            "research_family": [849, 850, 851, 852, 853], "virtual_cash": "140.00"}


def import_fx(session, body: bytes, now: datetime):
    """Dated reference, deliberately available only from the following UTC day."""
    source = "ecb-forward:" + sha256(body).hexdigest()[:20]
    valid = []
    for cube in ET.fromstring(body).iter():
        if "time" not in cube.attrib:
            continue
        day = date.fromisoformat(cube.attrib["time"])
        values = {child.attrib["currency"]: D(child.attrib["rate"]) for child in cube}
        if day >= now.date() or not {"USD", "GBP"} <= values.keys():
            continue
        rate = (values["GBP"] / values["USD"]).quantize(D(".00000001"))
        if not rate.is_finite() or rate <= 0:
            raise ValueError("Invalid ECB reference")
        at = datetime.combine(day + timedelta(days=1), time.min, UTC)
        valid.append(at)
        exists = session.scalar(select(FxRate.id).where(FxRate.base == "USD", FxRate.quote == "GBP", FxRate.ts == at))
        if exists is None:
            session.add(FxRate(base="USD", quote="GBP", ts=at, rate=rate, source=source))
    if not valid or now - max(valid) > timedelta(days=7):
        raise ValueError("No recent prior-day ECB reference")
    session.commit()


def fetch_fx():
    with httpx.Client(timeout=20) as client:
        response = client.get(FX_URL)
        response.raise_for_status()
        return response.content


def prepare(session, api, *, through: date, commit: str, now=None):
    now = now or datetime.now(UTC)
    row = session.scalar(select(Strategy).where(Strategy.key == "turn_of_month").with_for_update())
    if row is None or row.status == "killed":
        raise ValueError("An existing, non-killed turn_of_month strategy is required")
    if session.scalar(select(Trial.id).where(Trial.strategy_id == row.id, Trial.mode == "paper", Trial.status == "running")):
        raise ValueError("Explicitly resume the existing paper trial")
    primary = session.get(Trial, 849)
    if (primary is None or primary.mode != "backtest" or primary.status != "complete"
            or primary.params.get("variant") != "tom_minute_2bp"
            or primary.pnl_after_fees is None or primary.pnl_after_fees <= 0):
        raise ValueError("Primary historical trial 849 must be complete and profitable after fees")
    trial = Trial(strategy_id=row.id, mode="paper", code_version=NAME, git_commit=commit,
                  data_start=now, params={"primary_trial": 849}, metrics={NAME: {"attempts": {}}})
    session.add(trial); session.commit()
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    try:
        start_month = now.astimezone(NEW_YORK).date().replace(day=1)
        end_month = (through.replace(day=28) + timedelta(days=4)).replace(day=1)
        rows = connector._call(api.calendar_range, start_month, end_month + timedelta(days=7))
        iid = connector.register_equity("SPY")
        params = plan(rows, start=now, through=through, instrument_id=iid)
        if connector.ledger.open_positions(strategy_id=row.id, mode="paper") or session.scalar(select(Order.id).where(
                Order.strategy_id == row.id, Order.mode == "paper", Order.status.in_(ACTIVE))):
            raise ValueError("Existing paper holdings require continuation of their trial")
        connector.initialize_cash(D(140))
        row.status, row.allocation_usd = "paper", D(140)
        trial.params = params
        trial.notes = "Primary #6 forward paper; promotion/risk decision: docs/research/08-turn-of-month-paper.md. Broker fees omit regulatory charges; fee scenario kept separately."
        session.commit()
        return trial.id
    except Exception as exc:
        session.rollback()
        trial = session.get(Trial, trial.id)
        trial.status, trial.completed_ts = "failed", now
        trial.notes = "Preparation failed: " + type(exc).__name__
        session.commit()
        raise


def slot_evidence(training, holdout):
    """Validate the two recorded evaluations without replaying either dataset."""
    for trial, final in ((training, False), (holdout, True)):
        if (trial is None or trial.mode != "backtest" or trial.status != "complete"
                or trial.final_holdout != final or not trial.strategy_version
                or not trial.dataset_key or trial.holdout_start is None
                or trial.pnl_after_fees is None or trial.pnl_after_fees <= 0):
            raise ValueError("Complete profitable training and final holdout trials are required")
        params = trial.params or {}
        core = params.get("strategy_params", {})
        if (params.get("variant") != "tom_minute_2bp"
                or core.get("entry_notional") != "140"
                or core.get("use_available_cash") is not True
                or D(core.get("entry_fee_reserve", "0")) != D(".01")
                or core.get("seconds_before_close") != 60
                or params.get("_holdout", {}).get("identity", {}).get("key") != "turn_of_month"):
            raise ValueError("Evidence must use the frozen cash-aware $140 TOM rule")
    if (training.strategy_version != holdout.strategy_version
            or training.dataset_key != holdout.dataset_key
            or training.holdout_start != holdout.holdout_start):
        raise ValueError("Training and holdout must share one strategy version and dataset split")
    return {"primary_trial": training.id, "holdout_trial": holdout.id,
            "research_family": [training.id, holdout.id],
            "research_strategy_version": training.strategy_version,
            "research_dataset_key": training.dataset_key,
            "research_holdout_start": training.holdout_start.isoformat(),
            "entry_notional": "140", "use_available_cash": True, "entry_fee_reserve": ".01"}


def unused_paper_trial(session, strategy_id, trial_id):
    """Only an explicitly named, never-used experiment can be superseded."""
    running = list(session.scalars(select(Trial).where(Trial.strategy_id == strategy_id,
        Trial.mode == "paper", Trial.status == "running").with_for_update()))
    if len(running) != 1 or running[0].id != trial_id or running[0].code_version != NAME:
        raise ValueError("Explicitly identify the sole prepared TOM paper trial")
    old = running[0]
    if ((old.metrics or {}).get(NAME, {}).get("attempts")
            or session.scalar(select(Order.id).where(Order.trial_id == old.id).limit(1))
            or session.scalar(select(Fill.id).where(Fill.trial_id == old.id).limit(1))
            or session.scalar(select(Position.id).where(Position.strategy_id == strategy_id,
                Position.mode == "paper", Position.status == "open").limit(1))
            or session.scalar(select(Order.id).where(Order.strategy_id == strategy_id,
                Order.mode == "paper", Order.status.in_(ACTIVE)).limit(1))):
        raise ValueError("Used trials or existing exposure must be continued, not replaced")
    return old


def prepare_slot(session, api, *, training_id, holdout_id, supersede_id, through, commit, now=None):
    now = now or datetime.now(UTC)
    training, holdout = session.get(Trial, training_id), session.get(Trial, holdout_id)
    evidence = slot_evidence(training, holdout)
    source = Path(__file__).parents[1] / "strategy" / "turn_of_month.py"
    expected = holdout.params["_holdout"]["identity"]["code"].get("strategy/turn_of_month.py")
    if sha256(source.read_bytes()).hexdigest() != expected:
        raise ValueError("The forward strategy source differs from the evaluated version")
    row = session.scalar(select(Strategy).where(Strategy.key == "turn_of_month"))
    if row is None or row.status == "killed":
        raise ValueError("An existing non-killed TOM strategy is required")
    unused_paper_trial(session, row.id, supersede_id)
    session.rollback()  # connector methods own their transactions
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    start_month = now.astimezone(NEW_YORK).date().replace(day=1)
    end_month = (through.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = connector._call(api.calendar_range, start_month, end_month + timedelta(days=7))
    iid = connector.register_equity("SPY")
    params = {**plan(rows, start=now, through=through, instrument_id=iid), **evidence,
              "supersedes_unused_trial": supersede_id,
              "decision_record": "docs/research/09-turn-of-month-slot-results.md"}
    connector.initialize_cash(D(140))  # verifies the existing book; cannot add/reset cash
    row = session.scalar(select(Strategy).where(Strategy.key == "turn_of_month").with_for_update())
    if row.status == "killed":
        raise ValueError("Killed strategies cannot be promoted")
    old = unused_paper_trial(session, row.id, supersede_id)
    trial = Trial(strategy_id=row.id, mode="paper", code_version=NAME, git_commit=commit,
        data_start=now, params=params, metrics={NAME: {"attempts": {}}},
        notes="Slot-sized TOM execution measurement. Historical profit passes; calendar premium absent in holdout and profits regime-concentrated. Not ready-for-live. See " + params["decision_record"])
    session.add(trial); session.flush()
    old.status, old.completed_ts = "abandoned", now
    old.notes = (old.notes or "") + f" Superseded unused by slot-sized paper trial {trial.id}; original parameters preserved."
    row.status, row.allocation_usd = "paper", D(140)
    session.commit()
    return trial.id


class Context(StrategyContext):
    def __init__(self, runner): self.runner = runner
    @property
    def now(self): return self.runner.now()
    @property
    def mode(self): return "paper"
    @property
    def params(self): return self.runner.core.params
    def position(self, instrument_id):
        p = self.runner.connector.ledger.get_position(self.runner.strategy_id, "paper", instrument_id)
        return p.quantity if p else ZERO
    def snapshot(self, instrument_id): return self.runner.snapshots.get(instrument_id)
    def resting_tags(self, instrument_id=None):
        return tuple(o.metadata_["client_order_id"] for o in self.runner.orders()
                     if instrument_id is None or o.instrument_id == instrument_id)
    def available_cash(self, instrument_id):
        if instrument_id != self.runner.iid:
            return None
        runner = self.runner
        if runner.evidence_guard is not None:
            venue = runner.connector._venue(lock=True)
            result = runner.evidence_guard(runner.connector, PaperGuardContext(
                phase="refresh", now=runner.now(), venue=venue, strategy_id=runner.strategy_id))
            actual = runner.connector._balance(venue, runner.now()).available
            runner.session.commit()
            return min(actual, result.cash_available, result.strategy_cash)
        strategy = runner.session.get(Strategy, runner.strategy_id)
        net = runner.connector.ledger.realized_after_fees(strategy_id=runner.strategy_id, mode="paper")
        modeled_fees = D(runner.state().get("modeled_regulatory_fees", "0"))
        return max(ZERO, min(runner.connector.cash().available,
                            strategy.allocation_usd + net - modeled_fees))


class Runner:
    def __init__(self, session, api, trial_id, *, now=None):
        self.session, self.api, self.trial_id = session, api, trial_id
        self.now = now or (lambda: datetime.now(UTC))
        trial = self.trial()
        self.strategy_id, self.iid = trial.strategy_id, trial.params["instrument_id"]
        self.connector = AlpacaPaperConnector(session, api, now=self.now)
        self.core = TurnOfMonth(trial.params)
        self.ctx, self.snapshots = Context(self), {}
        self.core.on_start(self.ctx)
        self.calendar = {row["date"]: MarketSession.from_api(row) for row in trial.params["calendar"]}
        self.checked_day, self.fx_day = None, None
        self.evidence_guard = None

    def sync_evidence_guard(self):
        """Local opt-in lookup only; no change to trial identity or schedule."""
        from tradingbot.connectors.alpaca_paper import NAME as CONNECTOR_NAME
        from tradingbot.forward.paper_evidence import EvidenceGuard, NAME as EVIDENCE_NAME
        venue = self.connector._venue(lock=True)
        required = (venue.metadata_ or {}).get(CONNECTOR_NAME, {}).get("guard_required")
        self.session.commit()
        if required is None:
            self.evidence_guard = self.connector.execution_guard = None
        elif required == EVIDENCE_NAME:
            if self.evidence_guard is None:
                self.evidence_guard = EvidenceGuard(self.calendar.values(), additional={self.iid})
            self.connector.execution_guard = self.evidence_guard
        else:
            raise OrderRejected("Unsupported account evidence policy")

    def trial(self, lock=False):
        stmt = select(Trial).where(Trial.id == self.trial_id).execution_options(populate_existing=True)
        trial = self.session.scalar(stmt.with_for_update() if lock else stmt)
        if trial is None or trial.mode != "paper" or trial.status != "running" or trial.code_version != NAME:
            raise ValueError("An explicitly prepared running paper trial is required")
        return trial

    def state(self): return dict(self.trial().metrics[NAME])

    def save(self, state):
        trial = self.trial()
        trial.metrics = {**trial.metrics, NAME: state}
        self.session.commit()

    def orders(self):
        return list(self.session.scalars(select(Order).where(Order.trial_id == self.trial_id, Order.mode == "paper", Order.status.in_(ACTIVE))))

    def incident(self, key, message):
        state = self.state()
        seen = list(state.get("incidents", []))
        if key in seen: return
        self.connector.risk.log_incident(severity="warning", category="other", mode="paper",
            strategy_id=self.strategy_id, instrument_id=self.iid, message=message, details={"trial_id": self.trial_id})
        self.session.flush()
        self.save({**state, "incidents": [*seen, key]})

    def mark(self):
        if self.evidence_guard is not None:
            venue = self.connector._venue(lock=True)
            result = self.evidence_guard(self.connector, PaperGuardContext(
                phase="refresh", now=self.now(), venue=venue))
            self.connector._refresh_risk(result, self.now())
            broker = self.connector.risk.strategy_pnl(self.strategy_id, "paper", result.marks)
            net = broker + result.strategy_pnl_offsets.get(self.strategy_id, ZERO)
            state = self.state()
            peak = max(D(state.get("peak_net", "0")), net)
            drawdown = max(D(state.get("max_drawdown", "0")), peak - net)
            fees = sum((D(row["extra_fee_usd"]) for row in result.details["fees"]
                        if row["strategy_id"] == self.strategy_id), ZERO)
            self.save({**state, "last_mark_at": self.now().isoformat(), "broker_pnl": str(broker),
                "modeled_regulatory_fees": str(fees), "fee_scenario": result.details["policy"],
                "net_with_fee_scenario": str(net), "peak_net": str(peak), "max_drawdown": str(drawdown),
                "daily_net": {**state.get("daily_net", {}), self.now().astimezone(NEW_YORK).date().isoformat(): str(net)},
                "account_evidence": result.details})
            return
        # Shared mode-wide mark set, including positions from other strategies.
        marks = {}
        ids = set(self.session.scalars(select(Position.instrument_id).where(Position.mode == "paper", Position.status == "open")))
        for iid in ids | {self.iid}:
            q = self.session.scalar(select(Quote).where(Quote.instrument_id == iid, Quote.time <= self.now())
                .order_by(Quote.time.desc(), Quote.id.desc()).limit(1))
            if q is not None:
                value = q.mid if q.mid is not None else q.last
                if value is None and q.bid is not None and q.ask is not None: value = (q.bid + q.ask) / 2
                if value is not None: marks[iid] = value
        self.connector.risk.refresh_halts("paper", marks, now=self.now())
        state = self.state()
        pnl = self.connector.risk.strategy_pnl(self.strategy_id, "paper", marks)
        fees = EquityFeeBook()
        modeled = sum((fees.charge(day=f.fill_ts.astimezone(NEW_YORK).date(), side=f.side, price=f.price, size=f.size)[0]
            for f in self.session.scalars(select(Fill).where(Fill.trial_id == self.trial_id).order_by(Fill.fill_ts, Fill.id))), ZERO)
        equity = pnl - modeled
        peak = max(D(state.get("peak_net", "0")), equity)
        drawdown = max(D(state.get("max_drawdown", "0")), peak - equity)
        daily = {**state.get("daily_net", {}), self.now().astimezone(NEW_YORK).date().isoformat(): str(equity)}
        self.save({**state, "last_mark_at": self.now().isoformat(), "broker_pnl": str(pnl),
            "modeled_regulatory_fees": str(modeled), "fee_scenario": fees.policy,
            "net_with_fee_scenario": str(equity), "peak_net": str(peak), "max_drawdown": str(drawdown), "daily_net": daily})

    def step(self):
        now = self.now()
        self.trial()  # detect a stopped trial before polling known orders
        self.sync_evidence_guard()
        evidence_error = False
        if self.evidence_guard is not None:
            try:
                self.evidence_guard.capture(self.connector)
            except (ValueError, OrderRejected, PaperAPIError):
                self.session.rollback()
                evidence_error = True
        pending = self.orders()
        for order in pending:
            try:
                self.connector.refresh(order.id)
            except PaperEvidenceUnavailable:
                evidence_error = True  # real executions remain committed
        day = now.astimezone(NEW_YORK).date().isoformat()
        session = self.calendar.get(day)
        state = self.state()
        attempts = dict(state["attempts"])
        for planned, action in self.core.params["schedule"].items():
            close = self.calendar[planned].closes_at
            if close <= now and planned not in attempts:
                attempts[planned] = {"status": "missed_window", "side": action}
                self.save({**self.state(), "attempts": attempts})
                if action == "sell" and self.ctx.position(self.iid) > 0:
                    self.incident("missed-exit-" + planned, "Turn-of-month paper exit window missed; owned shares remain; no off-schedule liquidation.")
            # Only assess the most recent scheduled exit: an old exit followed
            # by a later valid buy must not be diagnosed as an incomplete exit.
            latest_action = max((d for d in self.core.params["schedule"] if d <= day), default=None)
            if (planned == latest_action and action == "sell" and close <= now
                    and self.ctx.position(self.iid) > 0):
                self.incident("residual-exit-" + planned, "Turn-of-month paper exit incomplete; residual shares remain for explicit review.")
            if close <= now and attempts.get(planned, {}).get("status") == "claimed":
                self.incident("claimed-" + planned, "Turn-of-month paper attempt interrupted before receipt; inspect durable connector order; never automatically resend.")
        # DAY order expiry/fill races are polled explicitly. No cancellation on exit.
        if session is None or not session.is_open(now):
            if self.evidence_guard is None and (pending or state.get("last_mark_at", "")[:10] != now.date().isoformat()):
                self.mark()
            return "outside_session"
        if evidence_error:
            self.incident("account-evidence-" + day,
                          "SPY paper account evidence unavailable; known fills retained and new intents held.")
            return "evidence_hold"
        if self.checked_day != day:
            actual = self.connector._calendar(date.fromisoformat(day))
            if actual != session:
                raise OrderRejected("Recorded calendar differs from today's official calendar; review the plan")
            self.checked_day = day
        action = self.core.params["schedule"].get(day)
        due = action and session.closes_at - timedelta(seconds=60) <= now < session.closes_at
        if self.ctx.position(self.iid) > 0 or (due and day not in attempts):
            instrument = self.session.get(Instrument, self.iid)
            q = self.connector._capture_quote(instrument)
            self.session.commit()
            if not 0 <= (self.now() - q.time).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
                raise OrderRejected("No fresh IEX quote")
            event = MarketEvent.quote(self.iid, q.time, bid=q.bid, ask=q.ask)
            self.snapshots[self.iid] = event.as_snapshot()
        else:
            event = None
        if event is not None or pending or state.get("last_mark_at", "")[:10] != now.date().isoformat():
            self.mark()
        if not due or day in attempts or self.orders(): return "observing"
        self.core._attempted = set(attempts)  # same pure reactor, durable day state
        intents = self.core.on_event(self.ctx, event)
        if not intents:
            # A flat exit / held entry is also a once-only scheduled observation.
            self.save({**self.state(), "attempts": {**attempts, day: {"status": "no_intent", "side": action}}})
            return "no_intent"
        intent = intents[0]
        if not session.closes_at - timedelta(seconds=60) <= self.now() < session.closes_at:
            return "window_elapsed"
        fx = self.session.scalar(select(FxRate.ts).where(FxRate.base == "USD", FxRate.quote == "GBP", FxRate.ts <= now).order_by(FxRate.ts.desc()).limit(1))
        if fx is None or now - fx > timedelta(days=7):
            raise OrderRejected("Recent dated USD/GBP reference required before submission")
        # Serialize the attempt before crossing the network, including a crash
        # between this commit and the connector's own durable POST reservation.
        trial = self.trial(lock=True)
        state = dict(trial.metrics[NAME]); attempts = dict(state["attempts"])
        if day in attempts:
            self.session.commit()
            return "already_attempted"
        request_id = f"tom-{self.trial_id}-{day.replace('-', '')}-{intent.side}"
        attempt = {"status": "claimed", "side": intent.side, "quantity": str(intent.size),
            "limit": str(intent.limit_price), "request_id": request_id, "at": self.now().isoformat(),
            "decision_bid": str(event.bid), "decision_ask": str(event.ask), "quote_at": event.time.isoformat()}
        trial.metrics = {**trial.metrics, NAME: {**state, "attempts": {**attempts, day: attempt}}}
        self.session.commit()
        try:
            if self.evidence_guard is not None:
                # Re-age every exposure, preserving the frozen closing window.
                self.evidence_guard.capture(self.connector, valid_until=session.closes_at)
            result = self.connector.submit_limit(request_id=request_id, instrument_id=self.iid,
                strategy_id=self.strategy_id, trial_id=self.trial_id, side=intent.side,
                quantity=intent.size, limit_price=intent.limit_price)
            attempt.update(status=result.status, order_id=result.order_id, submission_unknown=result.submission_unknown)
        except (ValueError, OrderRejected, PaperAPIError) as exc:
            attempt["status"] = type(exc).__name__
            self.incident("attempt-" + day, "Turn-of-month paper attempt rejected or unavailable; no retry for this session.")
        self.save({**self.state(), "attempts": {**self.state()["attempts"], day: attempt}})
        return attempt["status"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--through", type=date.fromisoformat, required=True)
    slot = sub.add_parser("prepare-slot")
    slot.add_argument("--through", type=date.fromisoformat, required=True)
    slot.add_argument("--training-id", type=int, required=True)
    slot.add_argument("--holdout-id", type=int, required=True)
    slot.add_argument("--supersede-id", type=int, required=True)
    run = sub.add_parser("run")
    run.add_argument("--trial-id", type=int, required=True)
    run.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    api = AlpacaPaperAPI.from_env()
    try:
        with SessionLocal() as session:
            if args.command == "prepare-slot":
                with get_engine().connect() as lock:
                    if not lock.scalar(text("SELECT pg_try_advisory_lock(60426, :trial)"), {"trial": args.supersede_id}):
                        raise ValueError("The existing paper runner must be stopped before superseding")
                    import_fx(session, fetch_fx(), datetime.now(UTC))
                    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
                    print(json.dumps({"trial_id": prepare_slot(session, api, through=args.through,
                        training_id=args.training_id, holdout_id=args.holdout_id,
                        supersede_id=args.supersede_id, commit=commit)}))
                    return
            if args.command == "prepare":
                import_fx(session, fetch_fx(), datetime.now(UTC))
                commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
                print(json.dumps({"trial_id": prepare(session, api, through=args.through, commit=commit)}))
                return
            # Dedicated connection keeps this lock across connector commits.
            # This is process coordination, not account/order reconciliation.
            with get_engine().connect() as lock:
                if not lock.scalar(text("SELECT pg_try_advisory_lock(60426, :trial)"), {"trial": args.trial_id}):
                    return
                runner = Runner(session, api, args.trial_id)
                while True:
                    try:
                        day = runner.now().date()
                        if runner.fx_day != day:
                            import_fx(session, fetch_fx(), runner.now())
                            runner.fx_day = day
                        runner.step()
                    except Exception as exc:
                        session.rollback()
                        # Never print remote exceptions / credential-bearing URLs.
                        print(json.dumps({"incident": type(exc).__name__, "trial_id": args.trial_id,
                                          "at": datetime.now(UTC).isoformat()}), flush=True)
                        if args.once: raise SystemExit(1) from None
                        clock.sleep(60)
                        continue
                    if args.once: break
                    clock.sleep(10)
    finally:
        api.close()


if __name__ == "__main__":
    main()
