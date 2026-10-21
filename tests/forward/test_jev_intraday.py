"""Real Postgres and connector execution with fake HTTP/model; no paid calls."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from connectors.conftest import FakeAPI, isolate_alpaca_venue
from tradingbot.ai.jev import (JevDecision, MODEL_ID, INPUT_PRICE_PER_MILLION, PRICING_VERSION, _validate_questions,
                               within_token_limits)
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector
from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, Incident, Instrument, JevRequest, JevTurn, Order, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.forward.ai import evidence_gate
from tradingbot.data.iex_intraday import SYMBOLS
from tradingbot.forward.jev_intraday import (NAME, Runner, SettledQuotes, due_boundary, prepare, request_batch,
                                            request_batches, update_readiness)
from tradingbot.strategy.jev import DecisionSpec, JevStrategy, Plan, Target
from tradingbot.strategy.registry import register


DEPLOYED_KEYS = ("jev_j1_gate", "jev-j2-menu-v1", "jev_j3_news", "jev_j4_regime")


@register
class FixtureStrategy(JevStrategy):
    key = "jev-intraday-integration-fixture"
    arm = "J1"
    ungated_twin = True

    def plan(self, view):
        if "SPY" not in view.states or "SPY" in view.positions or "SPY" in view.entered_today:
            return Plan(memory={"seen": view.boundary.isoformat()})
        return Plan((DecisionSpec("spy-entry", {"go": {"type": "noul", "instructions": "Enter SPY?"}},
            {"skip": (), "enter": (Target("SPY", D(".8"), D(2)),)}, baseline="enter"),),
            memory={"seen": view.boundary.isoformat()})

    def choose(self, spec, answers):
        return "enter" if answers["go"]["noul"] >= .6 else "skip"


class Model:
    def __init__(self, session, clock):
        self.session, self.clock = session, clock
        self.calls = []
        self.unavailable = False
        self.probability = .9
        self.after_call = lambda: None
        self.model_id = MODEL_ID

    def decide(self, **kwargs):
        at = self.clock[0]
        self.calls.append(deepcopy(kwargs))
        self.after_call()
        if self.unavailable:
            return None
        request_id = str(uuid4())
        answers = {k: {"type": "noul", "noul": self.probability} for k in kwargs["questions"]}
        self.session.add(JevRequest(id=request_id, started_ts=at, completed_ts=self.clock[0],
            billing_month=at.date().replace(day=1), completed_month=self.clock[0].date().replace(day=1),
            correlation_id=kwargs["correlation_id"], questions=kwargs["questions"], answers=answers,
            requested_model=kwargs["model"], model_id=self.model_id, status="ok", actual_usd=D(0),
            reserved_usd=D(0), input_price_per_million=INPUT_PRICE_PER_MILLION,
            pricing_version=PRICING_VERSION, latency_ms=1, outcomes={}))
        self.session.commit()
        return JevDecision(request_id, self.model_id, answers, D(0), 1)


@pytest.fixture
def setup():
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(session)
        # Admission's arm and strategy-key uniqueness is global. Hide deployed
        # cohorts only in this rollback transaction so tests survive admission.
        session.execute(update(Trial).where(Trial.code_version == NAME)
                        .values(code_version="test-hidden-"+uuid4().hex))
        session.execute(update(Strategy).where(Strategy.key.in_(DEPLOYED_KEYS))
                        .values(key=Strategy.key+"-test-hidden-"+uuid4().hex[:8]))
        clock = [timestamp("2026-09-30T14:01:00Z")]
        api = FakeAPI(clock)
        raw_quote = api.quote
        api.quote = lambda symbol: {**raw_quote(symbol), "bs": 1, "as": 1}
        connector = AlpacaPaperConnector(session, api, now=lambda: clock[0])
        iid = connector.register_equity("SPY")
        connector.initialize_cash(D(100))
        venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
        row = Strategy(key=FixtureStrategy.key, name="Jev fixture", venue_id=venue.id,
                       status="paper", allocation_usd=D(25), config={})
        session.add_all([row, FxRate(base="USD", quote="GBP", ts=clock[0]-timedelta(days=1),
                                   rate=D(".8"), source="fixture")])
        session.commit()
        # Use a genuine repository risk checklist without changing any real plan.
        trial_id = prepare(session, FixtureStrategy(), review_record="docs/promotion-checklist.md",
                           git_commit="test", now=clock[0])
        model = Model(session, clock)
        def state_builder(session, symbol, *, decision_at, boundary):
            return {"symbol": symbol, "boundary": boundary.isoformat(), "features": {},
                    "news": {"untrusted": True, "items": []}} if symbol == "SPY" else None
        runner = Runner(session, api, model=model, now=lambda: clock[0], state_builder=state_builder)
        yield session, runner, api, model, clock, session.get(Trial, trial_id), iid
    finally:
        session.close()
        try:
            assert outer.is_active
            outer.rollback()
        finally:
            connection.close()


def turn(setup):
    session, runner, _, _, clock, trial, _ = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    result = runner.decide(trial, FixtureStrategy(), boundary, observation, market)
    return result, session.scalar(select(JevTurn).where(JevTurn.trial_id == trial.id).order_by(JevTurn.id.desc()))


def test_real_orders_and_virtual_fills_are_separate_and_turn_is_idempotent(setup):
    session, runner, api, model, _, trial, _ = setup
    result, row = turn(setup)
    assert result and row.payload["status"] == "complete"
    assert len(api.submissions) == len(model.calls) == 1
    assert api.submissions[0]["side"] == "buy"
    assert model.calls[0]["model"] == "jev-latest"
    assert model.calls[0]["correlation_id"].startswith(f"paper-trial:{trial.id}:")
    observation = row.payload["observation"]
    assert observation["states"]["SPY"]["execution_quote"] == observation["quotes"]["SPY"]
    all_ids = [trial.id, *runner.state(trial)["twins"].values()]
    assert session.scalar(select(Fill.id).where(Fill.trial_id.in_(all_ids))) is None
    for tid in runner.state(trial)["twins"].values():
        twin = session.get(Trial, tid)
        assert len(runner.state(twin)["book"]["fills"]) == 1
    assert not turn(setup)[0]
    assert len(api.submissions) == len(model.calls) == 1


def test_model_outage_holds_real_and_random_but_preserves_ungated_control(setup):
    session, runner, api, model, _, trial, _ = setup
    model.unavailable = True
    assert turn(setup)[0]
    assert not api.submissions
    twins = runner.state(trial)["twins"]
    assert not runner.state(session.get(Trial, twins["random"]))["book"]["fills"]
    assert len(runner.state(session.get(Trial, twins["ungated"]))["book"]["fills"]) == 1


@pytest.mark.parametrize("outcome", ["bullish", "neutral", "unavailable"])
def test_j3_typed_headlines_persist_consumption_and_route_only_passing_real_and_random(setup, outcome):
    from tradingbot.strategy.jev_j3 import J3NewsReactor
    session, runner, api, model, clock, _, _ = setup
    params = {"news_start_at": "2026-09-30T13:30:00Z"}
    core = J3NewsReactor(params)
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    row = Strategy(key=core.key, name="J3 integration", venue_id=venue.id,
                   status="paper", allocation_usd=D(25), config={"params": params})
    session.add(row)
    session.commit()
    trial_id = prepare(session, core, review_record="docs/research/jev-j3-news-plan.md",
                       git_commit="test", now=clock[0])
    trial = session.get(Trial, trial_id)
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    state = observation["states"]["SPY"]
    state.update(features={"atr14": "2"}, quality={"complete_suffix_intervals": 15},
                 events={"collection_halted": False},
                 news={"status": "ok", "untrusted": True, "items": [{"id": "j3-news",
                     "created_at": (boundary-timedelta(minutes=10)).isoformat(),
                     "updated_at": (boundary-timedelta(minutes=10)).isoformat(),
                     "known_at": (boundary-timedelta(minutes=9)).isoformat(),
                     "headline": "A new economic outlook"}]})

    def typed_decide(**kwargs):
        model.calls.append(deepcopy(kwargs))
        if outcome == "unavailable":
            return None
        answers = {}
        for key, q in kwargs["questions"].items():
            if q["type"] == "choice":
                answers[key] = {"type": "choice", "choice": outcome, "confidence": 1,
                                "probabilities": {k: int(k == outcome) for k in q["criteria"]}}
            elif q["type"] == "score":
                answers[key] = {"type": "score", "score": 3, "confidence": 1,
                                "probabilities": {str(i): int(i == 3) for i in range(5)},
                                "legend": {str(i): c for i, c in enumerate(q["criteria"])}}
            else:
                answers[key] = {"type": "noul", "noul": 1}
        request_id = str(uuid4())
        session.add(JevRequest(id=request_id, started_ts=clock[0], completed_ts=clock[0],
            billing_month=clock[0].date().replace(day=1), completed_month=clock[0].date().replace(day=1),
            correlation_id=kwargs["correlation_id"], questions=kwargs["questions"], answers=answers,
            requested_model=kwargs["model"], model_id=MODEL_ID, status="ok", actual_usd=D(0),
            reserved_usd=D(0), input_price_per_million=INPUT_PRICE_PER_MILLION,
            pricing_version=PRICING_VERSION, latency_ms=1, outcomes={}))
        session.commit()
        return JevDecision(request_id, MODEL_ID, answers, D(0), 1)

    model.decide = typed_decide
    assert runner.decide(trial, core, boundary, observation, market)
    assert len(model.calls) == 1 and len(model.calls[0]["questions"]) == 3
    assert bool(api.submissions) is (outcome == "bullish")
    if api.submissions:
        assert api.submissions[0]["side"] == "buy"
        assert runner.state(trial)["stops"]["SPY"] == "3.0"
    twins = runner.state(trial)["twins"]
    assert set(twins) == {"random"}
    control = runner.state(session.get(Trial, twins["random"]))
    assert bool(control["book"]["fills"]) is (outcome == "bullish")
    assert runner.state(trial)["memory"]["news_revisions"]["SPY"]
    clock[0] += timedelta(minutes=15)
    observation["at"] = clock[0].isoformat()
    assert runner.decide(trial, core, boundary+timedelta(minutes=15), observation, market)
    assert len(model.calls) == 1  # no stale replay after a skip or model outage


@pytest.mark.parametrize("cause", ["expired", "wrong_model"])
def test_fresh_order_quote_cannot_rescue_expired_or_unpinned_decision(setup, cause):
    _, _, api, model, clock, _, _ = setup
    if cause == "expired":
        model.after_call = lambda: clock.__setitem__(0, clock[0]+timedelta(seconds=31))
    else:
        model.model_id = "jev-next-unreviewed"
    assert turn(setup)[0]
    assert not api.submissions


def test_uncertain_post_is_reserved_and_never_submitted_again(setup):
    session, runner, api, _, clock, trial, _ = setup
    api.timeout_submit = True
    assert turn(setup)[0]
    assert len(api.submissions) == 1
    assert runner.state(trial)["entries"]["2026-09-30"]["SPY"]
    clock[0] += timedelta(minutes=15)
    assert turn(setup)[0]
    assert len(api.submissions) == 1
    assert len(runner.orders(trial)) == 1
    assert session.scalar(select(Order.id).where(Order.trial_id == trial.id))


def test_constructor_never_calls_broker_or_model(setup):
    session, _, api, model, clock, _, _ = setup
    def forbidden(*a, **kw):
        raise AssertionError("startup I/O")
    for name in ("account", "order", "activities", "quote", "calendar"):
        setattr(api, name, forbidden)
    Runner(session, api, model=model, now=lambda: clock[0])
    assert not model.calls


def fill_entry(setup, qty=None):
    session, runner, api, _, clock, trial, _ = setup
    turn(setup)
    order = runner.orders(trial)[0]
    qty = str(order.size) if qty is None else qty
    clock[0] += timedelta(seconds=1)
    api.fill(order.metadata_["client_order_id"].removeprefix("tbp-"), qty=qty)
    runner.guard.capture(runner.connector)
    runner.connector.refresh(order.id)
    return order


def test_close_exit_runs_with_model_unavailable_and_keeps_actual_fill_ledger(setup):
    session, runner, api, model, clock, trial, _ = setup
    fill_entry(setup)
    assert len(runner.positions(trial)) == 1
    model.unavailable = True
    clock[0] = timestamp("2026-09-30T19:55:00Z")
    runner.manage(trial, runner.market(clock[0]))
    assert [s["side"] for s in api.submissions] == ["buy", "sell"]
    sell = runner.orders(trial)[0]
    clock[0] += timedelta(seconds=1)
    api.fill(sell.metadata_["client_order_id"].removeprefix("tbp-"), qty=str(sell.size))
    runner.manage(trial, runner.market(clock[0]))
    assert not runner.positions(trial)
    assert len(list(session.scalars(select(Fill).where(Fill.trial_id == trial.id)))) == 2
    assert runner.connector.cash().unsettled == D(20)


def test_partial_entry_is_canceled_before_close_residual_is_sold(setup):
    _, runner, api, model, clock, trial, _ = setup
    fill_entry(setup, qty=".05")
    model.unavailable = True
    clock[0] = timestamp("2026-09-30T19:55:00Z")
    runner.manage(trial, runner.market(clock[0]))
    assert api.cancellations
    assert api.submissions[-1]["side"] == "sell" and D(api.submissions[-1]["qty"]) == D(".05")


def test_stop_is_code_owned_and_risk_kill_remains_absolute(setup):
    session, runner, api, _, clock, trial, _ = setup
    fill_entry(setup)
    api.quote = lambda symbol: {"bp": "97", "ap": "97", "bs": 1, "as": 1, "t": clock[0].isoformat()}
    runner.manage(trial, runner.market(clock[0]))
    assert api.submissions[-1]["side"] == "sell"
    # No new order is allowed after a strategy kill, including close exits.
    row = session.get(Strategy, trial.strategy_id)
    row.status = "killed"
    session.commit()
    n = len(api.submissions)
    clock[0] = timestamp("2026-09-30T19:55:00Z")
    runner.manage(trial, runner.market(clock[0]))
    assert len(api.submissions) == n


def test_residual_after_close_is_an_incident_not_a_fabricated_flat(setup):
    session, runner, api, _, clock, trial, _ = setup
    fill_entry(setup)
    clock[0] = timestamp("2026-09-30T20:01:00Z")
    runner.manage(trial, runner.market(clock[0]))
    assert runner.positions(trial)
    assert "residual_exposure_after_close" in runner.state(trial)["integrity_errors"]
    assert session.scalar(select(Incident.id).where(Incident.strategy_id == trial.strategy_id))
    assert len(api.submissions) == 1


def test_early_close_and_nontrading_day_schedule(setup):
    _, runner, _, _, clock, _, _ = setup
    market = runner.market(clock[0])
    early = type(market)(market.trade_date, market.settlement_date, market.opens_at, market.closes_at-timedelta(hours=3))
    assert due_boundary(timestamp("2026-09-30T16:54:59Z"), early)
    assert due_boundary(timestamp("2026-09-30T16:55:00Z"), early) is None
    assert due_boundary(market.opens_at+timedelta(minutes=14), market) is None
    assert runner.market(timestamp("2026-10-03T14:00:00Z")) is None


def test_failed_admission_is_logged_without_resetting_shared_cash(setup):
    session, runner, _, _, clock, trial, _ = setup
    row = session.get(Strategy, trial.strategy_id)
    row.allocation_usd = D(26)
    session.commit()
    with pytest.raises(ValueError, match="quarter"):
        prepare(session, FixtureStrategy(), review_record="docs/promotion-checklist.md", git_commit="test", now=clock[0])
    assert session.scalar(select(Trial.id).where(Trial.strategy_id == row.id, Trial.status == "failed"))
    assert runner.connector._book(runner.connector._venue())["initial_cash"] == "100"


def test_crash_claim_is_not_replayed_and_cannot_qualify(setup):
    session, runner, api, model, clock, trial, _ = setup
    boundary = due_boundary(clock[0], runner.market(clock[0]))
    session.add(JevTurn(trial_id=trial.id, boundary=boundary, observed_at=clock[0],
                        payload={"status": "deciding", "batches": [{"status": "pending"}]}))
    session.commit()
    assert not turn(setup)[0]
    assert not api.submissions and not model.calls
    assert "evidence_requires_review" in runner.report(trial)["reasons"]


def test_report_includes_real_cost_receipts_and_keeps_virtuals_ineligible(setup):
    session, runner, _, _, _, trial, _ = setup
    turn(setup)
    gate = runner.report(trial)
    state = runner.state(trial)
    assert state["model_receipts_complete"] and state["code_identity_unchanged"]
    assert state["model_requests"] == 1 and state["mean_model_latency_ms"] == 1
    assert not gate["eligible_for_review"] and trial.status == "running"
    for tid in state["twins"].values():
        assert runner.state(session.get(Trial, tid))["ready_for_live"] is False


def test_cancel_ack_does_not_allow_close_order_until_entry_resolved(setup):
    _, runner, api, _, clock, trial, _ = setup
    fill_entry(setup, qty=".05")
    api.cancel_ack_only = True
    clock[0] = timestamp("2026-09-30T19:55:00Z")
    runner.manage(trial, runner.market(clock[0]))
    assert len(api.submissions) == 1
    assert runner.orders(trial)[0].status == "partially_filled"


def test_gap_or_feed_halt_blocks_entry_even_if_model_says_enter(setup):
    _, runner, api, _, clock, trial, _ = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    observation["states"]["SPY"]["quality"] = {"complete_suffix_intervals": 0}
    assert runner.decide(trial, FixtureStrategy(), boundary, observation, market)
    assert not api.submissions


class BatchStrategy(FixtureStrategy):
    def plan(self, view):
        return Plan(tuple(DecisionSpec(str(i), {f"q{j}": {"type": "noul", "instructions": "Gate?"} for j in range(5)},
            {"skip": (), "enter": (Target("SPY", D(".1")),)}) for i in range(27)))

    def choose(self, spec, answers):
        assert len(answers) == 5
        return "skip"


@pytest.mark.parametrize("include_news", [True, False])
def test_batched_question_mapping_respects_128_limit_and_one_observation(setup, monkeypatch, include_news):
    _, runner, api, model, clock, trial, _ = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    observation["states"]["SPY"]["source_receipts"] = {"large_audit": "x"*270000}
    observation["states"]["SPY"]["news"]["items"] = [{"headline": "raw external text"}]
    monkeypatch.setattr(BatchStrategy, "include_news", include_news)
    assert runner.decide(trial, BatchStrategy(), boundary, observation, market)
    assert [len(c["questions"]) for c in model.calls] == [125, 10]
    assert model.calls[0]["state"]["observations"] == model.calls[1]["state"]["observations"]
    assert "source_receipts" not in model.calls[0]["state"]["observations"]["SPY"]
    assert ("news" in model.calls[0]["state"]["observations"]["SPY"]) is include_news
    assert observation["states"]["SPY"]["news"]["items"] == [{"headline": "raw external text"}]
    assert not api.submissions


@pytest.mark.parametrize("days,trades,net,eligible", [
    (6, 30, "1", False), (7, 29, "1", False), (7, 30, "0", False), (7, 30, ".001", True),
])
def test_queue_requires_all_three_owner_evidence_conditions(days, trades, net, eligible):
    start = timestamp("2026-10-02T14:00:00Z")
    now = start+timedelta(days=days)
    gate = evidence_gate(started_at=start, observed_at=now, trade_count=trades, net_pnl=D(net),
                         flat=True, pending=False, integrity_ok=True)
    state = update_readiness({}, gate, now, flat=True)
    assert state["ready_for_live"] is eligible
    assert gate["automatic_promotion"] is False  # queue only; never live orders


def test_queued_arm_keeps_running_and_is_rejudged_weekly():
    now = timestamp("2026-10-09T20:00:00Z")
    good = {"eligible_for_review": True, "reasons": []}
    state = update_readiness({}, good, now, flat=True)
    negative = {"eligible_for_review": False, "reasons": ["not_profitable_after_costs"]}
    assert update_readiness(state, negative, now+timedelta(days=1), flat=True)["ready_for_live"]
    assert not update_readiness(state, negative, now+timedelta(days=7), flat=True)["ready_for_live"]
    halted = {"eligible_for_review": False, "reasons": ["evidence_requires_review"]}
    assert not update_readiness(state, halted, now+timedelta(minutes=1), flat=False)["ready_for_live"]


def test_official_transport_batches_only_the_free_iex_feed():
    api = AlpacaPaperAPI.__new__(AlpacaPaperAPI)
    captured = []
    api._data = SimpleNamespace(get_stock_latest_quote=lambda request: captured.append(request) or {"SPY": {}})
    assert api.quotes(["SPY", "SPY", "QQQ"]) == {"SPY": {}}
    assert captured[0].symbol_or_symbols == ["QQQ", "SPY"]
    assert captured[0].feed.value == "iex"
    assert api.quotes([]) == {} and len(captured) == 1


def test_batched_observation_and_complete_portfolio_guard(setup):
    _, runner, api, _, clock, _, iid = setup
    calls = []
    one = api.quote
    api.quotes = lambda symbols: calls.append(list(symbols)) or {s: one(s) for s in symbols}
    market = runner.market(clock[0])
    observation = runner.observation(due_boundary(clock[0], market), market)
    assert set(observation["quotes"]) == {"SPY"} and calls == [["SPY"]]
    runner.guard.capture(runner.connector, additional=[iid])
    assert calls == [["SPY"], ["SPY"]]
    api.quotes = lambda symbols: {}
    with pytest.raises(KeyError):
        runner.guard.capture(runner.connector, additional=[iid])
    assert runner.guard.quotes is None  # incomplete batch cannot retain old evidence


def test_quote_receipt_after_feature_cutoff_preserves_original_deadline(setup):
    _, runner, api, _, clock, _, _ = setup
    feature_at = clock[0]
    market = runner.market(feature_at)
    raw_quote = api.quote
    def late_quotes(symbols):
        clock[0] += timedelta(seconds=2)
        return {symbol: raw_quote(symbol) for symbol in symbols}
    api.quotes = late_quotes
    observation = runner.observation(due_boundary(feature_at, market), market)
    state = observation["states"]["SPY"]
    assert timestamp(observation["at"]) == feature_at
    assert timestamp(state["execution_quote"]["t"]) == clock[0]
    assert timestamp(state["execution_quote_observed_at"]) == clock[0]
    assert timestamp(observation["deadline"]) == feature_at+timedelta(seconds=30)


@pytest.mark.parametrize("failure", ["plan", "execute"])
def test_virtual_failure_cannot_block_real_orders_or_taint_real_evidence(setup, monkeypatch, failure):
    _, runner, api, _, _, trial, _ = setup
    if failure == "plan":
        original = runner.view
        def view(participant, *args):
            if runner.state(participant)["virtual"]:
                raise ValueError("unavailable diagnostic view")
            return original(participant, *args)
        monkeypatch.setattr(runner, "view", view)
    else:
        def execute(*args):
            raise ValueError("unavailable diagnostic execution")
        monkeypatch.setattr(runner, "_virtual_execute", execute)
    assert turn(setup)[0]
    assert len(api.submissions) == 1 and not runner.state(trial)["integrity_errors"]


class SizedStrategy(FixtureStrategy):
    def plan(self, view):
        plan = super().plan(view)
        return Plan(tuple(DecisionSpec(s.key, s.questions, s.alternatives, baseline=s.baseline,
                        minimum_size_factor=D(".5")) for s in plan.decisions), plan.memory)

    def size_factor(self, spec, answers):
        return D(self.params.get("factor", ".75"))


@pytest.mark.parametrize("factor,quantity", [(".75", D(".15")), ("2", None)])
def test_code_sizing_applies_exact_factor_within_predeclared_ceiling(setup, factor, quantity):
    session, runner, api, _, clock, trial, _ = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    result = runner.decide(trial, SizedStrategy({"factor": factor}), boundary, observation, market)
    if quantity is None:
        assert not result and not api.submissions
    else:
        assert result and D(api.submissions[0]["qty"]) == quantity
        turn = session.scalar(select(JevTurn).where(JevTurn.trial_id == trial.id))
        proof = turn.payload["costs"]["real"]["spy-entry"]["enter"]["SPY"]
        assert D(proof["minimum_quantity"]) == D(".1")
        assert D(proof["quantity"]) == D(".2")


def test_stale_quote_outside_the_turn_does_not_expire_it(setup):
    # 2026-10-05: one 25s-old quote elsewhere in the universe left every arm 5s.
    _, runner, api, model, clock, _, _ = setup
    one = api.quote
    api.quote = lambda symbol: {**one(symbol), **(
        {"t": (clock[0]-timedelta(seconds=25)).isoformat()} if symbol == "UNG" else {})}
    runner.state_builder = lambda session, symbol, *, decision_at, boundary: (
        {"symbol": symbol, "boundary": boundary.isoformat(), "features": {},
         "news": {"untrusted": True, "items": []}} if symbol in ("SPY", "UNG") else None)
    model.after_call = lambda: clock.__setitem__(0, clock[0]+timedelta(seconds=10))
    result, row = turn(setup)
    observation = row.payload["observation"]
    assert result and set(observation["quotes"]) == {"SPY", "UNG"}
    assert timestamp(observation["deadline"]) == timestamp(observation["at"])+timedelta(seconds=5)
    assert timestamp(row.payload["deadline"]) == timestamp(observation["at"])+timedelta(seconds=30)
    assert row.payload["batches"][0]["status"] == "ok" and len(api.submissions) == 1
    assert set(model.calls[0]["state"]["observations"]) == {"SPY"}


def test_calls_carry_only_their_decisions_scope_and_split_to_fit_jev_limits():
    # 2026-10-05: all 40 observations (76 KB) went with every call, and Jev
    # refused every J1/J3/J4 request with max_tokens_exceeded.
    observed = {s: {"symbol": s, "features": {"pad": "7"*3_000}, "news": {"items": []},
                    "source_receipts": {"digest": "x"}} for s in SYMBOLS}
    core = FixtureStrategy()
    specs = [DecisionSpec(f"J1-{s}", {"go": {"type": "noul", "instructions": "Gate?"}},
                          {"skip": (), "enter": (Target(s, D(".9")),)}, state={"symbol": s})
             for s in SYMBOLS[20:]]
    entries = [(i, spec, _validate_questions(spec.questions), core.observation_symbols(spec))
               for i, spec in enumerate(specs)]
    costs = {spec.key: {} for spec in specs}
    excluded = {"source_receipts", "cost"}
    _, one_call, questions = request_batch(entries, observed, costs, excluded)
    assert not within_token_limits({**one_call, "observations": observed}, questions)  # the old request
    batches = request_batches(entries, observed, costs, excluded)
    assert len(batches) > 1
    assert [e[1].key for specs_, _, _ in batches for e in specs_] == [s.key for s in specs]
    for specs_, state, questions in batches:
        assert within_token_limits(state, questions)
        assert set(state["observations"]) == {"SPY"} | {spec.state["symbol"] for _, spec, _, _ in specs_}
        assert all("source_receipts" not in obs for obs in state["observations"].values())
        assert set(state["decisions"]) == {str(i) for i, *_ in specs_}


def test_single_oversized_decision_fails_closed_without_a_model_call(setup, monkeypatch):
    session, runner, api, model, clock, trial, _ = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    observation["states"]["SPY"]["features"] = {"pad": "7"*60_000}
    result = runner.decide(trial, FixtureStrategy(), boundary, observation, market)
    row = session.scalar(select(JevTurn).where(JevTurn.trial_id == trial.id))
    assert result and row.payload["batches"] == [{"index": 0, "status": "oversized_request"}]
    assert not model.calls and not api.submissions
    assert session.scalar(select(Incident.id).where(Incident.message == "Jev intraday: oversized_request"))


def test_research_rows_for_a_traded_symbol_never_receive_its_orders(setup):
    # 2026-10-06: J4's SPY/QQQ entries resolved to research:total-return rows.
    session, runner, api, _, _, _, iid = setup
    real = session.get(Instrument, iid)
    def row(external_id):
        return Instrument(venue_id=real.venue_id, market_id=real.market_id, external_id=external_id, symbol="SPY",
                          instrument_type="equity", currency="USD", contract_multiplier=D(1))
    session.add(row("research:total-return:SPY"))
    session.commit()
    assert runner.instruments()["SPY"].id == iid
    assert turn(setup)[0] and len(api.submissions) == 1
    session.add(row(str(uuid4())))
    session.commit()
    with pytest.raises(ValueError, match="Ambiguous"):
        runner.instruments()


def test_entry_is_priced_at_the_fresh_ask_within_its_planned_notional(setup):
    # 2026-10-06/07: limits at the observation ask were refused once the ask ticked up.
    session, runner, api, _, clock, trial, _ = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    observation = runner.observation(boundary, market)
    one = api.quote
    api.quote = lambda symbol: {**one(symbol), "ap": 100.05}
    assert runner.decide(trial, FixtureStrategy(), boundary, observation, market)
    [order] = api.submissions
    assert D(order["limit_price"]) == D("100.05") and D(order["qty"]) == D("0.199900049")
    assert D(order["qty"])*D("100.05") <= D(".2")*100


def test_quotes_leading_the_host_clock_wait_only_within_the_tolerance():
    clock, waits = [timestamp("2026-10-06T19:46:51.300Z")], []
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += timedelta(seconds=seconds)
    class Feed:
        def quotes(self, symbols):
            return {s: {"bp": 1, "ap": 1, "t": "2026-10-06T19:46:51.457123456Z"} for s in symbols}
        def quote(self, symbol):
            return {"bp": 1, "ap": 1, "t": (clock[0]+timedelta(seconds=5)).isoformat()}
    api = SettledQuotes(Feed(), lambda: clock[0], sleep=sleep)
    api.quotes(["V"])
    assert waits == [.157123] and clock[0] >= timestamp("2026-10-06T19:46:51.457123Z")
    api.quote("V")  # beyond the tolerance: unchanged, and still refused downstream
    assert waits == [.157123]
    assert not hasattr(SettledQuotes(object(), lambda: clock[0]), "quotes")


def test_freshest_quote_is_neither_dropped_nor_refused_as_future(setup):
    # The host clock lagged free-IEX event times by tens of ms on 2026-10-06/07.
    _, runner, api, _, clock, _, _ = setup
    runner.api._sleep = lambda seconds: clock.__setitem__(0, clock[0]+timedelta(seconds=seconds))
    one = api.quote
    api.quote = lambda symbol: {**one(symbol), "t": (clock[0]+timedelta(milliseconds=30)).isoformat()}
    result, row = turn(setup)
    assert set(row.payload["observation"]["quotes"]) == {"SPY"}
    assert result and row.payload["batches"][0]["status"] == "ok" and len(api.submissions) == 1


def test_concurrent_jev_receipt_after_the_clock_read_cannot_fail_the_turn(setup, monkeypatch):
    # 2026-10-07 10:30: AI-1's request committed between J4's clock read and its cost view.
    import tradingbot.forward.jev_intraday as runtime
    session, runner, api, _, clock, trial, _ = setup
    real, raced = runtime.account_costs, []
    def racing(session_, venue_id, now):
        if not raced:
            at = timestamp(now)+timedelta(milliseconds=5)
            session_.add(JevRequest(id=str(uuid4()), started_ts=at, completed_ts=at,
                billing_month=at.date().replace(day=1), completed_month=at.date().replace(day=1),
                correlation_id=f"paper-trial:{trial.id}:other-process", questions={}, answers={},
                requested_model="jev-latest", model_id=MODEL_ID, status="ok", actual_usd=D(0),
                reserved_usd=D(0), input_price_per_million=INPUT_PRICE_PER_MILLION,
                pricing_version=PRICING_VERSION, latency_ms=1, outcomes={}))
            session_.commit()
            clock[0] += timedelta(milliseconds=10)
            raced.append(at)
        return real(session_, venue_id, now)
    monkeypatch.setattr(runtime, "account_costs", racing)
    result, row = turn(setup)
    assert raced and result and row.payload["status"] == "complete"
    assert not runner.state(trial)["integrity_errors"] and len(api.submissions) == 1
