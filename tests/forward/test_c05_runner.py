from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.conftest import FakeAPI, isolate_alpaca_venue
from forward.test_c05_state import calendar
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector, NAME as CONNECTOR
from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.db.models import Fill, FxRate, Order, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.forward import c05_runner as r
from tradingbot.forward.c05_state import calendar_plan, dump_core, restore_core
from tradingbot.forward.c05_readiness import PARAMS, REACTOR, SYMBOLS, VERSION
from tradingbot.forward.paper_evidence import NAME as EVIDENCE
from tradingbot.forward import paper_evidence


class FiveAPI(FakeAPI):
    def __init__(self, clock):
        super().__init__(clock)
        self.account_row["cash"] = "1000"
        self.asset_ids = {s: str(uuid4()) for s in SYMBOLS}
        self.rows = calendar()
        self.prices = dict.fromkeys(SYMBOLS, D(100))
        self.quote_calls = 0
    def asset(self, symbol):
        return {**self.asset_row, "id": self.asset_ids[symbol], "symbol": symbol}
    def calendar(self, day):
        return deepcopy([x for x in self.rows if x["date"] == str(day)])
    def calendar_range(self, start, end):
        return deepcopy([x for x in self.rows if str(start) <= x["date"] <= str(end)])
    def quote(self, symbol):
        self.quote_calls += 1
        return {"t": (self.clock[0] - self.quote_age).isoformat(), "bp": str(self.prices[symbol]), "ap": str(self.prices[symbol])}


@pytest.fixture
def setup(monkeypatch):
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(session)
        clock = [timestamp("2026-10-30T20:05:00Z")]
        api = FiveAPI(clock)
        connector = AlpacaPaperConnector(session, api, now=lambda: clock[0])
        ids = {symbol: connector.register_equity(symbol) for symbol in SYMBOLS}
        connector.initialize_cash(D(140))
        venue = connector._venue(lock=True)
        venue.metadata_ = {**venue.metadata_, CONNECTOR: {**venue.metadata_[CONNECTOR], "guard_required": EVIDENCE}}
        strategy = Strategy(key="c05-forward-test-" + uuid4().hex, name="C05 fixture", venue_id=venue.id,
                            status="paper", allocation_usd=D(140))
        session.add(strategy)
        session.flush()
        params = {**PARAMS, **calendar_plan(api.rows, start="2026-10-01T20:50:00Z", through=date(2026, 12, 1)),
                  "instrument_ids": ids, "blackouts": [], "reactor_sha256": REACTOR,
                  "dependencies": r.dependencies(), "source_review": {"path": "fixture-review", "sha256": "a" * 64}}
        state = {"enabled": True, "phases": {}, "incidents": [], "blackouts": [],
                 "source_review": params["source_review"], "core": dump_core(restore_core(params))}
        trial = Trial(strategy_id=strategy.id, mode="paper", code_version=r.NAME, strategy_version=VERSION,
                      params=params, metrics={r.NAME: state})
        session.add_all([trial, FxRate(base="USD", quote="GBP", ts=timestamp("2026-10-29T00:00:00Z"), rate=D(".8"), source="c05-test")])
        session.commit()
        current = {"actions": [], "blackouts": []}
        def admit(ref, sessions, *, as_of, close_day=None):
            now = timestamp(as_of)
            day = str(close_day or now.astimezone(r.NEW_YORK).date())
            curve = {s: {"last_session": day, "adjusted_closes": ["100"] * 126 + ["101"],
                         "raw_closes": ["100"] * 127, "observed_at": now.isoformat()} for s in SYMBOLS}
            return {"reviewed_at": (now - timedelta(minutes=10)).isoformat(), "actions": deepcopy(current["actions"]),
                    "blackouts": deepcopy(current["blackouts"]), "vintage": curve,
                    "watch": {"independent_receipt": {"path": "fixture-independent", "sha256": "b" * 64}}, "review": {}}
        monkeypatch.setattr(r, "admission", admit)
        def raw(ref):
            day = str(clock[0].astimezone(r.NEW_YORK).date())
            return json.dumps({"bars": {s: [{"t": day + "T13:30:00Z", "c": "100"}] for s in SYMBOLS}}).encode()
        monkeypatch.setattr(r, "read_receipt", raw)
        runner = r.Runner(session, api, trial.id, now=lambda: clock[0])
        api.quote_calls = 0
        yield runner, api, clock, current
    finally:
        session.close()
        try:
            assert outer.is_active, "C05 integration tests must remain rollback-only"
            outer.rollback()
        finally:
            connection.close()


