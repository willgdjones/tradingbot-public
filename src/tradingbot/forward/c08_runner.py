"""Finite, explicit C08 paper experiment over the unchanged inventory reactor.

Preparation and activation are separate. The runner polls only its known local
intents and never retries a claimed opening phase after a crash.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from functools import wraps
import json
from pathlib import Path
import subprocess
import time

from sqlalchemy import select, text

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import (
    ACTIVE, NAME as CONNECTOR, AlpacaPaperConnector, OrderRejected, PaperEvidenceUnavailable,
    PaperGuardContext,
)
from tradingbot.connectors.cash import MarketSession, NEW_YORK, timestamp
from tradingbot.db.models import Fill, FxRate, Instrument, Order, Position, Strategy, Trial, Venue
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.forward.c05_readiness import distribution_entitlement
from tradingbot.forward.c08_readiness import REACTOR, ROOT, VERSION, digest, encoded, historical_evidence
from tradingbot.forward.c08_sources import admission, read_receipt
from tradingbot.forward.c08_state import NAME, PARAMS, WINDOW, calendar_plan, dump_core, eligible_release, phases, restore_core
from tradingbot.forward.paper_evidence import NAME as EVIDENCE, EvidenceGuard, account_evidence, save_evidence, schedule_income_event
from tradingbot.strategy import MarketEvent, MarketSnapshot, StrategyContext

ZERO = D(0)


def atomic(method):
    @wraps(method)
    def call(session, *args, **kwargs):
        try:
            return method(session, *args, **kwargs)
        except Exception:
            session.rollback()
            raise
    return call


def _schedule_income_actions(session, venue, admitted, sessions, iid, now):
    for action in admitted["actions"]:
        if action["kind"] != "ordinary_cash":
            continue
        source = (ROOT / admitted["review"]["watch"]["path"]).parent / action["issuer_source"]
        event = {**action, "source_receipt": {"path": str(source.relative_to(ROOT)),
                                              "sha256": digest(source.read_bytes())}}
        schedule_income_event(session, venue, event, sessions, instrument_id=iid, now=now)


def dependencies():
    names = ("forward/c08_runner.py", "forward/c08_state.py", "forward/c08_sources.py",
             "forward/c08_readiness.py", "forward/c05_readiness.py", "forward/paper_evidence.py",
             "connectors/alpaca_paper.py", "connectors/alpaca_api.py", "connectors/cash.py",
             "research/equity_fees.py", "risk/engine.py", "risk/limits.py", "strategy/c08_inventory.py")
    return {name: digest((ROOT / "src/tradingbot" / name).read_bytes()) for name in names}


def verify_binding(trial):
    if trial.params["dependencies"] != dependencies():
        raise ValueError("C08 forward implementation changed; explicit reviewed continuation required")
    if trial.params["reactor_sha256"] != REACTOR or trial.strategy_version != VERSION:
        raise ValueError("Frozen C08 research identity changed")
    if any(trial.params.get(key) != value for key, value in PARAMS.items()):
        raise ValueError("Frozen C08 parameters changed")
    phases(trial.params)


def prepare(session, api, *, through, review_ref, commit, now=None):
    """Record every preparation, including rejection; never activate or fund it."""
    now = timestamp(now or datetime.now(UTC))
    history = historical_evidence(session)
    strategy = session.get(Strategy, history["rows"][0]["strategy_id"])
    session.execute(text("SELECT pg_advisory_xact_lock(60800, :strategy)"), {"strategy": strategy.id})
    if session.scalar(select(Trial.id).where(Trial.strategy_id == strategy.id,
            Trial.mode == "paper", Trial.status == "running")):
        raise ValueError("Resume the existing C08 experiment explicitly")
    trial = Trial(strategy_id=strategy.id, mode="paper", code_version=NAME, git_commit=commit,
                  strategy_version=VERSION, data_start=now,
                  params={**PARAMS, "source_review": review_ref, "historical_evidence": history,
                          "reactor_sha256": REACTOR, "dependencies": dependencies()},
                  metrics={NAME: {"enabled": False, "phases": {}, "incidents": [], "core": None}},
                  notes="Prepared only; account/source/promotion activation required. No historical replay.")
    session.add(trial)
    session.commit()
    trial_id, stage = trial.id, "account_calendar"
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    try:
        venue = connector._venue()
        book = connector._book(venue)
        if D(book["initial_cash"]) != D(140):
            raise ValueError("C08 requires the existing unchanged shared $140 paper book")
        account = connector._call(api.account)
        connector._account_ok(account)
        if connector._fingerprint(account) != book["account"]:
            raise ValueError("Current account differs from the shared cash book")
        rows = connector._call(api.calendar_range, now.date() - timedelta(days=10), through + timedelta(days=10))
        plan = calendar_plan(rows, start=now, through=through)
        sessions = [MarketSession.from_api(row) for row in rows]
        stage = "source_admission"
        admitted = admission(review_ref, sessions, as_of=now)
        stage = "instrument_and_exposure"
        iid = connector.register_equity("USO")
        if strategy.status == "killed" or session.scalar(select(Position.id).where(
                Position.strategy_id == strategy.id, Position.mode == "paper", Position.quantity != 0)):
            raise ValueError("Existing C08 exposure or permanent kill requires continuation review")
        if session.scalar(select(Order.id).where(Order.strategy_id == strategy.id,
                Order.mode == "paper", Order.status.in_(ACTIVE))):
            raise ValueError("Existing C08 pending intents require continuation")
        trial = session.get(Trial, trial_id)
        trial.params = {**trial.params, **plan, "uso_id": iid, "blackouts": admitted["blackouts"]}
        trial.metrics = {NAME: {"enabled": False, "phases": {}, "incidents": [],
                               "core": dump_core(restore_core(trial.params)), "source_review": review_ref,
                               "blackouts": admitted["blackouts"],
                               "decision": "prepared_held_for_activation"}}
        session.commit()
        return {"trial_id": trial_id, "status": "prepared_held_for_activation", "orders": 0}
    except Exception as exc:
        session.rollback()
        trial = session.get(Trial, trial_id)
        trial.status, trial.completed_ts = "failed", now
        trial.notes = f"C08 preparation held at {stage}: {type(exc).__name__}. No activation, orders or replay."
        trial.metrics = {NAME: {"enabled": False, "phases": {}, "incidents": [], "core": None,
                               "decision": "hold_before_paper", "failure_stage": stage,
                               "failure_type": type(exc).__name__}}
        session.commit()
        return {"trial_id": trial_id, "status": "failed", "failure_stage": stage,
                "failure_type": type(exc).__name__, "orders": 0}


@atomic
def activate(session, api, trial_id, *, decision_ref, now=None):
    now = timestamp(now or datetime.now(UTC))
    trial = session.get(Trial, trial_id)
    if trial is None or trial.status != "running" or trial.code_version != NAME or trial.mode != "paper":
        raise ValueError("A separately prepared running C08 trial is required")
    verify_binding(trial)
    decision = json.loads(read_receipt(decision_ref))
    if (decision.get("trial_id") != trial_id or decision.get("decision") != "activate_paper"
            or not decision.get("promotion_checklist_complete") or not decision.get("account_integration_verified")
            or len(decision.get("what_could_blow_up_this_account", "")) < 100
            or timestamp(decision["reviewed_at"]) > now):
        raise ValueError("Complete written paper promotion/account-risk decision required")
    state = trial.metrics[NAME]
    if state["phases"] or state["enabled"]:
        raise ValueError("Used experiments must be resumed, not reactivated")
    sessions = [MarketSession.from_api(row) for row in trial.params["calendar"]]
    admitted = admission(state["source_review"], sessions, as_of=now)
    if now >= phases(trial.params)[0][2]:
        raise ValueError("Activation must precede the first scheduled open")
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    account = connector._call(api.account)
    connector._account_ok(account)
    venue = connector._venue(lock=True)
    book = connector._book(venue)
    if (book.get("guard_required") != EVIDENCE or D(book["initial_cash"]) != 140
            or connector._fingerprint(account) != book["account"]):
        raise ValueError("Shared paper evidence migration must already be admitted")
    strategy = session.get(Strategy, trial.strategy_id, populate_existing=True)
    trial = session.get(Trial, trial_id, populate_existing=True)
    state = deepcopy(trial.metrics[NAME])
    if state["phases"] or state["enabled"] or trial.status != "running":
        raise ValueError("C08 activation state changed during account verification")
    if strategy.status == "killed":
        raise ValueError("A permanent strategy kill cannot be activated")
    _schedule_income_actions(session, venue, admitted, sessions, trial.params["uso_id"], now)
    strategy.status, strategy.allocation_usd = "paper", D(140)
    evidence = account_evidence(session, venue, now, sessions)
    baseline = connector.risk.strategy_pnl(strategy.id, "paper") + evidence.strategy_pnl_offset(strategy.id)
    trial.metrics = {**trial.metrics, NAME: {**state, "enabled": True, "activation_at": now.isoformat(),
        "baseline_strategy_pnl": str(baseline), "activation_decision": decision_ref,
        "decision": "active_paper_not_ready_for_live"}}
    session.commit()


class Context(StrategyContext):
    def __init__(self, runner): self.runner = runner
    @property
    def now(self): return self.runner.now()
    @property
    def mode(self): return "paper"
    @property
    def params(self): return self.runner.core.params
    def snapshot(self, instrument_id): return self.runner.snapshots.get(instrument_id)
    def position(self, instrument_id):
        row = self.runner.connector.ledger.get_position(self.runner.strategy_id, "paper", instrument_id)
        return row.quantity if row else ZERO
    def open_orders(self, instrument_id=None):
        return tuple(o for o in self.runner.orders() if instrument_id is None or o.instrument_id == instrument_id)
    def resting_tags(self, instrument_id=None):
        return tuple(o.metadata_["client_order_id"] for o in self.open_orders(instrument_id))
    def available_cash(self, instrument_id):
        if instrument_id != self.runner.iid or self.runner.evidence is None:
            return None
        return min(self.runner.evidence.cash_available, self.runner.evidence.strategy_cash(self.runner.strategy_id),
                   self.runner.transport_cash)
    def marked_equity(self):
        if self.runner.evidence is None:
            return None
        pnl = self.runner.connector.risk.strategy_pnl(self.runner.strategy_id, "paper", self.runner.marks)
        return D(140) + pnl + self.runner.evidence.strategy_pnl_offset(self.runner.strategy_id)


class Runner:
    def __init__(self, session, api, trial_id, *, now=None):
        self.session, self.api, self.trial_id = session, api, trial_id
        self.now = now or (lambda: datetime.now(UTC))
        trial = self.trial()
        verify_binding(trial)
        self.strategy_id, self.iid = trial.strategy_id, trial.params["uso_id"]
        self.sessions = [MarketSession.from_api(row) for row in trial.params["calendar"]]
        self.schedule = phases(trial.params)
        self.core = restore_core({**trial.params, "blackouts": self.state().get("blackouts", trial.params["blackouts"])}, self.state()["core"])
        self.guard = EvidenceGuard(self.sessions, additional=(self.iid,))
        self.connector = AlpacaPaperConnector(session, api, now=self.now, execution_guard=self._guard)
        self.ctx = Context(self)
        self.snapshots, self.marks = {}, {}
        self.evidence, self.admitted, self.current_phase = None, None, None
        self.transport_cash = ZERO

    def trial(self, *, lock=False):
        stmt = select(Trial).where(Trial.id == self.trial_id).execution_options(populate_existing=True)
        trial = self.session.scalar(stmt.with_for_update() if lock else stmt)
        if trial is None or trial.mode != "paper" or trial.code_version != NAME or trial.status != "running":
            raise ValueError("Explicitly prepared running C08 trial required")
        return trial

    def state(self): return deepcopy(self.trial().metrics[NAME])

    def save(self, state):
        trial = self.trial(lock=True)
        trial.metrics = {**trial.metrics, NAME: state}
        self.session.commit()

    def orders(self):
        return list(self.session.scalars(select(Order).where(Order.trial_id == self.trial_id,
            Order.mode == "paper", Order.status.in_(ACTIVE))))

    def hold(self, key, message):
        state = self.state()
        if key not in state["incidents"]:
            self.connector.risk.log_incident(severity="warning", category="other", mode="paper",
                strategy_id=self.strategy_id, instrument_id=self.iid, message=message,
                details={"trial_id": self.trial_id, "key": key})
            state["incidents"].append(key)
        state["hold"] = {"key": key, "message": message, "at": self.now().isoformat()}
        self.save(state)

    def _guard(self, connector, context):
        if connector._book(context.venue).get("guard_required") != EVIDENCE:
            raise OrderRejected("C08 requires the admitted shared account evidence policy")
        result = self.guard(connector, context)
        if context.phase == "refresh":
            return result
        state = self.state()
        phase = state["phases"].get(self.current_phase)
        if not state["enabled"] or state.get("hold") or phase is None or phase["status"] != "claimed":
            raise OrderRejected("C08 phase is not a current enabled durable intent")
        if self.session.get(Strategy, self.strategy_id).allocation_usd != D(PARAMS["slot_usd"]):
            raise OrderRejected("C08 allocation differs from its frozen paper slot")
        opened = timestamp(phase["scheduled_at"])
        if not opened <= context.now < opened + WINDOW:
            raise OrderRejected("C08 opening submission window elapsed")
        if (context.quote is None or context.quote.time < opened
                or self.admitted is None or phase["source_review"] != self.admitted["review_ref"]
                or state["source_review"] != phase["source_review"]):
            raise OrderRejected("C08 quote/source changed since its opening decision")
        return replace(result, valid_until=min(result.valid_until, opened + WINDOW),
                       details={**result.details, "c08_phase": self.current_phase,
                                "c08_source_review": phase["source_review"], "decision_quote": phase["quote"]})

    def _income(self, admitted):
        """Recognize modeled entitlement for every attributed USO paper owner."""
        for action in admitted["actions"]:
            if action["kind"] != "ordinary_cash" or date.fromisoformat(action["ex_date"]) > self.now().astimezone(NEW_YORK).date():
                continue
            venue = self.connector._venue(lock=True)
            ex_open = next(s.opens_at for s in self.sessions if str(s.trade_date) == action["ex_date"])
            if self.session.scalar(select(Order.id).where(Order.instrument_id == self.iid,
                    Order.mode == "paper", Order.status.in_(ACTIVE), Order.created_ts < ex_open)):
                raise ValueError("Unresolved pre-ex orders prevent a known income entitlement")
            source_path = (ROOT / admitted["review"]["watch"]["path"]).parent / action["issuer_source"]
            event = {**action, "source_sha256": digest(source_path.read_bytes()),
                     "source_observed_at": action["observed_at"]}
            fills = list(self.session.scalars(select(Fill).where(Fill.instrument_id == self.iid,
                Fill.mode == "paper").order_by(Fill.fill_ts, Fill.id)))
            for sid in {f.strategy_id for f in fills}:
                if sid is None:
                    raise ValueError("Unattributed income entitlement requires review")
                rows = [{"id": f.id, "symbol": "USO", "side": f.side, "quantity": str(f.size),
                         "fill_at": f.fill_ts.isoformat()} for f in fills if f.strategy_id == sid]
                entitled = distribution_entitlement(event, rows, self.sessions, self.now())
                entitled.update(strategy_id=sid, source_receipt={"path": str(source_path.relative_to(ROOT)),
                                                                "sha256": event["source_sha256"]})
                old = [r for r in (venue.metadata_ or {}).get(EVIDENCE, {}).get("incomes", [])
                       if r["strategy_id"] == sid and r["event_id"] == entitled["event_id"]]
                if old:
                    facts = ("amount_per_share", "quantity_before_ex_open", "cash_amount", "recognized_at", "modeled_release_at")
                    if len(old) != 1 or any(old[0][k] != entitled[k] for k in facts):
                        raise ValueError("Previously recognized entitlement changed")
                else:
                    save_evidence(venue, income=entitled)
            self.session.commit()

    def _capture(self, deadline=None):
        if self.connector._book(self.connector._venue()).get("guard_required") != EVIDENCE:
            raise OrderRejected("C08 requires the admitted shared account evidence policy")
        quotes = self.guard.capture(self.connector, valid_until=deadline)
        self.snapshots = {iid: MarketSnapshot(iid, timestamp(q["t"]), bid=D(str(q["bp"])), ask=D(str(q["ap"])))
                          for iid, q in quotes.items()}
        self.marks = {iid: (q.bid + q.ask) / 2 for iid, q in self.snapshots.items()}
        venue = self.connector._venue(lock=True)
        self.evidence = account_evidence(self.session, venue, self.now(), self.sessions)
        self.transport_cash = self.connector._balance(venue, self.now()).available
        self.connector._refresh_risk(self.guard(self.connector, PaperGuardContext(
            phase="refresh", now=self.now(), venue=venue)), self.now())
        self.session.commit()

    def _reconcile(self):
        state = self.state()
        for tag, phase in state["phases"].items():
            if "request_id" not in phase:
                continue
            order = self.session.scalar(select(Order).where(Order.trial_id == self.trial_id,
                Order.metadata_["client_order_id"].as_string() == "tbp-" + phase["request_id"]))
            if order is None:
                if phase["status"] == "claimed":
                    self.hold("interrupted-" + tag, "C08 interrupted claimed phase has no connector receipt; never resend it.")
                continue
            if order.status in ACTIVE:
                try:
                    self.connector.refresh(order.id)
                except PaperEvidenceUnavailable:
                    pass  # receipt survived; a later complete mark batch reevaluates risk
                if self.now() >= timestamp(phase["scheduled_at"]) + WINDOW and order.status in ACTIVE:
                    self.connector.cancel(order.id)
            phase.update(status=order.status, order_id=order.id,
                         submission_unknown=bool(order.metadata_.get("submission_unknown")), filled_quantity=str(order.filled_size))
            receipts = []
            for fill in self.session.scalars(select(Fill).where(Fill.order_id == order.id).order_by(Fill.fill_ts, Fill.id)):
                reference = D(phase["quote"]["ask"] if order.side == "buy" else phase["quote"]["bid"])
                adverse = (fill.price / reference - 1) * (1 if order.side == "buy" else -1) * 10000
                receipts.append({"fill_id": fill.id, "at": fill.fill_ts.isoformat(), "price": str(fill.price),
                                 "quantity": str(fill.size), "broker_fee": str(fill.fee),
                                 "decision_quote_adverse_bp": str(adverse), "actual_paper_fill": True,
                                 "inside_first_minute": fill.fill_ts < timestamp(phase["scheduled_at"]) + WINDOW})
            phase["fill_receipts"] = receipts
            latest = self.state()
            latest["phases"][tag] = phase
            self.save(latest)
            if phase["mandatory_exit"] and (phase["submission_unknown"] or order.status in
                    {"partially_filled", "rejected", "canceled", "expired"} or
                    (self.now() >= timestamp(phase["scheduled_at"]) + WINDOW and order.status != "filled")):
                if order.filled_size < order.size:
                    self.hold("exit-" + tag, "C08 mandatory exit incomplete or unknown; residual exposure requires explicit resolution.")

    def _record_mark(self):
        if self.evidence is None:
            return
        state = self.state()
        net = self.ctx.marked_equity() - D(140) - D(state.get("baseline_strategy_pnl", "0"))
        peak = max(D(state.get("peak_net", "0")), net)
        state.update(last_mark_at=self.now().isoformat(), net_with_fee_income_scenario=str(net),
                     peak_net=str(peak), max_drawdown=str(max(D(state.get("max_drawdown", "0")), peak - net)),
                     account_evidence=self.evidence.details)
        self.save(state)

    def step(self):
        trial = self.trial()
        verify_binding(trial)
        state, now = self.state(), self.now()
        regular = next((s for s in self.sessions if s.is_open(now)), None)
        if regular and self.orders():
            try:
                self._capture()
            except Exception:
                self.evidence = None
        self._reconcile()  # only durable known intents, even if strategy/source held
        if regular and self.guard.quotes is not None and self.now() < self.guard.deadline:
            venue = self.connector._venue(lock=True)
            self.evidence = account_evidence(self.session, venue, self.now(), self.sessions)
            self.transport_cash = self.connector._balance(venue, self.now()).available
            self.session.commit()
            self._record_mark()
        state = self.state()
        if not state["enabled"]:
            return "prepared_held"
        if state.get("hold"):
            return "held_for_resolution"
        for tag, phase, at, calendar in self.schedule:
            if tag in state["phases"] or now < at:
                continue
            quantity = self.ctx.position(self.iid)
            if now >= at + WINDOW:
                state["phases"][tag] = {"status": "missed_window", "scheduled_at": at.isoformat(), "phase": phase}
                self.save(state)
                plans = state.get("blackouts", self.core.params["blackouts"])
                required = (phase == "open" and (str(calendar.trade_date) == trial.params["terminal_date"]
                            or any(p["exit"] == str(calendar.trade_date) for p in plans)))
                required |= phase == "close" and any(p["decision"] == str(calendar.trade_date) for p in plans)
                latest = state["core"]["latest"]
                required |= phase == "open" and latest is not None and (
                    calendar.trade_date > date.fromisoformat(latest["release_date"]) + timedelta(days=14)
                    or D(latest["scarcity"]) >= D(PARAMS["threshold"]))
                if quantity and required:
                    self.hold("missed-" + tag, "C08 required action/terminal phase missed; no off-window catch-up.")
                    return "held_for_resolution"
                state = self.state()
                continue
            try:
                self.admitted = admission(state["source_review"], self.sessions, as_of=at)
                self._income(self.admitted)
                self.core = restore_core({**trial.params, "blackouts": self.admitted["blackouts"]}, state["core"])
                if phase == "open":
                    self._capture(at + WINDOW)
                    source = eligible_release(self.admitted["eia"], reviewed_at=self.admitted["review"]["reviewed_at"], scheduled_open=at)
                    meta = {"phase": phase, "releases": [source] if source else [],
                            "terminal_open": str(calendar.trade_date) == trial.params["terminal_date"]}
                else:
                    meta = {"phase": phase}
                event = MarketEvent.quote(self.iid, at, meta=meta)
                intents = self.core.on_event(self.ctx, event)
                if phase == "close" and intents:
                    raise ValueError("C08 close callback must never submit")
                if len(intents) > 1 or self.orders():
                    raise ValueError("C08 phase has ambiguous or pending exposure")
                if self.now() >= at + WINDOW:
                    raise ValueError("C08 phase window elapsed during evidence capture")
                trial = self.trial(lock=True)
                state = deepcopy(trial.metrics[NAME])
                if tag in state["phases"]:
                    self.session.commit()
                    return "already_observed"
                observed = {"status": "no_intent", "phase": phase, "scheduled_at": at.isoformat(),
                            "observed_at": self.now().isoformat(), "source_review": state["source_review"]}
                if intents:
                    fx = self.session.scalar(select(FxRate.ts).where(FxRate.base == "USD", FxRate.quote == "GBP",
                        FxRate.ts <= now).order_by(FxRate.ts.desc()).limit(1))
                    if fx is None or now - fx > timedelta(days=7):
                        raise ValueError("Recent dated FX reference required before an intent")
                    intent, quote = intents[0], self.snapshots[self.iid]
                    observed.update(status="claimed", side=intent.side, quantity=str(intent.size), limit=str(intent.limit_price),
                        request_id=f"c08-{self.trial_id}-{calendar.trade_date:%Y%m%d}-{intent.side}",
                        mandatory_exit=intent.side == "sell", reason=intent.reason,
                        quote={"at": quote.time.isoformat(), "bid": str(quote.bid), "ask": str(quote.ask)})
                state["core"], state["phases"][tag] = dump_core(self.core), observed
                state["blackouts"] = self.admitted["blackouts"]
                trial.metrics = {**trial.metrics, NAME: state}
                self.session.commit()  # once-only phase and core state before any connector call
                if intents:
                    self.current_phase = tag
                    try:
                        result = self.connector.submit_limit(request_id=observed["request_id"], instrument_id=self.iid,
                            strategy_id=self.strategy_id, trial_id=self.trial_id, side=intent.side,
                            quantity=intent.size, limit_price=intent.limit_price)
                        observed.update(status=result.status, order_id=result.order_id, submission_unknown=result.submission_unknown)
                    except Exception as exc:
                        observed["status"] = "submission_held_" + type(exc).__name__
                    state = self.state()
                    state["phases"][tag] = observed
                    self.save(state)
                    if observed["mandatory_exit"] and (observed.get("submission_unknown")
                            or observed["status"] in {"rejected", "canceled", "expired"}
                            or observed["status"].startswith("submission_held")):
                        self.hold("exit-" + tag, "C08 mandatory exit was vetoed or submission outcome is unknown.")
                if phase == "open":
                    self._record_mark()
                return observed["status"]
            except Exception as exc:
                self.session.rollback()
                state = self.state()
                if tag not in state["phases"]:
                    state["phases"][tag] = {"status": "evidence_held", "phase": phase,
                        "scheduled_at": at.isoformat(), "failure_type": type(exc).__name__}
                    self.save(state)
                self.hold("evidence-" + tag, "C08 phase failed source, action, account or risk evidence; review before resuming.")
                return "held_for_resolution"
        terminal = self.schedule[-1]
        state = self.state()
        if now >= terminal[2] and terminal[0] in state["phases"]:
            if self.ctx.position(self.iid) or self.orders():
                if now < terminal[2] + WINDOW:
                    return "awaiting_terminal_fill"
                self.hold("terminal-residual", "C08 finite experiment ended with residual shares/orders; success withheld.")
                return "held_for_resolution"
            if state["phases"][terminal[0]]["status"] not in {"no_intent", "filled"}:
                return "terminal_unverified"
            trial = self.trial(lock=True)
            fills = list(self.session.scalars(select(Fill).where(Fill.trial_id == self.trial_id,
                Fill.mode == "paper").order_by(Fill.fill_ts, Fill.id)))
            actual_fees = sum((f.fee for f in fills), ZERO)
            gross = sum((f.realized_pnl or ZERO for f in fills), ZERO)
            if self.evidence is None:
                venue = self.connector._venue(lock=True)
                self.evidence = account_evidence(self.session, venue, self.now(), self.sessions)
            ids = {f.id for f in fills}
            modeled = sum((max(D(r["actual_fee_usd"]), D(r["modeled_fee_usd"]))
                for r in self.evidence.details["fees"] if r["fill_id"] in ids), ZERO)
            trial.pnl, trial.fees_total = gross, modeled
            trial.pnl_after_fees = D(state.get("net_with_fee_income_scenario", "0"))
            trial.trade_count = len(self.connector.ledger.round_trips(
                strategy_id=self.strategy_id, mode="paper", trial_id=self.trial_id))
            trial.max_drawdown = D(state.get("max_drawdown", "0"))
            trial.metrics = {**trial.metrics, "execution_audit": {
                "actual_fill_count": len(fills), "broker_fees_usd": str(actual_fees),
                "modeled_fees_usd": str(modeled), "broker_gross_usd": str(gross),
                "income_in_pnl_not_broker_cash": True, "calendar_months": sorted({f.fill_ts.strftime("%Y-%m") for f in fills}),
                "drawdown_sampling": "accepted complete portfolio quote batches",
                "slippage_reference": "IEX decision quote, not NBBO or primary opening auction",
                "live_fidelity_established": False, "ready_for_live": False}}
            trial.status, trial.completed_ts = "complete", now
            trial.notes = (trial.notes or "") + " Terminal flat state verified; paper execution is not live readiness."
            self.session.commit()
            return "complete"
        return "observing"


@atomic
def bind_review(session, trial_id, review_ref, *, now=None):
    """Admit a new immutable watch without erasing prior decisions or a hold."""
    now = timestamp(now or datetime.now(UTC))
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca").with_for_update()
                           .execution_options(populate_existing=True))
    if venue is None:
        raise ValueError("Existing Alpaca paper venue required")
    trial = session.scalar(select(Trial).where(Trial.id == trial_id).with_for_update())
    if trial is None or trial.code_version != NAME or trial.status != "running":
        raise ValueError("Running C08 experiment required")
    sessions = [MarketSession.from_api(row) for row in trial.params["calendar"]]
    admitted = admission(review_ref, sessions, as_of=now)
    _schedule_income_actions(session, venue, admitted, sessions, trial.params["uso_id"], now)
    state = deepcopy(trial.metrics[NAME])
    state["source_review"] = review_ref
    state["blackouts"] = admitted["blackouts"]
    state.setdefault("review_history", []).append({"review": review_ref, "bound_at": now.isoformat()})
    trial.metrics = {**trial.metrics, NAME: state}
    session.commit()


def resolve_flat_hold(session, trial_id, resolution_ref, *, now=None):
    """Explicit reviewed resolution only while flat; no erased attempts or halts."""
    now = timestamp(now or datetime.now(UTC))
    trial = session.scalar(select(Trial).where(Trial.id == trial_id).with_for_update())
    if trial is None or trial.code_version != NAME or trial.status != "running":
        raise ValueError("Running C08 experiment required")
    verify_binding(trial)
    state = deepcopy(trial.metrics[NAME])
    decision = json.loads(read_receipt(resolution_ref))
    if (not state.get("hold") or decision.get("trial_id") != trial_id
            or decision.get("hold_key") != state["hold"]["key"]
            or decision.get("decision") != "resume_flat_at_future_open"
            or not decision.get("reviewer") or len(decision.get("reason", "")) < 40
            or not timestamp(state["hold"]["at"]) <= timestamp(decision["reviewed_at"]) <= now):
        raise ValueError("Explicit current resolution of this C08 hold required")
    if (session.scalar(select(Position.id).where(Position.strategy_id == trial.strategy_id,
            Position.mode == "paper", Position.quantity != 0))
            or session.scalar(select(Order.id).where(Order.strategy_id == trial.strategy_id,
                Order.mode == "paper", Order.status.in_(ACTIVE)))):
        raise ValueError("Residual shares or active/unknown intents prevent a flat resolution")
    if session.get(Strategy, trial.strategy_id).status == "killed":
        raise ValueError("A permanent strategy kill cannot be cleared by a resolution")
    if any(timestamp(row["scheduled_at"]) <= now < timestamp(row["scheduled_at"]) + WINDOW
           for row in state["phases"].values()):
        raise ValueError("The current phase window must end before a future-open resolution")
    sessions = [MarketSession.from_api(row) for row in trial.params["calendar"]]
    admission(state["source_review"], sessions, as_of=now)
    state.setdefault("resolutions", []).append({"hold": state.pop("hold"), "receipt": resolution_ref})
    trial.metrics = {**trial.metrics, NAME: state}
    session.commit()


def admit_completion(session, trial_id, proof_ref, *, now=None):
    """Admit reviewed broker completion evidence, never a nominal calendar label.

    This operation only withholds/releases already recorded sale proceeds in
    the conservative evidence model. It cannot add cash to the transport book.
    """
    now = timestamp(now or datetime.now(UTC))
    proof = json.loads(read_receipt(proof_ref))
    read_receipt(proof["raw_receipt"])
    if (proof.get("kind") != "broker_settlement_completion" or not proof.get("reviewer")
            or proof.get("completion_documented") is not True or proof.get("calendar_label_only") is not False
            or len(proof.get("basis", "")) < 40
            or not timestamp(proof["completed_at"]) <= timestamp(proof["observed_at"]) <= timestamp(proof["reviewed_at"]) <= now):
        raise ValueError("Reviewed actual broker settlement completion required")
    trial = session.get(Trial, trial_id)
    fill = session.get(Fill, proof["fill_id"])
    if (trial is None or trial.code_version != NAME or trial.mode != "paper" or fill is None
            or fill.trial_id != trial_id or fill.mode != "paper" or fill.side != "sell"
            or digest(fill.venue_fill_id.encode()) != proof["venue_fill_id_sha256"]):
        raise ValueError("Completion proof does not identify this experiment's actual sale fill")
    connector = AlpacaPaperConnector(session, None, now=lambda: now)
    venue = connector._venue(lock=True)
    if proof["account_fingerprint"] != connector._book(venue)["account"]:
        raise ValueError("Completion proof belongs to another paper account")
    saved = {"kind": proof["kind"], "fill_id": fill.id, "completed_at": proof["completed_at"],
             "observed_at": proof["reviewed_at"], "actual_observed_at": proof["observed_at"], "source_receipt": proof_ref}
    try:
        save_evidence(venue, settlement=saved)
        evidence = account_evidence(session, venue, now,
            [MarketSession.from_api(row) for row in trial.params["calendar"]])
        session.commit()
        return {"fill_id": fill.id, "cash_available_usd": str(evidence.cash_available),
                "transport_cash_credited": False}
    except Exception:
        session.rollback()
        raise


def file_ref(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path.read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--through", type=date.fromisoformat, required=True)
    prep.add_argument("--review", type=Path, required=True)
    for name in ("activate", "bind-review", "resolve-flat", "admit-completion", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--trial-id", type=int, required=True)
        if name != "run":
            cmd.add_argument("--receipt", type=Path, required=True)
        else:
            cmd.add_argument("--once", action="store_true")
    args = parser.parse_args()
    api = AlpacaPaperAPI.from_env()
    try:
        with SessionLocal() as session:
            if args.command == "prepare":
                commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
                print(json.dumps(prepare(session, api, through=args.through, review_ref=file_ref(args.review), commit=commit)))
            elif args.command == "activate":
                activate(session, api, args.trial_id, decision_ref=file_ref(args.receipt))
                print(json.dumps({"trial_id": args.trial_id, "activated": True}))
            elif args.command == "bind-review":
                bind_review(session, args.trial_id, file_ref(args.receipt))
                print(json.dumps({"trial_id": args.trial_id, "review_bound": True}))
            elif args.command == "resolve-flat":
                resolve_flat_hold(session, args.trial_id, file_ref(args.receipt))
                print(json.dumps({"trial_id": args.trial_id, "hold_resolved_flat": True}))
            elif args.command == "admit-completion":
                print(json.dumps(admit_completion(session, args.trial_id, file_ref(args.receipt))))
            else:
                with get_engine().connect() as lock:
                    if not lock.scalar(text("SELECT pg_try_advisory_lock(60801, :trial)"), {"trial": args.trial_id}):
                        raise ValueError("C08 experiment already has an active runner")
                    runner = Runner(session, api, args.trial_id)
                    while True:
                        result = runner.step()
                        print(json.dumps({"trial_id": args.trial_id, "state": result}))
                        if args.once or result in {"complete", "prepared_held", "terminal_unverified"} or (
                                result == "held_for_resolution" and not runner.orders()):
                            break
                        time.sleep(2)
    finally:
        api.close()


if __name__ == "__main__":
    main()
