"""Explicit finite C05 paper orchestration over the unchanged commodity reactor.

Preparation remains disabled until source, account and promotion reviews pass.
Known intents are polled explicitly; construction never queries broker holdings
or reconciles the account. Claimed attempts are never automatically resubmitted.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
from functools import wraps
from pathlib import Path
import subprocess
import time

from sqlalchemy import select, text

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import (
    ACTIVE, AlpacaPaperConnector, OrderRejected, PaperAPIError, PaperEvidenceUnavailable, PaperGuardContext, PaperGuardResult,
)
from tradingbot.connectors.cash import MarketSession, NEW_YORK, timestamp
from tradingbot.db.models import Fill, FxRate, Instrument, Order, Position, Strategy, Trial
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.forward.c05_readiness import (
    PARAMS, REACTOR, ROOT, SYMBOLS, VERSION, digest, distribution_entitlement, historical_evidence,
)
from tradingbot.forward.c05_sources import admission, read_receipt
from tradingbot.forward.c05_state import (
    CLOSE_WINDOW, NAME, WINDOW, calendar_plan, dump_core, observe_close, phases, restore_core,
)
from tradingbot.forward.paper_evidence import (
    NAME as EVIDENCE, EvidenceGuard, account_evidence, required_instrument_ids, save_evidence,
    schedule_income_event,
)
from tradingbot.strategy import MarketEvent, MarketSnapshot, StrategyContext

ZERO = D(0)
LOCK_NAMESPACE = 60434


def atomic(method):
    @wraps(method)
    def wrapped(session, *args, **kwargs):
        try:
            return method(session, *args, **kwargs)
        except Exception:
            session.rollback()
            raise
    return wrapped


def dependencies():
    paths = ("forward/c05_runner.py", "forward/c05_state.py", "forward/c05_sources.py", "forward/c05_readiness.py",
             "forward/paper_evidence.py", "connectors/alpaca_paper.py", "connectors/alpaca_api.py", "connectors/cash.py",
             "research/c05_blackout.py", "research/equity_fees.py", "risk/engine.py", "risk/limits.py",
             "strategy/c05_commodity_trend.py")
    return {p: digest((ROOT / "src/tradingbot" / p).read_bytes()) for p in paths}


def verify_binding(trial):
    if trial.params["dependencies"] != dependencies():
        raise ValueError("C05 implementation changed; explicitly review experiment continuation")
    if trial.params["reactor_sha256"] != REACTOR or trial.strategy_version != VERSION:
        raise ValueError("Frozen C05 research identity changed")
    if any(trial.params.get(k) != v for k, v in PARAMS.items()):
        raise ValueError("Frozen C05 rule changed")
    phases(trial.params)


def prepare(session, api, *, through, review_ref, commit, now=None):
    """Ledger every attempted preparation; no account funding or activation."""
    now = timestamp(now or datetime.now(UTC))
    history = historical_evidence(session)
    sid = history["rows"][0]["strategy_id"]
    session.execute(text("SELECT pg_advisory_xact_lock(60435, :strategy)"), {"strategy": sid})
    if session.scalar(select(Trial.id).where(Trial.strategy_id == sid, Trial.mode == "paper", Trial.status == "running")):
        raise ValueError("Explicitly resume the existing C05 experiment")
    trial = Trial(strategy_id=sid, mode="paper", code_version=NAME, strategy_version=VERSION, git_commit=commit,
                  data_start=now, params={**PARAMS, "source_review": review_ref, "historical_evidence": history,
                    "dependencies": dependencies(), "reactor_sha256": REACTOR},
                  metrics={NAME: {"enabled": False, "phases": {}, "incidents": [], "core": None}},
                  notes="C05 disabled preparation; source/account/promotion review required. No final replay.")
    session.add(trial)
    session.commit()
    trial_id, stage = trial.id, "account_calendar"
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    try:
        venue = connector._venue()
        book = connector._book(venue)
        account = connector._call(api.account)
        connector._account_ok(account)
        if D(book["initial_cash"]) != 140 or connector._fingerprint(account) != book["account"]:
            raise ValueError("Existing shared $140 account required; never fund a separate C05 book")
        start = now.astimezone(NEW_YORK).date() - timedelta(days=400)
        rows = connector._call(api.calendar_range, start, through + timedelta(days=45))
        plan = calendar_plan(rows, start=now, through=through)
        sessions = [MarketSession.from_api(r) for r in rows]
        stage = "source_admission"
        admitted = admission(review_ref, sessions, as_of=now)
        stage = "instrument_exposure"
        strategy = session.get(Strategy, sid, populate_existing=True)
        if strategy.status == "killed" or session.scalar(select(Position.id).where(
                Position.strategy_id == sid, Position.mode == "paper", Position.quantity != 0)):
            raise ValueError("Existing C05 exposure or permanent kill requires continuation review")
        if session.scalar(select(Order.id).where(Order.strategy_id == sid, Order.mode == "paper", Order.status.in_(ACTIVE))):
            raise ValueError("Existing C05 pending intent requires continuation")
        ids = {symbol: connector.register_equity(symbol) for symbol in SYMBOLS}
        trial = session.get(Trial, trial_id)
        trial.params = {**trial.params, **plan, "instrument_ids": ids, "blackouts": admitted["blackouts"]}
        trial.metrics = {NAME: {"enabled": False, "phases": {}, "incidents": [],
            "source_review": review_ref, "core": dump_core(restore_core(trial.params)),
            "blackouts": admitted["blackouts"], "decision": "prepared_held_for_activation"}}
        session.commit()
        return {"trial_id": trial_id, "status": "prepared_held_for_activation", "orders": 0}
    except Exception as exc:
        session.rollback()
        trial = session.get(Trial, trial_id)
        trial.status, trial.completed_ts, trial.trade_count = "failed", now, 0
        trial.metrics = {NAME: {"enabled": False, "phases": {}, "core": None, "incidents": [],
            "decision": "hold_before_paper", "failure_stage": stage, "failure_type": type(exc).__name__}}
        trial.notes = f"C05 preparation held at {stage}: {type(exc).__name__}; no order, result, activation or historical replay."
        session.commit()
        return {"trial_id": trial_id, "status": "failed", "failure_stage": stage,
                "failure_type": type(exc).__name__, "orders": 0}


@atomic
def activate(session, api, trial_id, *, decision_ref, now=None):
    now = timestamp(now or datetime.now(UTC))
    trial = session.get(Trial, trial_id)
    if trial is None or trial.mode != "paper" or trial.code_version != NAME or trial.status != "running":
        raise ValueError("Prepared running C05 trial required")
    verify_binding(trial)
    decision = json.loads(read_receipt(decision_ref))
    if (decision.get("decision") != "activate_paper" or decision.get("trial_id") != trial_id
            or decision.get("promotion_checklist_complete") is not True
            or decision.get("account_integration_verified") is not True
            or len(decision.get("what_could_blow_up_this_account", "")) < 100
            or not now - timedelta(days=1) <= timestamp(decision["reviewed_at"]) <= now):
        raise ValueError("Current explicit paper promotion and account-risk review required")
    state = deepcopy(trial.metrics[NAME])
    if state["enabled"] or state["phases"]:
        raise ValueError("Used experiments require continuation, not reactivation")
    sessions = [MarketSession.from_api(r) for r in trial.params["calendar"]]
    admitted = admission(state["source_review"], sessions, as_of=now)
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    account = connector._call(api.account)
    connector._account_ok(account)
    session.commit()
    venue = connector._venue(lock=True)
    book = connector._book(venue)
    if (book.get("guard_required") != EVIDENCE or D(book["initial_cash"]) != 140
            or connector._fingerprint(account) != book["account"]):
        raise ValueError("Explicit shared-account evidence migration must precede C05 activation")
    trial = session.get(Trial, trial_id, populate_existing=True)
    strategy = session.get(Strategy, trial.strategy_id, populate_existing=True)
    state = deepcopy(trial.metrics[NAME])
    if state["enabled"] or state["phases"] or trial.status != "running" or strategy.status == "killed":
        raise ValueError("Activation state changed or strategy permanently killed")
    if any(s.opens_at <= now for s in sessions if str(s.trade_date) == trial.params["terminal_date"]):
        raise ValueError("C05 experiment terminal opening has already passed")
    strategy.status, strategy.allocation_usd = "paper", D(140)
    for event in admitted["actions"]:
        if event["kind"] == "ordinary_cash":
            schedule_income_event(session, venue, event, sessions,
                                  instrument_id=trial.params["instrument_ids"][event["symbol"]], now=now)
    evidence = account_evidence(session, venue, now, sessions)
    baseline = connector.risk.strategy_pnl(strategy.id, "paper") + evidence.strategy_pnl_offset(strategy.id)
    trial.metrics = {**trial.metrics, NAME: {**state, "enabled": True, "activation_at": now.isoformat(),
        "activation_decision": decision_ref, "baseline_strategy_pnl": str(baseline),
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
    def resting_tags(self, instrument_id=None):
        return tuple(o.metadata_["client_order_id"] for o in self.runner.orders()
                     if instrument_id is None or o.instrument_id == instrument_id)
    def available_cash(self, instrument_id):
        r = self.runner
        if instrument_id not in r.ids.values() or r.evidence is None:
            return None
        return min(r.evidence.cash_available, r.evidence.strategy_cash(r.strategy_id), r.transport_cash)
    def marked_equity(self):
        r = self.runner
        if r.evidence is None:
            return None
        pnl = r.connector.risk.strategy_pnl(r.strategy_id, "paper", r.marks)
        return D(r.trial().params["slot_usd"]) + pnl + r.evidence.strategy_pnl_offset(r.strategy_id)


class Runner:
    required_guard = EVIDENCE

    def verify_binding(self, trial):
        verify_binding(trial)

    def restore_core(self, params, saved=None):
        return restore_core(params, saved)

    def admit(self, state, phase_kind, calendar):
        return admission(state["source_review"], self.sessions, as_of=self.now(),
            close_day=calendar.trade_date if phase_kind == "close" else None)

    def __init__(self, session, api, trial_id, *, now=None):
        self.session, self.api, self.trial_id = session, api, trial_id
        self.now = now or (lambda: datetime.now(UTC))
        trial = self.trial()
        self.verify_binding(trial)
        self.strategy_id, self.ids = trial.strategy_id, trial.params["instrument_ids"]
        self.sessions = [MarketSession.from_api(r) for r in trial.params["calendar"]]
        self.schedule = phases(trial.params)
        self.core = self.restore_core({**trial.params, "blackouts": self.state()["blackouts"]}, self.state()["core"])
        self.guard = EvidenceGuard(self.sessions, additional=self.ids.values())
        self.connector = AlpacaPaperConnector(session, api, now=self.now, execution_guard=self._guard)
        self.ctx = Context(self)
        self.snapshots, self.marks = {}, {}
        self.evidence, self.admitted, self.current_phase, self.current_attempt = None, None, None, None
        self.transport_cash = ZERO

    def trial(self, *, lock=False):
        stmt = select(Trial).where(Trial.id == self.trial_id).execution_options(populate_existing=True)
        trial = self.session.scalar(stmt.with_for_update() if lock else stmt)
        if trial is None or trial.mode != "paper" or trial.code_version != NAME or trial.status != "running":
            raise ValueError("Explicit prepared running C05 trial required")
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
                strategy_id=self.strategy_id, message=message, details={"trial_id": self.trial_id, "key": key})
            state["incidents"].append(key)
        state["hold"] = {"key": key, "message": message, "at": self.now().isoformat()}
        self.save(state)

    def _guard(self, connector, context):
        if connector._book(context.venue).get("guard_required") != self.required_guard:
            raise OrderRejected("C05 requires shared account evidence enforcement")
        result = self.guard(connector, context)
        if context.phase == "refresh":
            return result
        state = self.state()
        phase = state["phases"].get(self.current_phase, {})
        attempts = phase.get("attempts", {})
        attempt = attempts.get(self.current_attempt)
        if (not state["enabled"] or state.get("hold") or attempt is None or attempt["status"] != "claimed"
                or state["source_review"] != phase["source_review"]
                or self.admitted is None or phase["source_review"] != self.admitted["review_ref"]):
            raise OrderRejected("C05 intent is not a current enabled durable attempt")
        if self.session.get(Strategy, self.strategy_id).allocation_usd != D(self.trial().params["slot_usd"]):
            raise OrderRejected("C05 allocation differs from the frozen slot")
        opened = timestamp(phase["scheduled_at"])
        if not opened <= context.now < opened + WINDOW or context.quote.time < opened:
            raise OrderRejected("C05 opening window elapsed or quote precedes it")
        if (context.instrument_id, context.side, context.quantity, context.limit_price) != (
                attempt["instrument_id"], attempt["side"], D(attempt["quantity"]), D(attempt["limit"])):
            raise OrderRejected("C05 submission differs from its durable intent")
        return replace(result, valid_until=min(result.valid_until or opened + WINDOW, opened + WINDOW),
            details={**result.details, "c05_phase": self.current_phase, "c05_attempt": self.current_attempt,
                     "c05_source_review": phase["source_review"], "decision_quote": attempt["quote"]})

    def _balances(self):
        venue = self.connector._venue(lock=True)
        self.evidence = account_evidence(self.session, venue, self.now(), self.sessions)
        self.transport_cash = self.connector._balance(venue, self.now()).available
        self.session.commit()

    def _capture(self, deadline=None):
        if self.connector._book(self.connector._venue()).get("guard_required") != self.required_guard:
            raise OrderRejected("C05 shared account migration is not active")
        quotes = self.guard.capture(self.connector, valid_until=deadline)
        self.snapshots = {iid: MarketSnapshot(iid, timestamp(q["t"]), bid=D(str(q["bp"])), ask=D(str(q["ap"])))
                          for iid, q in quotes.items()}
        self.marks = {iid: q.reference_price for iid, q in self.snapshots.items()}
        venue = self.connector._venue(lock=True)
        self.evidence = account_evidence(self.session, venue, self.now(), self.sessions)
        self.transport_cash = self.connector._balance(venue, self.now()).available
        self.connector._refresh_risk(self.guard(self.connector, PaperGuardContext(
            phase="refresh", now=self.now(), venue=venue)), self.now())
        self.session.commit()

    def _income(self, admitted):
        for action in admitted["actions"]:
            if action["kind"] != "ordinary_cash":
                continue
            ex = next(s.opens_at for s in self.sessions if str(s.trade_date) == action["ex_date"])
            if self.now() < ex:
                continue
            iid = self.ids[action["symbol"]]
            venue = self.connector._venue(lock=True)
            if self.session.scalar(select(Order.id).where(Order.instrument_id == iid, Order.mode == "paper",
                    Order.status.in_(ACTIVE), Order.created_ts < ex)):
                raise ValueError("Pre-ex pending intent prevents known entitlement ownership")
            fills = list(self.session.scalars(select(Fill).where(Fill.instrument_id == iid,
                Fill.mode == "paper").order_by(Fill.fill_ts, Fill.id)))
            event = {**action, "source_sha256": action["source_receipt"]["sha256"],
                     "source_observed_at": action["observed_at"]}
            for sid in {f.strategy_id for f in fills}:
                if sid is None:
                    raise ValueError("Unattributed entitlement needs explicit review")
                rows = [{"id": f.id, "symbol": action["symbol"], "side": f.side, "quantity": str(f.size),
                         "fill_at": f.fill_ts.isoformat()} for f in fills if f.strategy_id == sid]
                row = distribution_entitlement(event, rows, self.sessions, self.now())
                row.update(strategy_id=sid, source_receipt=action["source_receipt"])
                existing = [v for v in (venue.metadata_ or {}).get(EVIDENCE, {}).get("incomes", [])
                            if (v["strategy_id"], v["event_id"]) == (sid, row["event_id"])]
                if existing:
                    keys = ("amount_per_share", "quantity_before_ex_open", "cash_amount", "recognized_at", "modeled_release_at")
                    if len(existing) != 1 or any(D(existing[0][k]) != D(row[k]) if k in keys[:3]
                                                 else timestamp(existing[0][k]) != timestamp(row[k]) for k in keys):
                        raise ValueError("Previously recognized entitlement facts changed")
                else:
                    save_evidence(venue, income=row)
            self.session.commit()

    def _reconcile(self):
        """Only attempts durably claimed by this trial, never the broker account."""
        for phase_key, phase in self.state()["phases"].items():
            for tag, attempt in phase.get("attempts", {}).items():
                order = self.session.scalar(select(Order).where(Order.trial_id == self.trial_id,
                    Order.metadata_["client_order_id"].as_string() == "tbp-" + attempt["request_id"]))
                if order is None:
                    if attempt["status"] == "claimed":
                        self.hold("interrupted-" + tag, "C05 claimed attempt has no connector receipt; never resubmit it automatically.")
                    continue
                if order.status in ACTIVE:
                    try:
                        self.connector.refresh(order.id)
                    except PaperEvidenceUnavailable:
                        pass  # The connector committed actual fills before the missing-evidence hold.
                    except (ValueError, PaperAPIError):
                        self.session.rollback()
                        self.hold("poll-" + tag, "C05 known-order polling failed; unresolved intent remains reserved.")
                order = self.session.get(Order, order.id, populate_existing=True)
                attempt.update(status=order.status, order_id=order.id, filled_quantity=str(order.filled_size),
                    submission_unknown=bool(order.metadata_.get("submission_unknown")))
                receipts, opened = [], timestamp(phase["scheduled_at"])
                for fill in self.session.scalars(select(Fill).where(Fill.order_id == order.id).order_by(Fill.fill_ts, Fill.id)):
                    quote = attempt["quote"]
                    mid = (D(quote["bid"]) + D(quote["ask"])) / 2
                    cost = (fill.price / mid - 1) * (1 if fill.side == "buy" else -1) * 10000
                    receipts.append({"fill_id": fill.id, "at": fill.fill_ts.isoformat(), "price": str(fill.price),
                        "quantity": str(fill.size), "actual_broker_fee": str(fill.fee),
                        "decision_mid_cost_bp": str(cost), "historical_reference_bp": 10,
                        "inside_opening_window": opened <= fill.fill_ts < opened + WINDOW,
                        "settlement_date_label": fill.metadata_["settlement_date"], "actual_paper_fill": True})
                attempt["fill_receipts"] = receipts
                state = self.state()
                state["phases"][phase_key]["attempts"][tag] = attempt
                self.save(state)
                if attempt["submission_unknown"] or order.status in {"rejected", "canceled", "expired"}:
                    self.hold("unresolved-" + tag, "C05 intent unknown/rejected/incomplete; preserve targets and review exposure.")
                elif self.now() >= opened + WINDOW and order.filled_size < order.size:
                    self.hold("partial-" + tag, "C05 opening execution incomplete after the frozen window; remaining inventory requires review.")
                if any(not r["inside_opening_window"] for r in receipts):
                    self.hold("late-fill-" + tag, "C05 actual fill occurred outside the frozen opening window; execution fidelity is unresolved.")

    def _claim(self, phase_key, phase, intents, status):
        trial = self.trial(lock=True)
        state = deepcopy(trial.metrics[NAME])
        old = state["phases"].get(phase_key)
        if old is not None and old["status"] != "reductions_complete":
            self.session.commit()
            raise ValueError("C05 phase already claimed")
        if intents:
            fx = self.session.scalar(select(FxRate.ts).where(FxRate.base == "USD", FxRate.quote == "GBP",
                FxRate.ts <= self.now()).order_by(FxRate.ts.desc()).limit(1))
            if fx is None or self.now() - fx > timedelta(days=7):
                raise ValueError("Recent dated USD/GBP reference required")
        attempts = deepcopy(phase.get("attempts", {}))
        for intent in intents:
            if intent.tag in attempts:
                raise ValueError("Repeated C05 durable attempt tag")
            quote = self.snapshots[intent.instrument_id]
            request = f"c05-{self.trial_id}-" + digest(intent.tag.encode())[:24]
            attempts[intent.tag] = {"status": "claimed", "request_id": request, "at": self.now().isoformat(),
                "instrument_id": intent.instrument_id, "side": intent.side, "quantity": str(intent.size),
                "limit": str(intent.limit_price), "reason": intent.reason,
                "mandatory_exit": "forced blackout exit" in intent.reason or "terminal liquidation" in intent.reason,
                "quote": {"at": quote.time.isoformat(), "bid": str(quote.bid), "ask": str(quote.ask)},
                "fill_receipts": []}
        state["phases"][phase_key] = {**phase, "status": status, "attempts": attempts}
        state["core"] = dump_core(self.core)
        trial.metrics = {**trial.metrics, NAME: state}
        self.session.commit()  # every intent is durable BEFORE any HTTP submission

    def _submit(self, phase_key, intents):
        self.current_phase = phase_key
        for intent in intents:
            self.current_attempt = intent.tag
            state = self.state()
            attempt = state["phases"][phase_key]["attempts"][intent.tag]
            if state.get("hold"):
                attempt["status"] = "not_submitted_due_hold"
                state["phases"][phase_key]["attempts"][intent.tag] = attempt
                self.save(state)
                continue
            try:
                deadline = timestamp(state["phases"][phase_key]["scheduled_at"]) + WINDOW
                self._capture(deadline)
                result = self.connector.submit_limit(request_id=attempt["request_id"], instrument_id=intent.instrument_id,
                    strategy_id=self.strategy_id, trial_id=self.trial_id, side=intent.side,
                    quantity=intent.size, limit_price=intent.limit_price)
                attempt.update(status=result.status, order_id=result.order_id, submission_unknown=result.submission_unknown)
            except (ValueError, PaperAPIError) as exc:
                self.session.rollback()
                attempt.update(status=type(exc).__name__, failure_at=self.now().isoformat())
                self.hold("veto-" + intent.tag, "C05 requested execution was vetoed/unavailable; no automatic retry or resizing.")
            latest = self.state()
            latest["phases"][phase_key]["attempts"][intent.tag] = attempt
            self.save(latest)
            if attempt.get("submission_unknown"):
                self.hold("unknown-" + intent.tag, "C05 POST outcome is unknown; shared cash reservation retained and no retry.")

    def _close(self, phase_key, at, calendar):
        if self.orders():
            raise ValueError("Pending executions prevent a coherent completed-close decision")
        vintage = self.admitted["vintage"]
        independent = json.loads(read_receipt(self.admitted["watch"]["independent_receipt"]))["bars"]
        self.marks = {}
        for iid in required_instrument_ids(self.session, self.ids.values()):
            instrument = self.session.get(Instrument, iid)
            bars = [r for r in independent.get(instrument.symbol, [])
                    if timestamp(r["t"]).astimezone(NEW_YORK).date() == calendar.trade_date]
            if len(bars) != 1:
                raise ValueError("Completed-close portfolio reference coverage is incomplete")
            self.marks[iid] = D(str(bars[0]["c"]))
        # C05 uses its admitted raw primary close; the complete independent
        # comparison was checked before admission. Other holdings use their
        # separately captured completed-session close, not a stale live quote.
        self.marks.update({self.ids[s]: D(vintage[s]["raw_closes"][-1]) for s in SYMBOLS})
        self._balances()
        self.connector._refresh_risk(PaperGuardResult(marks=self.marks,
            strategy_pnl_offsets=self.evidence.strategy_offsets, daily_pnl_offset=self.evidence.daily_pnl_offset), self.now())
        self.session.commit()
        observe_close(self.core, self.ctx, vintage, calendar)
        if self.now() >= at + CLOSE_WINDOW:
            raise ValueError("C05 close observation window elapsed")
        trial = self.trial(lock=True)
        state = deepcopy(trial.metrics[NAME])
        if phase_key in state["phases"]:
            self.session.commit()
            return "already_observed"
        state["phases"][phase_key] = {"status": "complete", "phase": "close", "scheduled_at": at.isoformat(),
            "observed_at": self.now().isoformat(), "source_review": state["source_review"],
            "marked_equity_usd": str(self.ctx.marked_equity()), "completed_close_marks": {str(k): str(v) for k, v in self.marks.items()},
            "decision_count": len(self.core.decisions), "attempts": {}}
        state["core"] = dump_core(self.core)
        trial.metrics = {**trial.metrics, NAME: state}
        self.session.commit()
        return "close_observed"

    def _open(self, phase_key, at, calendar):
        state, day = self.state(), str(calendar.trade_date)
        phase = state["phases"].get(phase_key)
        terminal = day == self.trial().params["terminal_date"]
        try:
            self._capture(at + WINDOW)
        except (ValueError, PaperAPIError):
            # A thin ETF can print its first regular-session IEX quote seconds
            # after the bell (USO 09:30:16 on 2026-10-07, when one failed capture
            # held trial 7852 for good). Before anything is claimed, retry inside
            # the opening window; after it, the missed-window rules apply as before.
            if phase is not None or self.now() >= at + WINDOW:
                raise
            self.session.rollback()
            return "awaiting_opening_marks"
        if phase is None:
            if self.orders():
                raise ValueError("Existing C05 orders prevent a new opening phase")
            intents = []
            for symbol in SYMBOLS:
                iid = self.ids[symbol]
                intents.extend(self.core.on_event(self.ctx, MarketEvent.quote(iid, at,
                    meta={"phase": "reduce", "terminal_open": terminal})))
            requested = {i.instrument_id for i in intents}
            for symbol in SYMBOLS:
                iid = self.ids[symbol]
                if (terminal or not self.core.holdable(symbol, day)) and self.ctx.position(iid) and iid not in requested:
                    raise ValueError("Mandatory forced/terminal exit is unresolved dust")
            phase = {"phase": "open", "scheduled_at": at.isoformat(), "observed_at": self.now().isoformat(),
                     "source_review": state["source_review"], "attempts": {}}
            self._claim(phase_key, phase, intents, "awaiting_reductions" if intents else "reductions_complete")
            self._submit(phase_key, intents)
            if intents:
                return "awaiting_reductions"
            phase = self.state()["phases"][phase_key]
        if phase["status"] == "awaiting_reductions":
            sells = [a for a in phase["attempts"].values() if a["side"] == "sell"]
            if not all(a["status"] == "filled" and D(a["filled_quantity"]) == D(a["quantity"]) for a in sells):
                return "awaiting_reductions"
            for symbol in SYMBOLS:
                if (terminal or not self.core.holdable(symbol, day)) and self.ctx.position(self.ids[symbol]):
                    raise ValueError("Forced/terminal exit left residual shares")
            phase["status"] = "reductions_complete"
            state = self.state()
            state["phases"][phase_key] = phase
            self.save(state)
        if phase["status"] == "reductions_complete":
            intents = []
            for symbol in SYMBOLS:
                intents.extend(self.core.on_event(self.ctx, MarketEvent.quote(self.ids[symbol], at,
                    meta={"phase": "buy", "terminal_open": terminal})))
            self._claim(phase_key, phase, intents, "awaiting_buys" if intents else "complete")
            self._submit(phase_key, intents)
            return "awaiting_buys" if intents else "no_intent"
        return phase["status"]

    def _record_mark(self):
        if self.evidence is None:
            return
        state = self.state()
        net = self.ctx.marked_equity() - D(self.trial().params["slot_usd"]) - D(state.get("baseline_strategy_pnl", "0"))
        peak = max(D(state.get("peak_net", "0")), net)
        state.update(last_mark_at=self.now().isoformat(), net_with_fee_income_scenario=str(net), peak_net=str(peak),
                     max_drawdown=str(max(D(state.get("max_drawdown", "0")), peak - net)),
                     account_evidence=self.evidence.details)
        self.save(state)

    def _finish_if_flat(self):
        trial = self.trial()
        terminal = trial.params["terminal_date"] + ":open"
        state = self.state()
        phase = state["phases"].get(terminal)
        if (phase is None or phase["status"] != "complete" or state.get("hold") or self.orders()
                or any(self.ctx.position(i) for i in self.ids.values())):
            return False
        fills = list(self.session.scalars(select(Fill).where(Fill.trial_id == self.trial_id).order_by(Fill.fill_ts, Fill.id)))
        self._balances()
        net = self.ctx.marked_equity() - D(self.trial().params["slot_usd"]) - D(state.get("baseline_strategy_pnl", "0"))
        fill_ids = {f.id for f in fills}
        fees = sum((max(D(r["modeled_fee_usd"]), D(r["actual_fee_usd"]))
                    for r in self.evidence.details["fees"] if r["fill_id"] in fill_ids), ZERO)
        trial = self.trial(lock=True)
        trial.status, trial.completed_ts, trial.data_end = "complete", self.now(), self.now()
        trial.pnl_after_fees, trial.fees_total = net, fees
        trial.trade_count = len(fills)
        trial.max_drawdown = D(state.get("max_drawdown", "0"))
        trial.metrics = {**trial.metrics, NAME: {**state, "enabled": False, "decision": "complete_requires_fidelity_review",
            "ready_for_live": False, "actual_fill_count": len(fills), "trade_count_definition": "individual forward executions",
            "action_fidelity_established": False, "cash_completion_fidelity_established": False}}
        trial.notes = "C05 finite paper experiment completed flat; actual fill count differs from historical round-trip count. Separate fee/cash/action fidelity and promotion review required."
        self.session.commit()
        return True

    def step(self):
        self.verify_binding(self.trial())
        now = self.now()
        regular = next((s for s in self.sessions if s.is_open(now)), None)
        if regular and (self.orders() or any(self.ctx.position(i) for i in self.ids.values())):
            try:
                self._capture()
            except (ValueError, PaperAPIError):
                self.session.rollback()
                self.evidence = None
        self._reconcile()
        if self.evidence is not None:
            self._balances()
            self._record_mark()
        state = self.state()
        if not state["enabled"]:
            return "prepared_held"
        if state.get("hold"):
            return "held_for_resolution"
        for phase_key, phase_kind, at, calendar in self.schedule:
            phase = state["phases"].get(phase_key)
            if now < at or (phase and phase["status"] == "complete"):
                continue
            window = WINDOW if phase_kind == "open" else CLOSE_WINDOW
            if now >= at + window:
                if phase is None:
                    state["phases"][phase_key] = {"status": "missed_window", "phase": phase_kind,
                        "scheduled_at": at.isoformat(), "attempts": {}}
                    self.save(state)
                elif phase["status"] in {"awaiting_reductions", "awaiting_buys"}:
                    if all(a["status"] == "filled" for a in phase["attempts"].values()):
                        state["phases"][phase_key]["status"] = "complete"
                        self.save(state)
                mandatory = str(calendar.trade_date) == self.trial().params["terminal_date"] or any(
                    p["decision" if phase_kind == "close" else "exit"] == str(calendar.trade_date) for p in state["blackouts"])
                if mandatory and any(self.ctx.position(self.ids[p["symbol"]]) for p in state["blackouts"]
                                     if p["decision" if phase_kind == "close" else "exit"] == str(calendar.trade_date)):
                    self.hold("missed-" + phase_key, "C05 mandatory action phase missed with shares held; no off-window catch-up.")
                    return "held_for_resolution"
                if str(calendar.trade_date) == self.trial().params["terminal_date"] and any(self.ctx.position(i) for i in self.ids.values()):
                    self.hold("terminal-" + phase_key, "C05 terminal exit missed/incomplete; residual inventory requires review.")
                    return "held_for_resolution"
                state = self.state()
                continue
            try:
                self.admitted = self.admit(state, phase_kind, calendar)
                state = self.state()
                self.admitted["review_ref"] = state["source_review"]
                if phase_kind == "open" and timestamp(self.admitted["reviewed_at"]) >= at:
                    raise ValueError("Opening source review must be available before the scheduled open")
                self._income(self.admitted)
                self.core = self.restore_core({**self.trial().params, "blackouts": self.admitted["blackouts"]}, state["core"])
                if phase_kind == "close":
                    result = self._close(phase_key, at, calendar)
                else:
                    result = self._open(phase_key, at, calendar)
                self._record_mark()
                if self._finish_if_flat():
                    return "complete_requires_fidelity_review"
                return result
            except (ValueError, PaperAPIError) as exc:
                self.session.rollback()
                self.hold("evidence-" + phase_key, "C05 source, action, cash or execution evidence failed: " + type(exc).__name__)
                return "held_for_resolution"
        if self._finish_if_flat():
            return "complete_requires_fidelity_review"
        return "observing" if regular else "outside_session"


@atomic
def use_review(session, trial_id, review_ref, *, now):
    trial = session.get(Trial, trial_id)
    if trial is None or trial.status != "running" or trial.mode != "paper" or trial.code_version != NAME:
        raise ValueError("Prepared running C05 trial required")
    verify_binding(trial)
    sessions = [MarketSession.from_api(r) for r in trial.params["calendar"]]
    admitted = admission(review_ref, sessions, as_of=now)
    connector = AlpacaPaperConnector(session, None, now=lambda: timestamp(now))
    venue = connector._venue(lock=True)
    for event in admitted["actions"]:
        if event["kind"] == "ordinary_cash":
            schedule_income_event(session, venue, event, sessions,
                                  instrument_id=trial.params["instrument_ids"][event["symbol"]], now=now)
    trial = session.scalar(select(Trial).where(Trial.id == trial_id).with_for_update().execution_options(populate_existing=True))
    state = deepcopy(trial.metrics[NAME])
    old = {p["identity"]: p for p in state["blackouts"]}
    new = {p["identity"]: p for p in admitted["blackouts"]}
    if any(identity not in new or new[identity] != plan for identity, plan in old.items()):
        raise ValueError("Known action plans cannot disappear or change without explicit resolution")
    state.update(source_review=review_ref, blackouts=admitted["blackouts"])
    state["source_review_history"] = [*state.get("source_review_history", []), review_ref]
    trial.metrics = {**trial.metrics, NAME: state}
    session.commit()


@atomic
def record_completion(session, trial_id, proof_ref, *, now):
    """Explicit settlement-review import; nominal FILL settlement labels fail."""
    trial = session.get(Trial, trial_id)
    verify_binding(trial)
    proof = json.loads(read_receipt(proof_ref))
    if (proof.get("kind") != "broker_settlement_completion" or not proof.get("reviewer")
            or len(proof.get("reason", "")) < 30 or timestamp(proof["observed_at"]) > timestamp(now)):
        raise ValueError("Documented broker completion review required")
    read_receipt(proof["source_receipt"])
    fill = session.get(Fill, proof["fill_id"])
    connector = AlpacaPaperConnector(session, None, now=lambda: timestamp(now))
    venue = connector._venue(lock=True)
    instrument = session.get(Instrument, fill.instrument_id) if fill else None
    if fill is None or fill.mode != "paper" or fill.side != "sell" or instrument.venue_id != venue.id:
        raise ValueError("Completion must identify a known account sale fill")
    save_evidence(venue, settlement=proof)
    account_evidence(session, venue, timestamp(now), [MarketSession.from_api(r) for r in trial.params["calendar"]])
    session.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--through", type=date.fromisoformat, required=True)
    prep.add_argument("--review-ref", type=Path, required=True)
    for command in ("activate", "use-review", "record-completion", "run"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("--trial-id", type=int, required=True)
        if command != "run": command_parser.add_argument("--receipt-ref", type=Path, required=True)
        else: command_parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    api = AlpacaPaperAPI.from_env()
    try:
        with SessionLocal() as session:
            if args.command == "prepare":
                result = prepare(session, api, through=args.through, review_ref=json.loads(args.review_ref.read_text()),
                    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
                print(json.dumps(result))
                return
            with get_engine().connect() as lock:
                if not lock.scalar(text("SELECT pg_try_advisory_lock(60434, :trial)"), {"trial": args.trial_id}):
                    raise ValueError("C05 runtime already owns this trial")
                try:
                    if args.command == "activate":
                        activate(session, api, args.trial_id, decision_ref=json.loads(args.receipt_ref.read_text()))
                    elif args.command == "use-review":
                        use_review(session, args.trial_id, json.loads(args.receipt_ref.read_text()), now=datetime.now(UTC))
                    elif args.command == "record-completion":
                        record_completion(session, args.trial_id, json.loads(args.receipt_ref.read_text()), now=datetime.now(UTC))
                    else:
                        runner = Runner(session, api, args.trial_id)
                        while True:
                            try:
                                status = runner.step()
                                print(json.dumps({"trial_id": args.trial_id, "status": status}), flush=True)
                                if status == "complete_requires_fidelity_review":
                                    break
                            except Exception as exc:
                                session.rollback()
                                print(json.dumps({"trial_id": args.trial_id, "incident": type(exc).__name__}), flush=True)
                                if args.once: raise SystemExit(1) from None
                            if args.once: break
                            time.sleep(10)
                finally:
                    lock.execute(text("SELECT pg_advisory_unlock(60434, :trial)"), {"trial": args.trial_id})
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "ready_for_live": False}))
        raise SystemExit(1) from None
    finally:
        api.close()


if __name__ == "__main__":
    main()