def pending(runner, active=SYMBOLS):
    core = restore_core(runner.trial().params, runner.state()["core"])
    core.signals = {s: s in active for s in SYMBOLS}
    core.targets = {s: D("26.6") if s in active else D(0) for s in SYMBOLS}
    core.pending, core.reserve = set(SYMBOLS), D(7)
    core.reasons = dict.fromkeys(SYMBOLS, "monthly rebalance")
    state = runner.state()
    state["core"] = dump_core(core)
    runner.save(state)


def open_at(setup, at="2026-11-02T14:30:00Z", active=SYMBOLS):
    runner, api, clock, current = setup
    pending(runner, active)
    clock[0] = timestamp(at)
    return runner.step()


def fill_all(runner, api, clock, *, side=None):
    clock[0] += timedelta(seconds=1)
    for order in runner.orders():
        if side is None or order.side == side:
            api.fill(order.metadata_["client_order_id"][4:], qty=str(order.size - order.filled_size), price=str(order.limit_price))


def test_construction_and_disabled_preparation_do_not_submit(setup):
    runner, api, _, _ = setup
    assert api.quote_calls == 0 and not api.submissions
    state = runner.state(); state["enabled"] = False; runner.save(state)
    assert runner.step() == "prepared_held"
    assert not api.submissions


def test_actual_monthly_close_freezes_five_targets_and_survives_restart(setup):
    runner, api, clock, _ = setup
    assert runner.step() == "close_observed"
    state = runner.state()
    assert set(state["core"]["targets"].values()) == {"26.60"}
    assert state["core"]["signals"] == dict.fromkeys(SYMBOLS, True)
    assert not api.submissions
    restored = r.Runner(runner.session, api, runner.trial_id, now=lambda: clock[0])
    assert restored.step() == "outside_session"
    assert len(restored.state()["core"]["decisions"]) == 1


def test_five_opening_attempts_are_durable_and_restart_never_repeats_post(setup):
    runner, api, clock, _ = setup
    assert open_at(setup) == "awaiting_buys"
    assert len(api.submissions) == 5
    attempts = runner.state()["phases"]["2026-11-02:open"]["attempts"]
    assert len(attempts) == 5 and all(a["order_id"] for a in attempts.values())
    restored = r.Runner(runner.session, api, runner.trial_id, now=lambda: clock[0])
    assert restored.step() == "awaiting_buys"
    assert len(api.submissions) == 5
    fill_all(restored, api, clock)
    restored.step()
    for attempt in restored.state()["phases"]["2026-11-02:open"]["attempts"].values():
        assert attempt["status"] == "filled" and attempt["fill_receipts"][0]["inside_opening_window"]


def test_unknown_first_post_holds_other_sleeves_and_keeps_cash_reservation(setup):
    runner, api, clock, _ = setup
    api.timeout_submit = True
    open_at(setup)
    assert len(api.submissions) == 1
    assert runner.state()["hold"]
    assert runner.connector.cash().reserved > 0
    restored = r.Runner(runner.session, api, runner.trial_id, now=lambda: clock[0])
    assert restored.step() == "held_for_resolution"
    assert len(api.submissions) == 1


def test_crash_after_reactor_claim_before_connector_never_resends(setup, monkeypatch):
    runner, api, clock, _ = setup
    def crash(*args): raise RuntimeError("simulated crash after durable claim")
    monkeypatch.setattr(runner, "_submit", crash)
    # The first reductions batch is empty; crash only after a nonempty buy claim.
    original = r.Runner._submit
    monkeypatch.setattr(runner, "_submit", lambda key, intents: crash() if intents else original(runner, key, intents))
    with pytest.raises(RuntimeError): open_at(setup)
    assert not api.submissions
    restored = r.Runner(runner.session, api, runner.trial_id, now=lambda: clock[0])
    assert restored.step() == "held_for_resolution"
    assert not api.submissions


def test_reductions_wait_for_all_actual_fills_before_any_buy(setup):
    runner, api, clock, _ = setup
    assert open_at(setup, active={"GLD"}) == "awaiting_buys"
    fill_all(runner, api, clock); runner.step()
    assert open_at(setup, at="2026-11-03T14:30:00Z", active={"SLV"}) == "awaiting_reductions"
    sell = runner.orders()[0]
    assert sell.side == "sell" and len(api.submissions) == 2
    clock[0] += timedelta(seconds=1)
    api.fill(sell.metadata_["client_order_id"][4:], qty=".1")
    assert runner.step() == "awaiting_reductions" and len(api.submissions) == 2
    clock[0] += timedelta(seconds=1)
    api.fill(sell.metadata_["client_order_id"][4:], qty=str(sell.size - D(".1")))
    assert runner.step() == "awaiting_buys"
    assert len(api.submissions) == 3 and api.submissions[-1]["symbol"] == "SLV"


