"""Prospective daily AI-2 baskets over unchanged J-suite paper execution.

The shared state key is deliberately retained for inherited execution methods;
the independent code_version and singleton lock isolate this cohort from J1-J4.
No historical model calls, account funding, live transport or startup reconcile.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D, ROUND_DOWN
from hashlib import sha256
import json
import subprocess
import time
from uuid import uuid4

from sqlalchemy import select, text

from tradingbot.ai.claude import ClaudeClient, MODEL_ID as CLAUDE_MODEL
from tradingbot.ai.jev import JevClient, MODEL_ID, MAX_CALL_USD
from tradingbot.ai.state import build_state
from tradingbot.backtest.holdout import strategy_identity
from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.cash import NEW_YORK, timestamp
from tradingbot.data.iex_intraday import load_snapshot
from tradingbot.db.models import Fill, JevRequest, JevTurn, Strategy as StrategyRow, Trial
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.forward.ai import evidence_gate, trial_lock
from tradingbot.forward.ai_paper_costs import account_costs
from tradingbot.forward.jev_intraday import (
    NAME, ROOT, CLOSE_BUFFER, Runner, initial_state, plain, price_tick, quote_ok,
    identity as intraday_identity,
)
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import luck_probability
from tradingbot.paper.equities import EquityPaperBook, QTY
from tradingbot.risk import limits
from tradingbot.strategy.ai2_basket import AnalystBasket, UNIVERSE, START, END, FRACTION, probabilities, questions, random_longs

VERSION = "ai2_daily_basket_v2"
REVIEW = "docs/research/44-ai2-analyst-basket-plan.md"
ALLOCATION = D(35)
KINDS = ("jev", "claude", "random", "benchmark")
REAL = KINDS[:2]
LOCK_ID = 0x4149324441494C
ENTRY_OFFSET = timedelta(minutes=45)
ENTRY_WINDOW = timedelta(minutes=2)
ZERO = D(0)


def identity(kind):
    return strategy_identity(AnalystBasket(), AnalystRunner,
        {"version": VERSION, "kind": kind, "allocation": str(ALLOCATION),
         "universe": UNIVERSE, "start": START.isoformat(), "end": END.isoformat(),
         "entry_minutes": 45, "entry_window_seconds": 120, "fraction": str(FRACTION),
         "jev_model": MODEL_ID, "claude_model": CLAUDE_MODEL,
         "shared_execution_identity": intraday_identity(AnalystBasket(), ALLOCATION)[0]},
        execution_types=(Runner, ClaudeClient, JevClient, build_state, EquityPaperBook, account_costs))


def prepare(session, *, git_commit, now=None):
    """Admit four ledger variants with two actual paper allocations; never fund."""
    now = timestamp(now or datetime.now(UTC))
    with trial_lock(session, 0):
        runner = AnalystRunner(session, None)
        venue = runner.connector._venue()
        cohort = {}
        for kind in KINDS:
            key = f"ai2-daily-{kind}-v2"
            row = session.scalar(select(StrategyRow).where(StrategyRow.key == key))
            if row is None:
                row = StrategyRow(key=key, name=f"AI-2 daily {kind}", venue_id=venue.id, status="paper",
                    allocation_usd=ALLOCATION if kind in REAL else ZERO,
                    config={"virtual_only": kind not in REAL, "params": {}, "ready_for_live": False})
                session.add(row)
                session.flush()
            trial = Trial(strategy_id=row.id, mode="paper", code_version=VERSION, params={},
                          git_commit=git_commit, data_start=now, metrics={})
            session.add(trial)
            session.flush()
            cohort[kind] = trial
        session.commit()  # failed admission attempts remain in the trials ledger
        try:
            other = session.scalar(select(Trial.id).where(Trial.code_version == VERSION,
                Trial.status == "running", Trial.id.not_in([t.id for t in cohort.values()])))
            if other is not None:
                raise ValueError("AI2 already has an active cohort")
            book = runner.connector._book(venue)
            if D(book["initial_cash"]) < ALLOCATION*len(REAL):
                raise ValueError("Existing paper book cannot support this cohort")
            if set(UNIVERSE)-set(runner.instruments()):
                raise ValueError("Register all twenty reviewed equities before admission")
            review = (ROOT/REVIEW).read_text()
            if "what could blow up this account" not in review.lower():
                raise ValueError("Complete the written promotion/risk review")
            for kind, trial in cohort.items():
                row = session.get(StrategyRow, trial.strategy_id)
                expected_allocation = ALLOCATION if kind in REAL else ZERO
                if row.status != "paper" or row.venue_id != venue.id or row.allocation_usd != expected_allocation:
                    raise ValueError("Preserve existing strategy configuration; admission cannot reset it")
                if runner.orders(trial) or runner.connector.ledger.open_positions(strategy_id=row.id, mode="paper"):
                    raise ValueError("Admission requires a flat strategy without active intents")
                trial.strategy_version, frozen = identity(kind)
                state = {**initial_state(virtual=kind not in REAL), "arm": "AI2", "kind": kind,
                    "allocation": str(ALLOCATION), "cohort": {k: t.id for k, t in cohort.items()},
                    "twins": {}, "admitted_at": now.isoformat(), "review_record": REVIEW,
                    "review_sha256": sha256(review.encode()).hexdigest(), "frozen_identity": frozen,
                    "ready_for_live": False, "eligible_for_review": False}
                if kind == "jev":
                    state["twins"] = {k: cohort[k].id for k in ("random", "benchmark")}
                if kind not in REAL:
                    state["book"] = EquityPaperBook(ALLOCATION).state
                trial.metrics = {NAME: state}
                row.config = {**(row.config or {}), VERSION: {"trial_id": trial.id}, "ready_for_live": False}
            session.commit()
            return {kind: trial.id for kind, trial in cohort.items()}
        except Exception as exc:
            session.rollback()
            for trial in cohort.values():
                trial.status, trial.completed_ts = "failed", now
                trial.notes = f"AI2 admission failed: {type(exc).__name__}"
            session.commit()
            raise


def calibration(pairs):
    """Fixed reliability bins; unknown outcomes never become negative labels."""
    bins = [{"lower": str(D(i)/5), "upper": str(D(i+1)/5), "count": 0,
             "mean_probability": None, "positive_fraction": None} for i in range(5)]
    if not pairs:
        return {"count": 0, "brier": None, "always_yes_brier": None, "coin_brier": None, "bins": bins}
    groups = defaultdict(list)
    for p, y in pairs:
        groups[min(4, int(p*5))].append((p, D(int(y))))
    for index, rows in groups.items():
        bins[index].update(count=len(rows), mean_probability=str(sum(p for p, _ in rows)/len(rows)),
                           positive_fraction=str(sum(y for _, y in rows)/len(rows)))
    return {"count": len(pairs), "brier": str(sum((p-D(int(y)))**2 for p, y in pairs)/len(pairs)),
            "always_yes_brier": str(sum((D(1)-D(int(y)))**2 for _, y in pairs)/len(pairs)),
            "coin_brier": "0.25", "bins": bins, "outcome_basis": "virtual_benchmark_net_after_fees"}


class AnalystRunner(Runner):
    def __init__(self, session, api, *, model=None, claude=None, now=None, state_builder=build_state):
        super().__init__(session, api, model=model, now=now, state_builder=state_builder)
        self.claude = claude or ClaudeClient()
        self._entry_quotes = None

    def cohort(self):
        rows = list(self.session.scalars(select(Trial).where(Trial.code_version == VERSION,
                    Trial.status == "running").order_by(Trial.id)))
        if not rows:
            return {}
        result = {self.state(t)["kind"]: t for t in rows}
        if len(rows) != len(KINDS) or set(result) != set(KINDS):
            raise ValueError("Incomplete or duplicate AI2 cohort")
        expected = {k: t.id for k, t in result.items()}
        if any(self.state(t)["cohort"] != expected for t in rows):
            raise ValueError("Mismatched AI2 cohort")
        return result

    def trials(self):
        return [t for kind, t in self.cohort().items() if kind in REAL]

    def virtual_books(self, kind):
        return {t.id: (t, EquityPaperBook(self.state(t)["allocation"], self.state(t)["book"]))
                for k, t in self.cohort().items() if k == kind and k not in REAL}

    def mark_virtual(self, books, quotes, market):
        if self._entry_quotes is not None:
            quotes.update(self._entry_quotes)  # reuse the original still-fresh cutoff; never renew it
        return super().mark_virtual(books, quotes, market)

    def identity_ok(self, trial):
        try:
            state = self.state(trial)
            row = self.session.get(StrategyRow, trial.strategy_id, populate_existing=True)
            return (trial.strategy_version == identity(state["kind"])[0] and trial.params == {}
                and sha256((ROOT/REVIEW).read_bytes()).hexdigest() == state["review_sha256"]
                and state["allocation"] == str(ALLOCATION)
                and row.status == "paper" and row.allocation_usd == (ZERO if state["virtual"] else ALLOCATION))
        except Exception:
            return False

    def observation(self, boundary, market):
        previous = self.previous_market(self.now()) if self.state_builder is build_state else None
        at, states = self.now(), {}
        for symbol in UNIVERSE:
            kwargs = {"previous_session": previous} if self.state_builder is build_state else {}
            state = self.state_builder(self.session, symbol, decision_at=at, boundary=boundary, **kwargs)
            if state is not None:
                states[symbol] = deepcopy(state)
        quotes = self.quotes(UNIVERSE)
        observed_at = self.now()
        for symbol, state in states.items():
            state["execution_quote"] = deepcopy(quotes.get(symbol))
            state["execution_quote_observed_at"] = observed_at.isoformat()
        # Plan Amendment 1 (jxa): a most-recent interval with a bar-less IEX minute no
        # longer skips the day. Its features stay explicit nulls in the shared state,
        # visible to both models with its quality flags; nothing is backfilled.
        valid = set(states) == set(quotes) == set(UNIVERSE) and all(
            quote_ok(quotes[s], self.now(), market)
            and not states[s].get("events", {}).get("collection_halted", True) for s in UNIVERSE)
        incomplete = sorted(s for s, state in states.items()
                            if state.get("quality", {}).get("complete_suffix_intervals", 0) < 1)
        deadline = min([at+timedelta(seconds=limits.STALE_DATA_MAX_SECONDS)] + [
            timestamp(q["t"])+timedelta(seconds=limits.STALE_DATA_MAX_SECONDS) for q in quotes.values()
            if quote_ok(q, self.now(), market)])
        return {"at": at.isoformat(), "boundary": boundary.isoformat(), "valid": valid,
                "incomplete_latest_interval": incomplete,
                "states": states, "quotes": quotes, "deadline": deadline.isoformat(),
                "capture_completed_at": self.now().isoformat(), "previous_session": plain(previous) if previous else None}

    def common_budget(self, cohort):
        if any(self.orders(t) or self.positions(t) for k, t in cohort.items() if k in REAL):
            return ZERO
        virtual_cash = []
        for kind in KINDS[2:]:
            state = self.state(cohort[kind])
            book = EquityPaperBook(ALLOCATION, state["book"])
            if book.state["positions"] or book.state.get("killed"):
                return ZERO
            virtual_cash.append(book.cash(self.now()).available)
        venue = self.connector._venue()
        costs = account_costs(self.session, venue.id, self.now())
        cash = self.connector._balance(venue, self.now()).available-costs.total-D(".42")-2*MAX_CALL_USD
        return max(ZERO, FRACTION*min(ALLOCATION, cash/2, *virtual_cash,
                                     *(self.available(cohort[k]) for k in REAL)))

    def update_turn(self, turn, **changes):
        payload = deepcopy(turn.payload)
        payload.update(plain(changes))
        turn.payload = payload
        self.session.commit()

    def execute_basket(self, trial, selected, budget, observation, market, turn):
        if not selected:
            return []
        targets = AnalystBasket().targets(selected, budget=budget, allocation=ALLOCATION)
        outcomes = []
        for target in targets:
            quote = observation["quotes"][target.symbol]
            price = price_tick(D(str(quote["ap"])), "buy")
            quantity = (budget/len(targets)/price).quantize(QTY, rounding=ROUND_DOWN)
            request_id = sha256(f"ai2:{turn.id}:{trial.id}:{target.symbol}".encode()).hexdigest()[:32]
            try:
                result = self.execute(trial, target, identity=request_id, proof={"quantity": str(quantity)},
                    quote=quote, deadline=timestamp(observation["deadline"]), market=market)
            except Exception as exc:
                self.session.rollback()
                self.incident(trial, "ai2_entry_unavailable")
                result = {"error": type(exc).__name__}
            outcome = {"kind": self.state(trial)["kind"], "symbol": target.symbol,
                       "request_id": request_id, "quantity": str(quantity), "result": result}
            outcomes.append(outcome)
            self.update_turn(turn, executions=[*turn.payload["executions"], outcome])
        return outcomes

    def call_model(self, kind, trial, turn, model_state, question_set):
        deadline = timestamp(turn.payload["observation"]["deadline"])
        arms = deepcopy(turn.payload["arms"])
        arms[kind] = {"status": "pending", "called_at": self.now().isoformat()}
        self.update_turn(turn, arms=arms)
        if self.now() >= deadline:
            return {"status": "expired_before_call"}
        if self.session.get(StrategyRow, trial.strategy_id).status != "paper" or self.connector.risk.is_globally_halted("paper", self.now()):
            return {"status": "risk_veto_before_call"}
        provider = self.model if kind == "jev" else self.claude
        correlation = f"paper-trial:{trial.id}:ai2-turn-{turn.id}"
        try:
            result = provider.decide(state=deepcopy(model_state), questions=deepcopy(question_set),
                model="jev-latest" if kind == "jev" else CLAUDE_MODEL, correlation_id=correlation)
        except Exception:
            result = None
        receipt = {"status": "unavailable", "correlation_id": correlation, "called": True,
                   "completed_at": self.now().isoformat(), "selected": []}
        if kind == "claude":
            receipt.update(billing_basis="existing_subscription_zero_incremental_cash", estimated_cost_usd=None)
        if result is not None:
            receipt["provider"] = plain(asdict(result))
            if kind == "claude":
                receipt["estimated_cost_usd"] = str(result.estimated_cost_usd)
        # Charge/mark the account even if an answer is unavailable or expired.
        try:
            self.refresh_risk()
        except Exception:
            self.session.rollback()
            receipt["status"] = "risk_evidence_unavailable"
            return receipt
        if result is None:
            return receipt
        try:
            expected_model = MODEL_ID if kind == "jev" else CLAUDE_MODEL
            if result.model_id != expected_model or not isinstance(result.cost_usd, D) or not result.cost_usd.is_finite() or result.cost_usd < 0:
                raise ValueError("Invalid provider receipt")
            if kind == "jev":
                row = self.session.get(JevRequest, result.request_id, populate_existing=True)
                if (row is None or row.status != "ok" or row.model_id != MODEL_ID
                        or row.correlation_id != correlation or row.answers != result.answers
                        or row.actual_usd != result.cost_usd or row.reserved_usd != ZERO):
                    raise ValueError("Unverifiable Jev receipt")
            elif result.cost_usd != ZERO or result.billing_basis != "existing_subscription_zero_incremental_cash":
                raise ValueError("Unexpected Claude billing basis")
            values = probabilities(result.answers)
            receipt["probabilities"] = {s: str(p) for s, p in values.items()}
            receipt["confidence"] = {s: str(max(p, 1-p)) for s, p in values.items()}
            if self.now() >= deadline:
                receipt["status"] = "expired"
            else:
                receipt.update(status="ok", selected=list(AnalystBasket().select(result.answers)))
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            receipt["status"] = "invalid_receipt_or_answers"
        return receipt

    def decide_daily(self, cohort, boundary, market, *, missed=False):
        now = self.now()
        if (market is None or not START <= market.trade_date <= END
                or boundary != market.opens_at+ENTRY_OFFSET or now < boundary):
            return False
        missed = missed or not market.is_open(now) or now >= boundary+ENTRY_WINDOW
        primary = cohort["jev"]
        if self.session.scalar(select(JevTurn.id).where(JevTurn.trial_id == primary.id, JevTurn.boundary == boundary)):
            return False
        turn = JevTurn(trial_id=primary.id, boundary=boundary, observed_at=self.now(),
            payload={"status": "planning", "seed": uuid4().hex, "arms": {}, "executions": [], "labels": {}})
        self.session.add(turn)
        self.session.commit()
        try:
            if missed:
                self.update_turn(turn, status="skipped", reason="missed_entry_window")
                return False
            if not all(self.identity_ok(t) for t in cohort.values()):
                self.update_turn(turn, status="skipped", reason="identity_or_strategy_changed")
                return False
            observation = self.observation(boundary, market)
            turn.observed_at = timestamp(observation["at"])
            self.update_turn(turn, observation=observation)
            budget = self.common_budget(cohort)
            if not observation["valid"] or self.now() >= timestamp(observation["deadline"]):
                self.update_turn(turn, status="skipped", reason="incomplete_or_stale_twenty_stock_snapshot")
                return False
            if budget < len(UNIVERSE) or any((budget/len(UNIVERSE)/price_tick(D(str(observation["quotes"][s]["ap"])), "buy")
                    ).quantize(QTY, rounding=ROUND_DOWN)*price_tick(D(str(observation["quotes"][s]["ap"])), "buy") < 1 for s in UNIVERSE):
                self.update_turn(turn, status="skipped", reason="insufficient_paired_settled_cash_or_residual_exposure", budget=str(budget))
                return False
            question_set = questions(observation["quotes"], budget, market)
            model_state = {"observations": {s: {k: deepcopy(v) for k, v in state.items()
                    if k not in {"news", "source_receipts", "cost"}} for s, state in observation["states"].items()},
                "policy": {"universe": list(UNIVERSE), "budget_usd": str(budget), "exit_at": (market.closes_at-CLOSE_BUFFER).isoformat()}}
            order = list(REAL) if market.trade_date.toordinal() % 2 == 0 else list(reversed(REAL))
            self.update_turn(turn, status="deciding", budget=str(budget), questions=question_set,
                model_state=model_state, model_state_sha256=sha256(json.dumps(model_state, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                model_order=order)
            for trial in cohort.values():
                state = self.state(trial)
                state.update(started_at=state.get("started_at", observation["at"]), last_observed_at=observation["at"])
                self.save(trial, state)
            self._entry_quotes = observation["quotes"]
            self.execute_basket(cohort["benchmark"], UNIVERSE, budget, observation, market, turn)
            for kind in order:
                receipt = self.call_model(kind, cohort[kind], turn, model_state, question_set)
                arms = deepcopy(turn.payload["arms"])
                arms[kind] = receipt
                self.update_turn(turn, arms=arms)
                selected = receipt.get("selected", []) if receipt["status"] == "ok" else []
                self.execute_basket(cohort[kind], selected, budget, observation, market, turn)
                if kind == "jev":
                    random_selected = random_longs(len(selected), turn.payload["seed"])
                    self.update_turn(turn, random_selected=random_selected)
                    self.execute_basket(cohort["random"], random_selected, budget, observation, market, turn)
            self.update_turn(turn, status="complete")
            return True
        except Exception as exc:
            self.session.rollback()
            self.update_turn(turn, status="error", error=type(exc).__name__)
            self.incident(primary, "ai2_turn_failed", integrity=True)
            return False
        finally:
            self._entry_quotes = None

    def manage(self, trial, market, quotes=None):
        super().manage(trial, market, quotes)
        if market and market.is_open(self.now()) and self.now() >= market.opens_at+ENTRY_OFFSET+ENTRY_WINDOW:
            for order in self.orders(trial):
                if order.side == "buy":
                    try:
                        self.connector.cancel(order.id)
                    except Exception:
                        self.session.rollback()
                        self.incident(trial, "ai2_entry_cancel_unavailable")

    def summarize(self, trial, costs, market):
        """Actual ledger fills for real arms; separate simulator receipts for controls."""
        state = self.state(trial)
        virtual = state["virtual"]
        if virtual:
            book = EquityPaperBook(ALLOCATION, state["book"])
            positions = book.state["positions"]
            fills = [{"symbol": f["symbol"], "side": f["side"], "price": D(f["price"]),
                      "size": D(f["quantity"]), "fee": D(f["fee"]), "at": timestamp(f["at"])}
                     for f in book.state["fills"]]
            additional, model_cost, broker_fees = ZERO, ZERO, ZERO
            regulatory = sum((f["fee"] for f in fills), ZERO)
        else:
            symbols = {i.id: s for s, i in self.instruments().items()}
            actual = list(self.session.scalars(select(Fill).where(Fill.trial_id == trial.id, Fill.mode == "paper")
                                              .order_by(Fill.fill_ts, Fill.id)))
            fills = [{"symbol": symbols[f.instrument_id], "side": f.side, "price": f.price,
                      "size": f.size, "fee": (f.fee or ZERO)+costs.fee_by_fill.get(f.id, ZERO), "at": f.fill_ts}
                     for f in actual]
            positions = self.positions(trial)
            broker_fees = sum((f.fee or ZERO for f in actual), ZERO)
            regulatory = sum((costs.fee_by_fill.get(f.id, ZERO) for f in actual), ZERO)
            model_cost = costs.by_trial.get(trial.id, ZERO)-regulatory
            additional = costs.by_trial.get(trial.id, ZERO)
        try:
            quote_map = self.quotes(positions) if positions else {}
        except Exception:
            quote_map = {}  # Missing marks are unknown P&L, never yesterday's gain.
        marked = all(market is not None and quote_ok(quote_map.get(s), self.now(), market) for s in positions)
        gross = sum((f["price"]*f["size"]*(1 if f["side"] == "sell" else -1) for f in fills), ZERO)
        exposure = sum((D(pos["quantity"])*D(str(quote_map[s]["bp"])) for s, pos in positions.items()), ZERO) if marked else None
        if marked:
            gross += exposure
        fees = sum((f["fee"] for f in fills), ZERO)+model_cost
        net = gross-fees if marked else None
        events = defaultdict(list)
        for f in fills:
            events[f["symbol"]].append(FillEvent(f["side"], f["price"], f["size"], f["fee"], f["at"]))
        trips = [(symbol, trip) for symbol, rows in events.items() for trip in iter_round_trips(rows)]
        if marked:
            peak = max(D(state["peak_net"]), net)
            state.update(peak_net=str(peak), max_drawdown=str(max(D(state["max_drawdown"]), peak-net)))
            if state.get("started_at"):
                state["daily_net"][self.now().astimezone(NEW_YORK).date().isoformat()] = str(net)
        state.update(net_after_costs=str(net) if marked else None, gross_pnl=str(gross) if marked else None,
            marks_complete=marked, additional_costs=str(additional), model_cost_usd=str(model_cost),
            actual_broker_fees_usd=str(broker_fees), regulatory_fees_usd=str(regulatory),
            completed_round_trips=len(trips), open_positions=len(positions),
            current_exposure_usd=str(exposure) if exposure is not None else None,
            turnover_usd=str(sum((f["price"]*f["size"] for f in fills), ZERO)),
            trial_kind="virtual_diagnostic" if virtual else "real_alpaca_paper",
            trade_count_definition="completed flat-to-flat round trips", ready_for_live=False)
        trial.pnl, trial.pnl_after_fees, trial.fees_total = gross if marked else None, net, fees
        trial.trade_count, trial.max_drawdown = len(trips), D(state["max_drawdown"])
        trial.data_end = timestamp(state["last_observed_at"]) if state.get("last_observed_at") else None
        self.save(trial, state)
        return {"net": net, "positions": positions, "trips": trips, "marked": marked}

    def label_forecasts(self, turns, benchmark):
        outcomes = {}
        for symbol, trip in benchmark["trips"]:
            if trip.entry_ts is not None:
                day = trip.entry_ts.astimezone(NEW_YORK).date().isoformat()
                key = day, symbol
                if key in outcomes:
                    raise ValueError("More than one benchmark round trip per stock/day")
                outcomes[key] = {"value": trip.net_pnl > 0, "net_after_fees": str(trip.net_pnl),
                                 "observed_at": trip.exit_ts.isoformat()}
        for turn in turns:
            if not turn.payload.get("questions"):
                continue
            day = turn.boundary.astimezone(NEW_YORK).date().isoformat()
            labels = {s: outcomes[(day, s)] for s in UNIVERSE if (day, s) in outcomes}
            if labels != turn.payload.get("labels", {}):
                old = turn.payload.get("labels", {})
                if any(s not in labels or labels[s] != value for s, value in old.items()):
                    raise ValueError("A recorded benchmark outcome changed")
                self.update_turn(turn, labels=labels)
            jev = turn.payload.get("arms", {}).get("jev", {})
            provider = jev.get("provider", {})
            if provider.get("request_id") and jev.get("probabilities"):
                recorded = list(turn.payload.get("jev_labels_recorded", []))
                for symbol, label in labels.items():
                    if symbol not in recorded and self.model.record_outcome(provider["request_id"], symbol,
                            label["value"], observed_at=timestamp(label["observed_at"])):
                        recorded.append(symbol)
                if recorded != turn.payload.get("jev_labels_recorded", []):
                    self.update_turn(turn, jev_labels_recorded=recorded)

    def report_cohort(self, cohort, market):
        now = self.now()
        costs = account_costs(self.session, self.connector._venue().id, now)
        summaries = {kind: self.summarize(trial, costs, market) for kind, trial in cohort.items()}
        turns = list(self.session.scalars(select(JevTurn).where(JevTurn.trial_id == cohort["jev"].id)
                                         .order_by(JevTurn.boundary)))
        self.label_forecasts(turns, summaries["benchmark"])
        benchmark_complete = all(len(t.payload.get("labels", {})) == len(UNIVERSE)
                                 for t in turns if t.payload.get("questions"))
        interrupted = any(t.payload["status"] not in {"complete", "skipped", "error"} for t in turns)
        finished = (now.astimezone(NEW_YORK).date() > END or market is not None
                    and market.trade_date == END and now >= market.closes_at)
        records_ok = all(self.identity_ok(t) and not self.state(t)["integrity_errors"] for t in cohort.values())
        requests = list(self.session.scalars(select(JevRequest).where(
            JevRequest.correlation_id.startswith(f"paper-trial:{cohort['jev'].id}:"))))
        requests_by_id = {r.id: r for r in requests}
        for kind in REAL:
            trial, summary = cohort[kind], summaries[kind]
            state = self.state(trial)
            pairs, estimated, estimate_unknown, receipts_ok = [], ZERO, 0, True
            decision_counts = defaultdict(int)
            execution_counts, latencies = defaultdict(int), []
            for turn in turns:
                arm = turn.payload.get("arms", {}).get(kind)
                if not arm:
                    continue
                decision_counts[arm["status"]] += 1
                receipt = arm.get("provider")
                if receipt:
                    latencies.append(receipt["latency_ms"])
                    expected_model = MODEL_ID if kind == "jev" else CLAUDE_MODEL
                    receipts_ok &= receipt.get("model_id") == expected_model
                    if kind == "jev":
                        row = requests_by_id.get(receipt["request_id"])
                        receipts_ok &= (row is not None and row.status == "ok" and row.model_id == MODEL_ID
                            and row.correlation_id == f"paper-trial:{trial.id}:ai2-turn-{turn.id}"
                            and row.answers == receipt["answers"] and row.actual_usd == D(receipt["cost_usd"])
                            and row.reserved_usd == ZERO and row.questions == turn.payload["questions"])
                    else:
                        receipts_ok &= (receipt.get("billing_basis") == "existing_subscription_zero_incremental_cash"
                                        and D(receipt["cost_usd"]) == ZERO)
                if kind == "claude" and arm.get("called"):
                    if arm.get("estimated_cost_usd") is None:
                        estimate_unknown += 1
                    else:
                        estimated += D(arm["estimated_cost_usd"])
                for symbol, probability in arm.get("probabilities", {}).items():
                    label = turn.payload.get("labels", {}).get(symbol)
                    if label is not None:
                        pairs.append((D(probability), label["value"]))
                for execution in turn.payload.get("executions", []):
                    if execution["kind"] == kind:
                        result = execution["result"]
                        outcome = result if isinstance(result, str) else result.get("status", result.get("held", result.get("error", "unknown")))
                        execution_counts[outcome] += 1
            net = summary["net"]
            benchmark_net = summaries["benchmark"]["net"]
            gate = evidence_gate(started_at=state.get("started_at"), observed_at=state.get("last_observed_at"),
                trade_count=trial.trade_count, net_pnl=net if net is not None else ZERO,
                flat=not summary["positions"], pending=bool(self.orders(trial)),
                integrity_ok=(records_ok and summary["marked"] and receipts_ok and not interrupted
                    and not costs.unknown_request_ids and not self.connector.risk.is_globally_halted("paper", now)))
            if not finished:
                gate["reasons"].append("fixed_prospective_window_not_finished")
            if not benchmark_complete or benchmark_net is None or summaries["benchmark"]["positions"]:
                gate["reasons"].append("incomplete_virtual_benchmark")
            elif net is None or net <= benchmark_net:
                gate["reasons"].append("does_not_beat_equal_weight_benchmark")
            gate["eligible_for_review"] = not gate["reasons"]
            gate["benchmark_net_after_costs"] = str(benchmark_net) if benchmark_net is not None else None
            gate["benchmark_basis"] = "virtual_fresh_BBO_control_requires_execution_fidelity_review"
            changes, previous = {}, ZERO
            for day, value in sorted(state["daily_net"].items()):
                changes[day] = D(value)-previous
                previous = D(value)
            weeks = defaultdict(lambda: ZERO)
            for day, change in changes.items():
                weeks[datetime.fromisoformat(day).date().isocalendar()[:2]] += change
            chance = luck_probability(list(weeks.values())) if len(weeks) >= 2 else None
            regimes = {regime: {"sessions": 0, "net_after_costs": "0"} for regime in ("benchmark_up", "benchmark_down", "unknown")}
            for turn in turns:
                if not turn.payload.get("questions"):
                    continue
                day = turn.boundary.astimezone(NEW_YORK).date().isoformat()
                labels = turn.payload.get("labels", {})
                regime = "unknown" if len(labels) != len(UNIVERSE) else (
                    "benchmark_up" if sum((D(v["net_after_fees"]) for v in labels.values()), ZERO) > 0 else "benchmark_down")
                row = regimes[regime]
                row["sessions"] += 1
                row["net_after_costs"] = str(D(row["net_after_costs"])+changes.get(day, ZERO))
            state.update(eligible_for_review=gate["eligible_for_review"], current_gate=gate,
                benchmark_net_after_costs=gate["benchmark_net_after_costs"], benchmark_coverage_complete=benchmark_complete,
                model_receipts_complete=receipts_ok, code_identity_unchanged=self.identity_ok(trial),
                calibration=calibration(pairs), decision_counts=dict(decision_counts),
                entry_execution_counts=dict(execution_counts), entry_intents=sum(execution_counts.values()),
                model_latencies_ms=latencies,
                missed_or_skipped_days=sum(t.payload["status"] == "skipped" for t in turns),
                interrupted_turns=sum(t.payload["status"] not in {"complete", "skipped", "error"} for t in turns),
                weekly_luck_p_value=chance, weekly_clusters=len(weeks), regimes=regimes,
                claude_estimated_cost_usd=str(estimated) if kind == "claude" else None,
                claude_unknown_cost_estimates=estimate_unknown if kind == "claude" else None,
                net_after_known_claude_estimated_cost=str(net-estimated) if kind == "claude" and net is not None else None,
                model_requests=len(requests) if kind == "jev" else sum(a.payload.get("arms", {}).get(kind, {}).get("called", False) for a in turns),
                model_actual_cost_usd=str(sum((r.actual_usd or ZERO for r in requests), ZERO)) if kind == "jev" else "0",
                model_reserved_cost_usd=str(sum((r.reserved_usd for r in requests), ZERO)) if kind == "jev" else "0")
            trial.luck_p_value = D(str(chance)) if chance is not None else None
            row = self.session.get(StrategyRow, trial.strategy_id)
            row.config = {**(row.config or {}), "ready_for_live": False,
                          "pipeline_state": "eligible-for-review" if gate["eligible_for_review"] else "paper"}
            self.save(trial, state)
        return {kind: self.state(cohort[kind])["current_gate"] for kind in REAL}

    def tick(self):
        cohort = self.cohort()
        if not cohort:
            return {"status": "waiting_for_admission", "active_arms": 0}
        now, managed_quotes = self.now(), {}
        market = self.market(now)
        if market and market.is_open(now):
            for kind in KINDS[2:]:
                try:
                    self.mark_virtual(self.virtual_books(kind), managed_quotes, market)
                except Exception:
                    self.session.rollback()
                    self.incident(cohort[kind], "ai2_virtual_marks_unavailable")
        for kind in REAL:
            with trial_lock(self.session, cohort[kind].id):
                self.manage(cohort[kind], market, managed_quotes)
        boundary = market.opens_at+ENTRY_OFFSET if market else None
        if market and START <= market.trade_date <= END and now >= boundary:
            with trial_lock(self.session, cohort["jev"].id):
                exists = self.session.scalar(select(JevTurn.id).where(JevTurn.trial_id == cohort["jev"].id,
                                                                      JevTurn.boundary == boundary))
                if not exists:
                    missed = not market.is_open(now) or now >= boundary+ENTRY_WINDOW
                    waiting = not missed and self.state_builder is build_state and not any(
                        load_snapshot(self.session, s, decision_at=self.now(), boundary=boundary) for s in UNIVERSE)
                    if not waiting:
                        try:
                            if not missed:
                                self.refresh_risk()
                            self.decide_daily(cohort, boundary, market, missed=missed)
                        except Exception:
                            self.session.rollback()
                            self.incident(cohort["jev"], "ai2_decision_unavailable")
        if self._last_report is None or self.now()-self._last_report >= timedelta(minutes=1):
            try:
                self.report_cohort(cohort, market)
            except Exception:
                self.session.rollback()
                self.incident(cohort["jev"], "ai2_report_unavailable")
            self._last_report = self.now()
        return {"status": "running" if market and market.is_open(now) else "outside_session",
                "active_arms": len(REAL), "virtual_controls": len(KINDS)-len(REAL),
                "start_date": START.isoformat(), "end_date": END.isoformat(),
                "boundary": boundary.isoformat() if boundary else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true", help="Read-only stored results; no API/model calls")
    args = parser.parse_args(argv)
    with get_engine().connect() as lock, SessionLocal() as session:
        if args.prepare:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            print(json.dumps(prepare(session, git_commit=commit)))
            return
        if args.status:
            rows = session.scalars(select(Trial).where(Trial.code_version == VERSION).order_by(Trial.id))
            print(json.dumps([{ "trial_id": t.id, "status": t.status, "state": (t.metrics or {}).get(NAME, {})}
                              for t in rows], default=str))
            return
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
            raise SystemExit("AI2 paper service already running")
        lock.commit()
        runner = AnalystRunner(session, AlpacaPaperAPI.from_env())
        if not args.once:
            time.sleep(15-time.time()%15)
        try:
            while True:
                try:
                    print(json.dumps({"at": datetime.now(UTC).isoformat(), **runner.tick()}), flush=True)
                except Exception as exc:
                    session.rollback()
                    print(json.dumps({"at": datetime.now(UTC).isoformat(), "status": "unavailable",
                                      "error": type(exc).__name__}), flush=True)
                if args.once:
                    break
                time.sleep(15-time.time()%15)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})


if __name__ == "__main__":
    main()
