"""Selected C05 total-return rule on the existing shared Alpaca paper book.

No historical replay, funding, account reconciliation, issuer approval or invented
corporate-action income. The legacy durable execution state machine is reused.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time as daytime, timedelta
from decimal import Decimal as D
import json
import subprocess
import time
from uuid import uuid4

from sqlalchemy import select, text

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector, PaperGuardContext
from tradingbot.connectors.cash import MarketSession, NEW_YORK, timestamp
from tradingbot.data.alpaca_history import AlpacaHistoryAPI
from tradingbot.data.archive import Request
from tradingbot.data.free_history import YAHOO_CHART
from tradingbot.db.models import Fill, Instrument, Strategy, Trial
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.forward import c05_runner as legacy
from tradingbot.forward.ai_paper_costs import AIPaperCostGuard, account_costs
from tradingbot.forward.c05_readiness import (
    PARAMS as OLD_PARAMS, REACTOR, ROOT, SYMBOLS, ProbeBudget, ReadOnlyPaper,
    capture_http, capture_nontrade, digest, write_once,
)
from tradingbot.forward.c05_sources import price_vintage, read_receipt
from tradingbot.forward.c05_state import NAME, calendar_plan, dump_core, phases, restore_core
from tradingbot.forward.paper_evidence import AccountEvidence, required_instrument_ids
from tradingbot.strategy import MarketSnapshot

VERSION = "c05_total_return_paper_v1"
RESEARCH_VERSION = "cc23e1243ec9fd961e070e9ab83ecf5d7a5461a2eb3bdb9f114f3db73407d686"
SOURCE = "b4654006ee9cf0fbd3451c95300074556de3224d2901e558b73058cd3a0aa088"
PARAMS = {**OLD_PARAMS, "slot_usd": "35", "source_receipt": SOURCE}
PLAN = "docs/research/38-c05-total-return-plan.md"
ARCHIVE = ROOT / "data/forward/c05-total-return"
ZERO = D(0)


def dependencies():
    names = (*legacy.dependencies(), "forward/c05_total_return.py", "forward/ai_paper_costs.py",
             "data/alpaca_history.py", "data/disk_budget.py", "data/free_history.py")
    return {p: digest((ROOT / "src/tradingbot" / p).read_bytes()) for p in names}


def historical_evidence(session):
    """Read-only admission of the committed selected result; never rerun it."""
    if digest((ROOT / "src/tradingbot/strategy/c05_commodity_trend.py").read_bytes()) != REACTOR:
        raise ValueError("Selected reactor changed")
    evidence = []
    for tid, final in ((5385, False), (5401, True)):
        trial = session.get(Trial, tid)
        if (trial is None or trial.mode != "backtest" or trial.status != "complete"
                or trial.strategy_version != RESEARCH_VERSION or trial.final_holdout != final
                or trial.pnl_after_fees is None or trial.pnl_after_fees <= 0
                or any(trial.params.get(k) != v for k, v in {**PARAMS, "slot_usd": "140"}.items())
                or trial.params.get("blackouts") != []):
            raise ValueError("Selected C05 research proof differs")
        evidence.append({"trial_id": tid, "version": trial.strategy_version, "final": final,
            "pnl_after_fees": str(trial.pnl_after_fees), "max_drawdown": str(trial.max_drawdown),
            "trade_count": trial.trade_count, "luck_p_value": str(trial.luck_p_value) if trial.luck_p_value is not None else None})
    return evidence


def new_directory(kind):
    directory = ARCHIVE / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + kind + "-" + uuid4().hex[:10])
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def nontrade_snapshot(connector, sessions, *, since):
    """Sanitized, paginated actual records, from the existing bound account."""
    directory, budget = new_directory("activities"), ProbeBudget()
    api = ReadOnlyPaper.from_env()
    try:
        account = budget.call(api.account)
        connector._account_ok(account)
        if connector._fingerprint(account) != connector._book(connector._venue())["account"]:
            raise ValueError("Activity account differs from existing book")
        result = capture_nontrade(api, directory, timestamp(since), datetime.now(UTC), budget=budget)
    finally:
        api.close()
    result.update(observed_at=datetime.now(UTC).isoformat(), account_matches_book=True)
    return write_once(directory / "activities.json", result)


def capture_prices(connector, sessions):
    """One adjusted-close vintage per fund and independent completed raw marks."""
    began, directory, budget = datetime.now(UTC), new_directory("prices"), ProbeBudget()
    completed = [s for s in sessions if s.closes_at < began]
    if len(completed) < 127:
        raise ValueError("Insufficient calendar warm-up")
    last, start = completed[-1], completed[-127].trade_date
    needed = required_instrument_ids(connector.session, connector.session.scalars(select(Instrument.id).where(
        Instrument.venue_id == connector._venue().id, Instrument.symbol.in_(SYMBOLS))))
    instruments = list(connector.session.scalars(select(Instrument).where(Instrument.id.in_(needed))))
    if any(i.venue_id != connector._venue().id or i.instrument_type != "equity" for i in instruments):
        raise ValueError("Unsupported paper portfolio exposure")
    symbols = sorted(set(SYMBOLS) | {i.symbol for i in instruments})
    api = AlpacaHistoryAPI()
    try:
        raw = budget.call(lambda: api(Request("https://data.alpaca.markets/v2/stocks/bars", {
            "symbols": ",".join(symbols), "timeframe": "1Day", "adjustment": "raw", "feed": "iex",
            "start": last.trade_date.isoformat() + "T00:00:00Z",
            "end": datetime.combine(last.trade_date + timedelta(days=1), daytime.min, NEW_YORK).isoformat(),
            "limit": 10000, "sort": "asc", "asof": "-"})))
        independent = json.loads(raw)
        independent_ref = write_once(directory / "independent.raw", raw.encode(), raw=True)
        if independent.get("next_page_token") is not None:
            raise ValueError("Incomplete independent close page")
    finally:
        api.close()
    for symbol in symbols:
        bars = independent.get("bars", {}).get(symbol, [])
        if len(bars) != 1 or timestamp(bars[0]["t"]).astimezone(NEW_YORK).date() != last.trade_date:
            raise ValueError("Missing completed portfolio close")
    vintage, refs, comparisons = {}, [independent_ref], {}
    boundary = datetime.combine(began.astimezone(NEW_YORK).date() + timedelta(days=1), daytime.min, NEW_YORK)
    params = {"period1": int(datetime.combine(start, daytime.min, NEW_YORK).timestamp()),
              "period2": int(boundary.timestamp()), "interval": "1d", "events": "div,split", "includeAdjustedClose": "true"}
    for symbol in SYMBOLS:
        meta, raw, receipts = capture_http(directory, symbol, YAHOO_CHART.format(symbol=symbol), params=params, budget=budget)
        refs.extend(receipts)
        if meta["status_code"] != 200:
            raise ValueError("Adjusted close source unavailable")
        curve = price_vintage(raw, symbol, sessions, meta["observed_at"])
        reference = D(str(independent["bars"][symbol][0]["c"]))
        if reference <= 0 or curve["last_session"] != str(last.trade_date):
            raise ValueError("Invalid current independent reference")
        difference = abs(D(curve["raw_closes"][-1]) / reference - 1)
        comparisons[symbol] = {"difference": str(difference), "bound": ".01"}
        if difference > D(".01"):
            raise ValueError("Contradictory current raw prices")
        vintage[symbol] = curve
    return write_once(directory / "prices.json", {"vintage": vintage,
        "last_session": str(last.trade_date), "reviewed_at": datetime.now(UTC).isoformat(),
        "watch": {"independent_receipt": independent_ref}, "raw_receipts": refs,
        "comparisons": comparisons, "blackouts": [], "actions": []})


def read_prices(ref, sessions, *, now, close_day=None):
    row = json.loads(read_receipt(ref))
    for source in row["raw_receipts"]:
        read_receipt(source)
    expected = [s.trade_date for s in sessions if s.closes_at < now][-1]
    if (row["last_session"] != str(close_day or expected) or timestamp(row["reviewed_at"]) > now
            or set(row["vintage"]) != set(SYMBOLS)):
        raise ValueError("Source vintage is not the latest completed session")
    return row


@legacy.atomic
def prepare(session, api, *, through, git_commit, now=None, price_source=capture_prices, activity_source=nontrade_snapshot):
    now = timestamp(now or datetime.now(UTC))
    session.execute(text("SELECT pg_advisory_xact_lock(60435, 47)"))
    if session.scalar(select(Trial.id).where(Trial.code_version == VERSION, Trial.status == "running")):
        raise ValueError("Existing C05 paper experiment requires continuation")
    history = historical_evidence(session)
    connector = AlpacaPaperConnector(session, api, now=lambda: now)
    venue, account = connector._venue(), connector._call(api.account)
    connector._account_ok(account)
    book = connector._book(venue)
    if (D(book["initial_cash"]) != 140 or book.get("guard_required") is not None
            or connector._fingerprint(account) != book["account"]):
        raise ValueError("Existing unmodified shared $140 account required")
    costs = account_costs(session, venue.id, now)
    if connector._balance(venue, now).available - costs.total < D(PARAMS["slot_usd"]):
        raise ValueError("Insufficient existing shared cash for selected slot")
    review = (ROOT / PLAN).read_bytes()
    params = {**PARAMS, "historical_evidence": history, "dependencies": dependencies(), "reactor_sha256": REACTOR,
              "review_sha256": digest(review), "blackouts": []}
    row = Strategy(key=VERSION + "-" + uuid4().hex[:12], name="C05 selected 126-session total-return paper",
                   venue_id=venue.id, status="paper", allocation_usd=D(35), config={"ready_for_live": False})
    session.add(row)
    session.flush()
    trial = Trial(strategy_id=row.id, mode="paper", code_version=VERSION, strategy_version=RESEARCH_VERSION,
                  git_commit=git_commit, data_start=now, params=params,
                  metrics={NAME: {"enabled": False, "phases": {}, "incidents": [], "blackouts": [], "core": None}})
    session.add(trial)
    session.commit()  # Failed preparation is still an immutable trial observation.
    tid, stage = trial.id, "calendar"
    try:
        rows = connector._call(api.calendar_range, now.astimezone(NEW_YORK).date() - timedelta(days=400), through + timedelta(days=45))
        plan = calendar_plan(rows, start=now, through=through)
        sessions = [MarketSession.from_api(r) for r in rows]
        current = next((s for s in sessions if s.opens_at <= now < s.closes_at), None)
        if current is not None:
            # Observe today's still-future close; its elapsed opening is missed,
            # never backfilled. Tomorrow therefore has a current close vintage.
            plan["session_dates"] = [str(current.trade_date), *plan["session_dates"]]
        stage = "assets"
        ids = {s: connector.register_equity(s) for s in SYMBOLS}
        stage = "prices"
        source = price_source(connector, sessions)
        read_prices(source, sessions, now=datetime.now(UTC) if price_source is capture_prices else now)
        stage = "broker_records"
        activities = activity_source(connector, sessions, since=now)
        proof = json.loads(read_receipt(activities))
        if not proof["exhausted"] or not proof["account_matches_book"]:
            raise ValueError("Incomplete broker activity observation")
        trial = session.get(Trial, tid)
        trial.params = {**params, **plan, "instrument_ids": ids}
        trial.metrics = {NAME: {"enabled": True, "phases": {}, "incidents": [], "blackouts": [],
            "core": dump_core(restore_core(trial.params, expected_params=PARAMS)), "source_review": source,
            "activation_at": now.isoformat(), "baseline_strategy_pnl": "0", "activity_receipts": [activities],
            "decision": "active_paper_not_ready_for_live", "ready_for_live": False}}
        session.commit()
        return {"trial_id": tid, "strategy_id": row.id, "allocation": "35", "status": "active_paper_not_ready_for_live"}
    except Exception as exc:
        session.rollback()
        trial = session.get(Trial, tid)
        trial.status, trial.completed_ts, trial.trade_count = "failed", now, 0
        trial.metrics = {NAME: {"enabled": False, "failure_stage": stage, "failure_type": type(exc).__name__}}
        session.get(Strategy, trial.strategy_id).allocation_usd = ZERO
        session.commit()
        return {"trial_id": tid, "status": "failed", "stage": stage, "error": type(exc).__name__}


class Runner(legacy.Runner):
    required_guard = None

    def __init__(self, *args, price_source=capture_prices, activity_source=nontrade_snapshot, **kwargs):
        self.price_source, self.activity_source = price_source, activity_source
        super().__init__(*args, **kwargs)
        self.guard = AIPaperCostGuard()

    def trial(self, *, lock=False):
        stmt = select(Trial).where(Trial.id == self.trial_id).execution_options(populate_existing=True)
        trial = self.session.scalar(stmt.with_for_update() if lock else stmt)
        if trial is None or trial.mode != "paper" or trial.code_version != VERSION or trial.status != "running":
            raise ValueError("Running selected C05 paper trial required")
        return trial

    def verify_binding(self, trial):
        if (trial.params["dependencies"] != dependencies() or trial.strategy_version != RESEARCH_VERSION
                or trial.params["reactor_sha256"] != REACTOR
                or trial.params["review_sha256"] != digest((ROOT / PLAN).read_bytes())
                or any(trial.params.get(k) != v for k, v in PARAMS.items())):
            raise ValueError("Frozen C05 paper identity changed")
        phases(trial.params)

    def restore_core(self, params, saved=None):
        return restore_core(params, saved, expected_params=PARAMS)

    def _balances(self):
        venue = self.connector._venue(lock=True)
        costs = account_costs(self.session, venue.id, self.now())
        active = self.connector._orders(venue.id, active=True)
        held = sum((p.cost_basis or ZERO for p in self.connector.ledger.open_positions(
            strategy_id=self.strategy_id, mode="paper")), ZERO)
        pending = sum(((o.size - o.filled_size) * o.limit_price + D(".01")
            for o in active if o.side == "buy" and o.strategy_id == self.strategy_id), ZERO)
        self.transport_cash = self.connector._balance(venue, self.now()).available
        cash = self.transport_cash - costs.total - sum((D(".01") for o in active if o.side == "buy"), ZERO)
        own = (D(PARAMS["slot_usd"]) + self.connector.ledger.realized_after_fees(
            strategy_id=self.strategy_id, mode="paper") - held - pending - costs.by_strategy.get(self.strategy_id, ZERO))
        fills = list(self.session.scalars(select(Fill).where(Fill.trial_id == self.trial_id)))
        self.evidence = AccountEvidence(max(ZERO, cash), {self.strategy_id: max(ZERO, own)},
            {sid: -v for sid, v in costs.by_strategy.items()}, -costs.daily,
            {"policy": VERSION, "additional_cost_usd": str(costs.total), "broker_action_fidelity": False,
             "fees": [{"fill_id": f.id, "actual_fee_usd": str(f.fee),
                       "modeled_fee_usd": str((f.fee or ZERO) + costs.fee_by_fill.get(f.id, ZERO))} for f in fills]})
        self.session.commit()

    def _capture(self, deadline=None):
        self.guard.capture(self.connector, additional=self.ids.values(), valid_until=deadline)
        self.snapshots = {iid: MarketSnapshot(iid, timestamp(q["t"]), bid=D(str(q["bp"])), ask=D(str(q["ap"])))
                          for iid, q in self.guard.quotes.items()}
        self.marks = {iid: q.reference_price for iid, q in self.snapshots.items()}
        self._balances()
        venue = self.connector._venue(lock=True)
        self.connector._refresh_risk(self.guard(self.connector, PaperGuardContext(
            phase="refresh", now=self.now(), venue=venue)), self.now())
        self.session.commit()

    def observe_activities(self):
        ref = self.activity_source(self.connector, self.sessions, since=timestamp(self.trial().params["start"]))
        proof = json.loads(read_receipt(ref))
        if (not proof["exhausted"] or not proof["account_matches_book"]
                or timestamp(proof["observed_at"]) > self.now()):
            raise ValueError("Incomplete or future broker activity observation")
        state = self.state()
        state["activity_receipts"] = [*state.get("activity_receipts", []), ref]
        self.save(state)
        owned = set(self.session.scalars(select(Instrument.symbol).join(Fill).where(Fill.trial_id == self.trial_id)))
        if any(row.get("symbol") in owned for row in proof["c05_records"]):
            self.hold("broker-action", "Actual C05 nontrade record needs attribution before further execution; receipt preserved, no invented credit.")
            raise ValueError("Broker corporate action needs attribution")
        return ref

    def _income(self, admitted):
        # Actual broker records are captured by observe_activities. A synthetic
        # issuer-derived entitlement must never change shares or spendable cash.
        return None

    def admit(self, state, phase_kind, calendar):
        if phase_kind == "close":
            ref = self.price_source(self.connector, self.sessions)
            row = read_prices(ref, self.sessions, now=self.now(), close_day=calendar.trade_date)
            state["source_review"] = ref
            self.save(state)
            self.observe_activities()
            return row
        if self.state().get("preopen_activity_date") != str(calendar.trade_date):
            raise ValueError("No current preopen broker activity observation")
        return read_prices(state["source_review"], self.sessions, now=self.now())

    def step(self):
        self.verify_binding(self.trial())
        now = self.now()
        upcoming = next((s for s in self.sessions if s.opens_at - timedelta(minutes=10) <= now < s.opens_at), None)
        state = self.state()
        if upcoming and state["enabled"] and not state.get("hold") and state.get("preopen_activity_date") != str(upcoming.trade_date):
            try:
                self.observe_activities()
                state = self.state()
                state["preopen_activity_date"] = str(upcoming.trade_date)
                self.save(state)
            except Exception:
                self.session.rollback()
                self.hold("preopen-" + str(upcoming.trade_date), "C05 actual broker activity capture failed before the opening.")
        # Allow vendors one minute to publish a completed daily close. No stale
        # live quote or incomplete bar substitutes for that close observation.
        if any(s.closes_at <= now < s.closes_at + timedelta(minutes=1) for s in self.sessions):
            self._reconcile()
            return "awaiting_completed_close"
        return super().step()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--through", type=date.fromisoformat, default=date(2027, 1, 4))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    api = AlpacaPaperAPI.from_env()
    try:
        with SessionLocal() as session:
            if args.prepare:
                result = prepare(session, api, through=args.through,
                    git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
                print(json.dumps(result), flush=True)
                return
            trials = list(session.scalars(select(Trial.id).where(Trial.code_version == VERSION, Trial.status == "running")))
            if len(trials) != 1:
                raise ValueError("Exactly one admitted C05 paper trial required")
            with get_engine().connect() as lock:
                if not lock.scalar(text("SELECT pg_try_advisory_lock(60434, :trial)"), {"trial": trials[0]}):
                    raise ValueError("C05 already running")
                runner = Runner(session, api, trials[0])
                while True:
                    try:
                        status = runner.step()
                        print(json.dumps({"at": datetime.now(UTC).isoformat(), "trial_id": trials[0], "status": status}), flush=True)
                    except Exception as exc:
                        session.rollback()
                        print(json.dumps({"trial_id": trials[0], "incident": type(exc).__name__}), flush=True)
                        if args.once: raise SystemExit(1) from None
                    else:
                        if status == "complete_requires_fidelity_review": break
                    if args.once: break
                    time.sleep(5)
    finally:
        api.close()


if __name__ == "__main__":
    main()