def test_partial_after_window_keeps_inventory_and_holds_new_intents(setup):
    runner, api, clock, _ = setup
    open_at(setup, active={"GLD"})
    order = runner.orders()[0]
    clock[0] += timedelta(seconds=1)
    api.fill(order.metadata_["client_order_id"][4:], qty=".1")
    clock[0] = timestamp("2026-11-02T14:31:00Z")
    assert runner.step() == "held_for_resolution"
    assert runner.ctx.position(runner.ids["GLD"]) == D(".1")
    assert order.status == "partially_filled" and len(api.submissions) == 1


def test_stale_batch_or_source_hold_creates_no_intents(setup, monkeypatch):
    runner, api, clock, _ = setup
    api.quote_age = timedelta(seconds=31)
    # Inside the opening window an unclaimed phase retries instead of holding.
    assert open_at(setup) == "awaiting_opening_marks"
    assert not api.submissions
    assert not any(p.get("attempts") for p in runner.state()["phases"].values())


@pytest.mark.parametrize("delayed_poll", [False, True])
def test_terminal_open_exits_then_completes_flat_without_claiming_fidelity(setup, delayed_poll):
    runner, api, clock, _ = setup
    open_at(setup, active={"GLD"}); fill_all(runner, api, clock); runner.step()
    clock[0] = timestamp("2026-12-01T14:30:00Z")
    runner.session.add(FxRate(base="USD", quote="GBP", ts=clock[0]-timedelta(days=1), rate=D(".8"), source="terminal-test"))
    runner.session.commit()
    assert runner.step() == "awaiting_reductions"
    assert len(api.submissions) == 2 and api.submissions[-1]["side"] == "sell"
    fill_all(runner, api, clock)
    if delayed_poll:
        # The execution was timely; discovery after the window must still
        # finish a flat terminal phase without placing another order.
        clock[0] += timedelta(minutes=2)
    assert runner.step() == "complete_requires_fidelity_review"
    trial = runner.session.get(Trial, runner.trial_id)
    assert trial.status == "complete" and trial.trade_count == 2
    assert trial.pnl_after_fees == D("-.04")
    assert not trial.metrics[r.NAME]["ready_for_live"]
    assert not trial.metrics[r.NAME]["action_fidelity_established"]


def test_failed_source_preparation_is_recorded_zero_trade_null_metrics(setup, monkeypatch):
    runner, api, clock, _ = setup
    strategy_id = runner.strategy_id
    trial = runner.trial(); trial.status = "failed"; runner.session.commit()
    monkeypatch.setattr(r, "historical_evidence", lambda session: {"rows": [{"strategy_id": strategy_id}], "replayed": False})
    def denied(*args, **kwargs): raise ValueError("source admission held")
    monkeypatch.setattr(r, "admission", denied)
    result = r.prepare(runner.session, api, through=date(2026,12,1), review_ref={}, commit="test", now=clock[0])
    failed = runner.session.get(Trial, result["trial_id"])
    assert result["status"] == "failed" and result["failure_stage"] == "source_admission"
    assert failed.trade_count == 0 and failed.pnl_after_fees is None and failed.fees_total is None
    assert not api.submissions


def forced_plan(runner, current):
    plan = {"symbol": "GLD", "identity": "fixture-split", "decision": "2026-11-02", "exit": "2026-11-03", "reentry": "2026-11-05"}
    current["blackouts"] = [plan]
    state = runner.state()
    state["blackouts"] = [plan]
    state["core"]["causal_exits"] = [["GLD", "2026-11-03"]]
    state["core"]["targets"]["GLD"] = "0"
    state["core"]["pending"] = ["GLD"]
    state["core"]["reasons"]["GLD"] = "forced blackout exit"
    state["phases"]["2026-11-02:close"] = {"status": "complete", "attempts": {}, "phase": "close"}
    runner.save(state)


def test_risk_vetoed_forced_exit_remains_owned_and_is_logged(setup):
    runner, api, clock, current = setup
    open_at(setup, active={"GLD"}); fill_all(runner, api, clock); runner.step()
    forced_plan(runner, current)
    clock[0] = timestamp("2026-11-03T14:30:00Z")
    runner.connector.risk.trigger_daily_halt("paper", D(-50), clock[0])
    runner.session.commit()
    runner.step()
    assert runner.state()["hold"]
    attempt = next(iter(runner.state()["phases"]["2026-11-03:open"]["attempts"].values()))
    assert attempt["mandatory_exit"] and attempt["status"] == "OrderRejected"
    assert runner.ctx.position(runner.ids["GLD"]) == D(".266")
    assert len(api.submissions) == 1


