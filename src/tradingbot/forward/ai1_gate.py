"""Daily AI-1 cohort on the J-suite's existing paper execution machinery."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
import random
import subprocess
import time
from uuid import uuid4

from sqlalchemy import select, text

from tradingbot.ai.claude import ClaudeClient, MODEL_ID as CLAUDE_MODEL
from tradingbot.ai.jev import JevClient, MODEL_ID, _validate_answers, _validate_questions, estimated_tokens
from tradingbot.ai.state import build_state
from tradingbot.backtest.holdout import strategy_identity
from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.cash import NEW_YORK, timestamp
from tradingbot.data.iex_intraday import SYMBOLS, load_snapshot
from tradingbot.db.models import Fill, JevRequest, JevTurn, Strategy, Trial
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.forward.ai import evidence_gate, trial_lock
from tradingbot.forward.ai_paper_costs import account_costs
from tradingbot.forward.jev_intraday import (
    NAME, ROOT, TRUST, Runner, initial_state, plain, turn_deadline, update_readiness,
    identity as intraday_identity,
)
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import luck_probability
from tradingbot.paper.equities import EquityPaperBook
from tradingbot.strategy.ai1_gate import COUNT, FRACTION, DailyGate
from tradingbot.strategy.jev import View

VERSION = "ai1_daily_gate_v1"
ALLOCATION = D(15)
KINDS = ("ungated", "jev", "claude")
REVIEW = "docs/research/48-ai1-gate-plan.md"
LOCK_ID = 0x4149314441494C


def due_boundary(now, market):
    if market is None:
        return None
    boundary = market.opens_at+timedelta(hours=1)
    return boundary if boundary <= now < boundary+timedelta(minutes=2) and market.is_open(now) else None


def identity():
    return strategy_identity(DailyGate(), DailyRunner,
        {"version": VERSION, "allocation": str(ALLOCATION), "kinds": KINDS,
         "claude_model": CLAUDE_MODEL, "jev_model": MODEL_ID, "entry_minute": 60,
         "shared_execution_version": intraday_identity(DailyGate(), ALLOCATION)[0]},
        execution_types=(Runner, ClaudeClient, JevClient, build_state, EquityPaperBook,
                         intraday_identity, account_costs))


def prepare(session, *, git_commit, now=None):
    """Admit three equal real arms plus an informational random twin; no funding."""
    now = timestamp(now or datetime.now(UTC))
    with trial_lock(session, 0):
        if session.scalar(select(Trial.id).where(Trial.code_version == VERSION, Trial.status == "running")):
            raise ValueError("AI-1 already admitted")
        runner = DailyRunner(session, None)
        venue = runner.connector._venue()
        book = runner.connector._book(venue)
        if D(book["initial_cash"]) < ALLOCATION*len(KINDS):
            raise ValueError("Existing book cannot support the cohort; never fund/reset it here")
        review = (ROOT/REVIEW).read_text()
        if "what could blow up this account" not in review.lower():
            raise ValueError("Missing promotion review")
        version, frozen = identity()
        cohort = {}
        for kind in (*KINDS, "random"):
            key = f"ai1-daily-{kind}-v1"
            row = session.scalar(select(Strategy).where(Strategy.key == key))
            if row is not None:
                raise ValueError("A prior variant exists; review before a new version")
            virtual = kind == "random"
            row = Strategy(key=key, name=f"AI-1 daily {kind}", venue_id=venue.id,
                status="paper", allocation_usd=D(0) if virtual else ALLOCATION,
                config={"virtual_only": virtual, "params": {}, "ready_for_live": False})
            session.add(row)
            session.flush()
            state = {**initial_state(virtual=virtual), "kind": kind, "arm": "AI1",
                     "allocation": str(ALLOCATION), "twins": {}, "admitted_at": now.isoformat(),
                     "review_record": REVIEW, "review_sha256": sha256(review.encode()).hexdigest(),
                     "frozen_identity": frozen}
            if virtual:
                state["book"] = EquityPaperBook(ALLOCATION).state
            trial = Trial(strategy_id=row.id, mode="paper", params={"kind": kind},
                git_commit=git_commit, code_version=VERSION, strategy_version=version,
                data_start=now, metrics={NAME: state})
            session.add(trial)
            session.flush()
            cohort[kind] = trial.id
        for kind, tid in cohort.items():
            trial = session.get(Trial, tid)
            state = runner.state(trial)
            state.update(cohort=cohort, leader_id=cohort["ungated"])
            if kind == "ungated":
                state["twins"] = {"random": cohort["random"]}
            trial.metrics = {NAME: state}
            row = session.get(Strategy, trial.strategy_id)
            row.config = {**row.config, VERSION: {"trial_id": tid}}
        session.commit()
        return cohort


def calibration(rows):
    """Paired probabilities/realized ungated outcomes; unavailable labels omitted."""
    if not rows:
        return {"count": 0, "brier": None, "always_yes_brier": None, "beats_always_yes": False}
    score = sum((p-D(y))**2 for p, y in rows)/len(rows)
    baseline = sum((D(1)-D(y))**2 for _, y in rows)/len(rows)
    return {"count": len(rows), "brier": str(score), "always_yes_brier": str(baseline),
            "beats_always_yes": score < baseline,
            "reliability": [{"lower": str(D(i)/5), "count": len(bin_rows),
                "mean_probability": str(sum(p for p, _ in bin_rows)/len(bin_rows)) if bin_rows else None,
                "positive_rate": str(sum(D(y) for _, y in bin_rows)/len(bin_rows)) if bin_rows else None}
                for i in range(5) for bin_rows in [[r for r in rows if min(4, int(r[0]*5)) == i]]]}


class DailyRunner(Runner):
    def __init__(self, session, api, *, model=None, claude=None, now=None, state_builder=build_state):
        super().__init__(session, api, model=model, now=now, state_builder=state_builder)
        self.claude = claude or ClaudeClient()

    def trials(self):
        return [t for t in self.session.scalars(select(Trial).where(
            Trial.code_version == VERSION, Trial.status == "running").order_by(Trial.id))
                if not self.state(t)["virtual"]]

    def core(self, trial):
        return DailyGate()

    def virtual_books(self, kind):
        return {t.id: (t, EquityPaperBook(self.state(t)["allocation"], self.state(t)["book"]))
            for t in self.session.scalars(select(Trial).where(Trial.code_version == VERSION,
                Trial.status == "running")) if self.state(t)["virtual"] and self.state(t)["kind"] == kind}

    def manage(self, trial, market, quotes=None):
        super().manage(trial, market, quotes)
        if market and market.is_open(self.now()) and self.now() >= market.opens_at+timedelta(minutes=62):
            for order in self.orders(trial):
                if order.side == "buy":
                    try:
                        self.connector.cancel(order.id)
                    except Exception:
                        self.session.rollback()
                        self.incident(trial, "entry_window_cancel_unavailable")

    def turns(self, leader):
        return list(self.session.scalars(select(JevTurn).where(JevTurn.trial_id == leader.id)
                                        .order_by(JevTurn.boundary)))

    def recent_sessions(self):
        days = []
        for offset in range(14):
            market = self.market(self.now()-timedelta(days=offset))
            if market and market.opens_at+timedelta(minutes=62) <= self.now():
                days.append(market.trade_date)
                if len(days) == 5:
                    break
        return days

    def provider_calls(self, calls):
        # No ORM objects cross threads. Jev owns an independent SessionLocal;
        # Claude only runs a bounded subprocess. Both use the same frozen data.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {kind: pool.submit(client.decide, **kwargs) for kind, (client, kwargs) in calls.items()}
            results = {}
            for kind, future in futures.items():
                try:
                    results[kind] = future.result()
                except Exception:
                    results[kind] = None
            return results

    def decide_cohort(self, leader, boundary, observation, market):
        if self.session.scalar(select(JevTurn.id).where(JevTurn.trial_id == leader.id, JevTurn.boundary == boundary)):
            return False
        cohort = {k: self.session.get(Trial, tid) for k, tid in self.state(leader)["cohort"].items()}
        turn = JevTurn(trial_id=leader.id, boundary=boundary, observed_at=timestamp(observation["at"]),
            payload={"status": "planning", "observation": observation, "seed": uuid4().hex,
                     "receipts": {}, "executions": [], "predictions": {}, "labels": {}})
        self.session.add(turn)
        self.session.commit()  # one daily cohort claim, before any provider/order
        try:
            core = DailyGate()
            view = View(timestamp(observation["at"]), boundary, observation["states"], {},
                        ALLOCATION, ALLOCATION, frozenset(), {})
            plan = core.plan(view)
            costs = {s.key: self._costs(s, view, observation, market) for s in plan.decisions}
            # The deadline and model input cover only what this cohort shows or
            # trades: its candidates plus SPY. On 2026-10-05 a 16s-old quote for
            # a non-candidate cut the window to 14s (six of eight ungated entries
            # expired), and all 40 observations were ~50k tokens, over Jev's 32k
            # state+question limit. Fixed once here and never renewed.
            deadline = turn_deadline(observation, core, {"ai1": plan})
            scope = set().union(*(core.observation_symbols(s) for s in plan.decisions))
            payload = deepcopy(turn.payload)
            payload.update(plans=plain(plan), costs=costs, candidate_count=len(plan.decisions),
                           deadline=deadline.isoformat(), observation_scope=sorted(scope),
                           regime=observation["states"].get("SPY", {}).get("features", {}).get("ret_session"))
            turn.payload = payload
            self.session.commit()
            required = ALLOCATION*FRACTION*len(plan.decisions)
            venue = self.connector._venue()
            account = self.connector._balance(venue, self.now()).available-account_costs(self.session, venue.id, self.now()).total
            code_ok = all(t.strategy_version == identity()[0] and
                self.state(t)["review_sha256"] == sha256((ROOT/REVIEW).read_bytes()).hexdigest()
                for t in cohort.values())
            reason = None
            if not code_ok:
                reason = "identity_changed"
            elif self.connector.risk.is_globally_halted("paper", self.now()) or any(
                    self.session.get(Strategy, cohort[k].strategy_id).status != "paper" for k in KINDS):
                reason = "risk_halted"
            elif not plan.decisions:
                reason = "no_complete_signals"
            elif any(self.positions(t) or self.orders(t) for k, t in cohort.items() if k in KINDS):
                reason = "unresolved_previous_day"
            elif account < (required+D(".20"))*len(KINDS) or any(
                    self.available(cohort[k]) < required+D(".10") for k in KINDS):
                reason = "insufficient_paired_settled_cash"
            elif any(costs[s.key]["enter"].get(s.key) is None or
                     D(costs[s.key]["enter"][s.key]["notional_usd"]) < 1 for s in plan.decisions):
                reason = "missing_execution_evidence"
            if reason:
                turn.payload = {**turn.payload, "status": "complete", "skip_reason": reason}
                self.session.commit()
                return True
            at = observation["at"]
            for trial in cohort.values():
                state = self.state(trial)
                state.update(started_at=state.get("started_at", at), last_observed_at=at)
                self.save(trial, state)
            questions = {s.key: {**s.questions["profit"], "instructions": TRUST+s.questions["profit"]["instructions"]}
                         for s in plan.decisions}
            model_state = {"observations": {symbol: {k: v for k, v in value.items() if k not in {"source_receipts", "cost"}}
                for symbol, value in observation["states"].items() if symbol in scope},
                "decisions": {s.key: {"context": s.state, "execution_by_option": costs[s.key]} for s in plan.decisions}}
            # An oversized request still fails closed inside JevClient, with no call or spend.
            turn.payload = {**turn.payload, "status": "deciding", "questions": questions,
                            "model_state_estimated_tokens": list(estimated_tokens(model_state, _validate_questions(questions)))}
            self.session.commit()
            calls = {kind: (client, dict(state=model_state, questions=questions, model=pin,
                     correlation_id=f"paper-trial:{cohort[kind].id}:ai1-turn-{turn.id}"))
                     for kind, client, pin in (("jev", self.model, "jev-latest"), ("claude", self.claude, CLAUDE_MODEL))}
            results = self.provider_calls(calls)
            selected = {"ungated": {s.key: "enter" for s in plan.decisions}, "jev": {}, "claude": {}}
            predictions, receipts = {}, {}
            for kind, result in results.items():
                receipts[kind] = {"status": "unavailable"}
                if result is None:
                    continue
                receipts[kind] = {**plain(asdict(result)), "status": "received"}
                try:
                    _validate_answers(result.answers, questions)
                    expected = MODEL_ID if kind == "jev" else CLAUDE_MODEL
                    if result.model_id != expected or self.now() >= deadline:
                        raise ValueError("Wrong model or expired observation")
                    predictions[kind] = {key: str(answer["noul"]) for key, answer in result.answers.items()}
                    selected[kind] = {s.key: core.choose(s, {"profit": result.answers[s.key]}) for s in plan.decisions}
                    receipts[kind]["status"] = "ok"
                except (ValueError, KeyError, TypeError):
                    receipts[kind]["status"] = "invalid_or_expired"
            # A random control with the same Jev pass count over identical signals.
            passing = sum(c == "enter" for c in selected["jev"].values())
            sampled = set(random.Random(turn.payload["seed"]).sample([s.key for s in plan.decisions], passing))
            selected["random"] = {s.key: "enter" if s.key in sampled else "skip" for s in plan.decisions}
            turn.payload = {**turn.payload, "receipts": receipts, "predictions": predictions,
                            "selections": selected, "status": "executing", "random_pass_count": passing}
            self.session.commit()  # includes unavailable/expired receipts and all choices
            self.refresh_risk()  # Jev charges count even on an all-skip response
            rotation = boundary.date().toordinal() % len(KINDS)
            order = KINDS[rotation:]+KINDS[:rotation]
            for spec in plan.decisions:
                for kind in (*order, "random"):
                    if selected[kind].get(spec.key) != "enter":
                        continue
                    target = spec.alternatives["enter"][0]
                    token = sha256(f"ai1:{turn.id}:{kind}:{spec.key}".encode()).hexdigest()[:32]
                    result = self.execute(cohort[kind], target, identity=token,
                        proof=costs[spec.key]["enter"][target.symbol], quote=observation["quotes"].get(target.symbol),
                        deadline=deadline, market=market)
                    payload = deepcopy(turn.payload)
                    payload["executions"].append({"kind": kind, "symbol": target.symbol, "identity": token, "result": result})
                    turn.payload = payload
                    self.session.commit()
            turn.payload = {**turn.payload, "status": "complete"}
            self.session.commit()
            return True
        except Exception as exc:
            self.session.rollback()
            turn.payload = {**turn.payload, "status": "error", "error": type(exc).__name__}
            self.session.commit()
            self.incident(leader, "ai1_cohort_failed", integrity=True)
            return False

    def performance(self, trial, costs):
        groups = defaultdict(list)
        fills = list(self.session.scalars(select(Fill).where(Fill.trial_id == trial.id, Fill.mode == "paper")
                                         .order_by(Fill.fill_ts, Fill.id)))
        for fill in fills:
            groups[fill.instrument_id].append(FillEvent(fill.side, fill.price, fill.size,
                (fill.fee or D(0))+costs.fee_by_fill.get(fill.id, D(0)), fill.fill_ts))
        trips = {iid: list(iter_round_trips(events)) for iid, events in groups.items()}
        positions, marked, unrealized = self.positions(trial), True, D(0)
        market = self.market(self.now())
        from tradingbot.forward.jev_intraday import quote_ok
        quotes = self.quotes(positions) if positions else {}
        for symbol, pos in positions.items():
            if not market or not quote_ok(quotes.get(symbol), self.now(), market):
                marked = False
            else:
                unrealized += (D(str(quotes[symbol]["bp"]))-D(pos["avg_price"]))*D(pos["quantity"])
        net = self.connector.ledger.realized_after_fees(trial_id=trial.id, mode="paper")-costs.by_trial.get(trial.id, D(0))+unrealized
        return net, trips, marked, positions, fills

    def report_cohort(self, leader, market):
        cohort = {k: self.session.get(Trial, tid) for k, tid in self.state(leader)["cohort"].items()}
        turns = self.turns(leader)
        costs = account_costs(self.session, self.connector._venue().id, self.now())
        performance = {k: self.performance(cohort[k], costs) for k in KINDS}
        instruments = self.instruments()
        outcomes_synced = True
        # Real ungated flat-to-flat outcomes label both passed and rejected gates.
        for turn in turns:
            labels = deepcopy(turn.payload.get("labels", {}))
            day = turn.boundary.astimezone(NEW_YORK).date()
            for symbol in turn.payload.get("questions", {}):
                if symbol in labels or symbol not in instruments:
                    continue
                trips = [t for t in performance["ungated"][1].get(instruments[symbol].id, [])
                         if t.entry_ts.astimezone(NEW_YORK).date() == day]
                if len(trips) == 1:
                    labels[symbol] = {"outcome": trips[0].net_pnl > 0, "net_pnl": str(trips[0].net_pnl),
                                      "observed_at": trips[0].exit_ts.isoformat()}
            if labels != turn.payload.get("labels", {}):
                turn.payload = {**turn.payload, "labels": labels}
                self.session.commit()
            receipt = turn.payload.get("receipts", {}).get("jev", {})
            if receipt.get("status") == "ok":
                for symbol, label in labels.items():
                    outcomes_synced &= self.model.record_outcome(receipt["request_id"], symbol, label["outcome"],
                                                observed_at=timestamp(label["observed_at"]))
        common_ok = (all(t.payload["status"] == "complete" for t in turns)
                     and not costs.unknown_request_ids and not self.state(leader)["integrity_errors"])
        recent = self.recent_sessions()
        recent_turns = [t for t in turns if t.boundary.astimezone(NEW_YORK).date() in recent]
        frequency = sum(t.payload.get("candidate_count", 0) for t in recent_turns)
        for kind in KINDS:
            trial, state = cohort[kind], self.state(cohort[kind])
            net, trips_by_symbol, marked, positions, fills = performance[kind]
            trips = [t for group in trips_by_symbol.values() for t in group]
            pairs = [(D(p), t.payload["labels"][symbol]["outcome"]) for t in turns
                     for symbol, p in t.payload.get("predictions", {}).get(kind, {}).items()
                     if symbol in t.payload.get("labels", {})]
            cal = calibration(pairs)
            missing = sum(symbol not in t.payload.get("labels", {}) for t in turns
                          for symbol in t.payload.get("predictions", {}).get(kind, {}))
            execution_gaps = []
            if kind != "ungated":
                for turn in turns:
                    day = turn.boundary.astimezone(NEW_YORK).date()
                    for symbol, choice in turn.payload.get("selections", {}).get(kind, {}).items():
                        if choice != "enter":
                            continue
                        iid = instruments[symbol].id if symbol in instruments else None
                        matched = []
                        for arm in ("ungated", kind):
                            arm_trips = [t for t in performance[arm][1].get(iid, []) if t.entry_ts.astimezone(NEW_YORK).date() == day]
                            quantity = sum((f.size for f in performance[arm][4] if f.instrument_id == iid
                                and f.side == "buy" and f.fill_ts.astimezone(NEW_YORK).date() == day), D(0))
                            matched.append((len(arm_trips), quantity))
                        if matched[0][0] != 1 or matched[1][0] != 1 or matched[0][1] != matched[1][1]:
                            execution_gaps.append({"day": day.isoformat(), "symbol": symbol})
            receipts = [t.payload["receipts"][kind] for t in turns if kind in t.payload.get("receipts", {})]
            receipt_ok = True
            estimated = sum((D(r.get("estimated_cost_usd", "0")) for r in receipts), D(0))
            estimate_complete = kind != "claude" or all("estimated_cost_usd" in r for r in receipts)
            for r in receipts:
                if r.get("status") == "ok":
                    receipt_ok &= r.get("model_id") == (MODEL_ID if kind == "jev" else CLAUDE_MODEL)
            if kind == "jev":
                receipt_ok &= outcomes_synced
                for r in receipts:
                    if r.get("status") != "ok":
                        continue
                    saved = self.session.get(JevRequest, r["request_id"])
                    receipt_ok &= (saved is not None and saved.status == "ok" and saved.model_id == MODEL_ID
                        and saved.correlation_id.startswith(f"paper-trial:{trial.id}:") and saved.actual_usd is not None)
            gate = evidence_gate(started_at=state.get("started_at"), observed_at=state.get("last_observed_at"),
                trade_count=len(trips), net_pnl=net, flat=not positions, pending=bool(self.orders(trial)),
                integrity_ok=common_ok and receipt_ok and marked and trial.strategy_version == identity()[0]
                    and not state["integrity_errors"] and self.session.get(Strategy, trial.strategy_id).status == "paper"
                    and sha256((ROOT/REVIEW).read_bytes()).hexdigest() == state["review_sha256"]
                    and not self.connector.risk.is_globally_halted("paper", self.now()))
            extra = []
            if kind == "ungated":
                extra.append("baseline_control_only")
            else:
                if net <= performance["ungated"][0] or not performance["ungated"][2]:
                    extra.append("does_not_beat_ungated_after_costs")
                if cal["count"] < 30 or missing or not cal["beats_always_yes"]:
                    extra.append("calibration_not_proven")
                if execution_gaps:
                    extra.append("unmatched_selected_execution")
                if len(recent) < 5 or len(recent_turns) < 5 or frequency < 30:
                    extra.append("base_frequency_below_30_per_five_sessions")
            gate["reasons"].extend(extra)
            gate["eligible_for_review"] &= not extra
            state = update_readiness(state, gate, self.now(), flat=not positions and not self.orders(trial))
            if marked:
                peak = max(D(state["peak_net"]), net)
                state.update(peak_net=str(peak), max_drawdown=str(max(D(state["max_drawdown"]), peak-net)))
                state["daily_net"][self.now().date().isoformat()] = str(net)
            daily, previous = [], D(0)
            for _, value in sorted(state["daily_net"].items()):
                daily.append(D(value)-previous)
                previous = D(value)
            regime = defaultdict(lambda: D(0))
            for trip in trips:
                turn = next((t for t in turns if t.boundary.astimezone(NEW_YORK).date()
                             == trip.entry_ts.astimezone(NEW_YORK).date()), None)
                ret = turn.payload.get("regime") if turn else None
                label = "unknown" if ret is None else "up" if D(ret) > 0 else "down" if D(ret) < 0 else "flat"
                regime[label] += trip.net_pnl
            state.update(net_after_costs=str(net) if marked else None, calibration=cal, unlabeled_predictions=missing,
                paired_execution_gaps=execution_gaps,
                completed_round_trips=len(trips), base_signals_last_five_sessions=frequency,
                trial_kind="real_alpaca_paper", marks_complete=marked, model_receipts_complete=receipt_ok,
                code_identity_unchanged=trial.strategy_version == identity()[0], regime_trade_net=plain(dict(regime)),
                model_estimated_cost_usd=str(estimated) if estimate_complete else None,
                model_estimated_cost_complete=estimate_complete,
                provider_unavailable_days=sum(r.get("status") != "ok" for r in receipts),
                net_less_claude_list_price_estimate=str(net-estimated) if estimate_complete and marked else None,
                additional_costs=str(costs.by_trial.get(trial.id, D(0))))
            trial.pnl_after_fees, trial.trade_count, trial.max_drawdown = net if marked else None, len(trips), D(state["max_drawdown"])
            trial.fees_total = sum((f.fee or D(0) for f in fills), D(0))+costs.by_trial.get(trial.id, D(0))
            probability = luck_probability(daily)
            trial.luck_p_value = D(str(probability)) if probability is not None else None
            trial.data_end = timestamp(state["last_observed_at"]) if state.get("last_observed_at") else None
            row = self.session.get(Strategy, trial.strategy_id)
            row.config = {**row.config, "ready_for_live": state.get("ready_for_live", False),
                "pipeline_state": "ready-for-live" if state.get("ready_for_live") else "paper"}
            self.save(trial, state)
        self.report_virtual(cohort["random"], market)

    def tick(self):
        trials = self.trials()
        if not trials:
            return {"status": "waiting_for_admitted_strategies", "active_arms": 0}
        leader = next(t for t in trials if self.state(t)["kind"] == "ungated")
        market = self.market(self.now())
        with trial_lock(self.session, leader.id):
            quotes = {}
            for trial in trials:
                self.manage(trial, market, quotes)
            risk_ok = False
            if market and market.is_open(self.now()):
                try:
                    self.refresh_risk()
                    risk_ok = True
                except Exception:
                    self.session.rollback()
                    self.incident(leader, "risk_evidence_unavailable")
                try:
                    self.mark_virtual(self.virtual_books("random"), quotes, market)
                except Exception:
                    self.session.rollback()
            boundary = due_boundary(self.now(), market)
            if boundary and risk_ok and not self.session.scalar(select(JevTurn.id).where(
                    JevTurn.trial_id == leader.id, JevTurn.boundary == boundary)):
                if self.state_builder is build_state and not any(load_snapshot(self.session, s,
                        decision_at=self.now(), boundary=boundary) for s in SYMBOLS):
                    return {"status": "waiting_for_snapshot", "active_arms": len(trials)}
                self.decide_cohort(leader, boundary, self.observation(boundary, market), market)
            elif market and self.now() >= market.opens_at+timedelta(minutes=62):
                missed = market.opens_at+timedelta(hours=1)
                if not self.session.scalar(select(JevTurn.id).where(JevTurn.trial_id == leader.id,
                                                                  JevTurn.boundary == missed)):
                    self.session.add(JevTurn(trial_id=leader.id, boundary=missed, observed_at=self.now(),
                        payload={"status": "complete", "skip_reason": "missed_snapshot_or_entry_window",
                                 "candidate_count": 0, "labels": {}, "predictions": {}, "receipts": {}}))
                    self.session.commit()
            if self._last_report is None or self.now()-self._last_report >= timedelta(minutes=1):
                self.report_cohort(leader, market)
                self._last_report = self.now()
        return {"status": "running" if market and market.is_open(self.now()) else "outside_session", "active_arms": len(trials)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    with get_engine().connect() as lock, SessionLocal() as session:
        if args.prepare:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            print(json.dumps(prepare(session, git_commit=commit)))
            return
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
            raise SystemExit("AI-1 daily service already running")
        lock.commit()
        runner = DailyRunner(session, AlpacaPaperAPI.from_env())
        try:
            while True:
                try:
                    print(json.dumps({"at": datetime.now(UTC).isoformat(), **runner.tick()}), flush=True)
                except Exception as exc:
                    session.rollback()
                    print(json.dumps({"status": "unavailable", "error": type(exc).__name__}), flush=True)
                if args.once:
                    break
                time.sleep(15-time.time()%15)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})


if __name__ == "__main__":
    main()