def test_forced_dust_never_becomes_flat_or_a_fabricated_fill(setup):
    runner, api, clock, current = setup
    clock[0] = timestamp("2026-11-02T14:30:00Z")
    order = runner.connector.ledger.record_order(instrument_id=runner.ids["GLD"], strategy_id=runner.strategy_id,
        trial_id=runner.trial_id, mode="paper", side="buy", order_type="limit", size=D(".005"), limit_price=D(100),
        metadata={"connector": CONNECTOR, "client_order_id": "fixture-dust"})
    runner.connector.ledger.record_fill(order=order, price=D(100), size=D(".005"), fee=D(0), fill_ts=clock[0],
        usd_gbp_rate=D(".8"), liquidity="unknown", venue_fill_id="fixture-dust-fill",
        metadata={"connector": CONNECTOR, "settlement_date": "2026-11-03"})
    runner.session.commit()
    forced_plan(runner, current)
    clock[0] = timestamp("2026-11-03T14:30:00Z")
    assert runner.step() == "held_for_resolution"
    assert runner.ctx.position(runner.ids["GLD"]) == D(".005")
    assert not api.submissions
    assert len(list(runner.session.scalars(select(Fill).where(Fill.trial_id == runner.trial_id)))) == 1


def activation_decision(trial_id, now):
    return {"decision": "activate_paper", "trial_id": trial_id, "promotion_checklist_complete": True,
            "account_integration_verified": True, "reviewed_at": now.isoformat(),
            "what_could_blow_up_this_account": "Synthetic fixture review: commodity gaps, spreads, source delays, omitted fees and unverified share conversions can cause losses. " * 2}


def test_activation_without_account_migration_cannot_change_allocation(setup, monkeypatch):
    runner, api, clock, _ = setup
    state = runner.state(); state["enabled"] = False; runner.save(state)
    strategy = runner.session.get(Strategy, runner.strategy_id)
    strategy.status, strategy.allocation_usd = "backtest", D(0)
    venue = runner.connector._venue(lock=True)
    venue.metadata_ = {**venue.metadata_, CONNECTOR: {k: v for k, v in venue.metadata_[CONNECTOR].items() if k != "guard_required"}}
    runner.session.commit()
    monkeypatch.setattr(r, "read_receipt", lambda ref: json.dumps(activation_decision(runner.trial_id, clock[0])).encode())
    with pytest.raises(ValueError, match="migration"):
        r.activate(runner.session, api, runner.trial_id, decision_ref={}, now=clock[0])
    assert strategy.allocation_usd == 0 and strategy.status == "backtest"
    assert not runner.state()["enabled"] and not api.submissions


def test_activation_queues_income_before_ex_and_failed_late_schedule_rolls_back(setup, monkeypatch):
    runner, api, clock, current = setup
    state = runner.state(); state["enabled"] = False; runner.save(state)
    strategy = runner.session.get(Strategy, runner.strategy_id)
    strategy.status, strategy.allocation_usd = "backtest", D(0)
    runner.session.commit()
    monkeypatch.setattr(paper_evidence, "receipt", lambda ref: b"fixture issuer source")
    monkeypatch.setattr(r, "read_receipt", lambda ref: json.dumps(activation_decision(runner.trial_id, clock[0])).encode())
    event = {"symbol": "DBA", "kind": "ordinary_cash", "currency": "USD", "ex_date": "2026-10-30",
             "payable_date": "2026-11-03", "amount_per_share": ".5", "observed_at": "2026-10-29T14:00:00Z",
             "reviewed_at": "2026-10-29T15:00:00Z", "source_receipt": {"path": "fixture", "sha256": "a" * 64}}
    current["actions"] = [event]
    with pytest.raises(ValueError, match="before ex-open"):
        r.activate(runner.session, api, runner.trial_id, decision_ref={}, now=clock[0])
    assert strategy.allocation_usd == 0 and strategy.status == "backtest"
    current["actions"] = [{**event, "ex_date": "2026-11-02"}]
    r.activate(runner.session, api, runner.trial_id, decision_ref={}, now=clock[0])
    assert strategy.allocation_usd == 140 and runner.state()["enabled"]
    venue = runner.connector._venue()
    assert len(venue.metadata_[EVIDENCE]["scheduled_income"]) == 1
    assert venue.metadata_[CONNECTOR]["initial_cash"] == "140" and not api.submissions


def test_source_failure_before_monthly_decision_preserves_empty_reactor(setup, monkeypatch):
    runner, api, _, _ = setup
    before = runner.state()["core"]
    def denied(*args, **kwargs): raise ValueError("unresolved issuer notice")
    monkeypatch.setattr(r, "admission", denied)
    assert runner.step() == "held_for_resolution"
    assert runner.state()["core"] == before and not api.submissions


def test_missing_documented_completion_cannot_be_inferred_from_fill_label(setup, monkeypatch):
    runner, _, clock, _ = setup
    monkeypatch.setattr(r, "read_receipt", lambda ref: json.dumps({"kind": "nominal_t1"}).encode())
    with pytest.raises(ValueError, match="Documented"):
        r.record_completion(runner.session, runner.trial_id, {}, now=clock[0])
