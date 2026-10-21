"""Daily cohort invariants, real Postgres rolled back; fake brokers/providers."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from connectors.conftest import FakeAPI, isolate_alpaca_venue
from tradingbot.ai.claude import ClaudeDecision, MODEL_ID as CLAUDE_MODEL
from tradingbot.ai.jev import (JevDecision, MODEL_ID, INPUT_PRICE_PER_MILLION, PRICING_VERSION,
                               _validate_questions, within_token_limits)
from tradingbot.ai.state import NEWS_HEADLINE_CHARS, NEWS_MAX_ITEMS
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, JevRequest, JevTurn, Order, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.forward.ai1_gate import (
    ALLOCATION, VERSION, NAME, KINDS, DailyRunner, calibration, due_boundary, prepare,
)
from tradingbot.forward.ai_paper_costs import account_costs
from tradingbot.data.iex_intraday import SYMBOLS


class Model:
    def __init__(self, session, clock, kind):
        self.session, self.clock, self.kind = session, clock, kind
        self.calls, self.labels = [], []
        self.unavailable = False
        self.probability = .8

    def decide(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.unavailable:
            return None
        at, request_id = self.clock[0], str(uuid4())
        answers = {k: {"type": "noul", "noul": self.probability} for k in kwargs["questions"]}
        if self.kind == "claude":
            return ClaudeDecision(request_id, CLAUDE_MODEL, answers, D(0), 1, D(".01"), {})
        self.session.add(JevRequest(id=request_id, started_ts=at, completed_ts=at,
            billing_month=at.date().replace(day=1), completed_month=at.date().replace(day=1),
            correlation_id=kwargs["correlation_id"], questions=kwargs["questions"], answers=answers,
            requested_model="jev-latest", model_id=MODEL_ID, status="ok", actual_usd=D(".001"),
            reserved_usd=D(0), input_price_per_million=INPUT_PRICE_PER_MILLION,
            pricing_version=PRICING_VERSION, latency_ms=1, outcomes={}))
        self.session.commit()
        return JevDecision(request_id, MODEL_ID, answers, D(".001"), 1)

    def record_outcome(self, *args, **kwargs):
        self.labels.append((args, kwargs))
        return True


@pytest.fixture
def setup():
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(session)
        session.execute(update(Trial).where(Trial.code_version == VERSION).values(code_version="test-hidden-"+uuid4().hex))
        session.execute(update(Strategy).where(Strategy.key.startswith("ai1-daily-")).values(key=Strategy.key+"-"+uuid4().hex[:8]))
        clock = [timestamp("2026-09-30T14:30:05Z")]
        api = FakeAPI(clock)
        api.quote = lambda symbol: {"bp": 100, "ap": 100, "bs": 1, "as": 1, "t": clock[0].isoformat()}
        connector = AlpacaPaperConnector(session, api, now=lambda: clock[0])
        connector.register_equity("SPY")
        connector.initialize_cash(D(100))
        session.add(FxRate(base="USD", quote="GBP", ts=clock[0]-timedelta(days=1), rate=D(".8"), source="fixture"))
        session.commit()
        cohort = prepare(session, git_commit="fixture", now=clock[0])
        models = {k: Model(session, clock, k) for k in ("jev", "claude")}
        def builder(session, symbol, *, decision_at, boundary):
            return {"symbol": symbol, "boundary": boundary.isoformat(), "features": {"ret_session": ".01"},
                    "quality": {"complete_suffix_intervals": 4}, "news": {"untrusted": True, "items": []}} if symbol == "SPY" else None
        runner = DailyRunner(session, api, model=models["jev"], claude=models["claude"],
                             now=lambda: clock[0], state_builder=builder)
        # Test sessions use one connection/savepoint; no database object crosses threads.
        runner.provider_calls = lambda calls: {k: c.decide(**kw) for k, (c, kw) in calls.items()}
        yield session, runner, api, models, clock, {k: session.get(Trial, t) for k, t in cohort.items()}
    finally:
        session.close()
        try:
            assert outer.is_active
            outer.rollback()
        finally:
            connection.close()


def turn(setup):
    session, runner, api, models, clock, cohort = setup
    market = runner.market(clock[0])
    boundary = due_boundary(clock[0], market)
    result = runner.decide_cohort(cohort["ungated"], boundary, runner.observation(boundary, market), market)
    return result, session.scalar(select(JevTurn).where(JevTurn.trial_id == cohort["ungated"].id))


def test_three_real_equal_tickets_one_virtual_control_and_no_duplicate(setup):
    session, runner, api, models, clock, cohort = setup
    assert turn(setup)[0]
    assert len(api.submissions) == 3
    assert len({s["qty"] for s in api.submissions}) == 1
    assert all(s["side"] == "buy" for s in api.submissions)
    assert models["jev"].calls[0]["state"] == models["claude"].calls[0]["state"]
    assert models["jev"].calls[0]["questions"] == models["claude"].calls[0]["questions"]
    assert len(runner.state(cohort["random"])["book"]["fills"]) == 1
    assert session.scalar(select(Order.id).where(Order.trial_id == cohort["random"].id)) is None
    assert not turn(setup)[0] and len(api.submissions) == 3
    assert not session.scalar(select(Fill.id).where(Fill.trial_id.in_([t.id for t in cohort.values()])))


def test_provider_outage_only_skips_that_gate_and_matched_random(setup):
    _, runner, api, models, _, cohort = setup
    models["jev"].unavailable = True
    assert turn(setup)[0]
    assert len(api.submissions) == 2
    assert not runner.state(cohort["random"])["book"]["fills"]
    assert not runner.orders(cohort["jev"])


def test_claude_outage_preserves_jev_and_ungated(setup):
    _, runner, api, models, _, cohort = setup
    models["claude"].unavailable = True
    assert turn(setup)[0] and len(api.submissions) == 2
    assert not runner.orders(cohort["claude"])


def test_paired_cash_skip_consumes_day_before_providers(setup, monkeypatch):
    _, runner, api, models, _, _ = setup
    monkeypatch.setattr(runner, "available", lambda trial: D(".50"))
    ok, row = turn(setup)
    assert ok and row.payload["skip_reason"] == "insufficient_paired_settled_cash"
    assert not api.submissions and not any(m.calls for m in models.values())
    assert not turn(setup)[0]


def test_original_deadline_expires_even_with_fresh_execution_quote(setup):
    _, runner, api, models, clock, _ = setup
    original = runner.provider_calls
    def delayed(calls):
        replies = original(calls)
        clock[0] += timedelta(seconds=31)
        return replies
    runner.provider_calls = delayed
    ok, row = turn(setup)
    assert ok and not api.submissions
    assert row.payload["receipts"]["jev"]["status"] == "invalid_or_expired"
    assert row.payload["receipts"]["claude"]["status"] == "invalid_or_expired"


def test_admission_does_not_reset_cash_or_touch_other_runners(setup):
    session, runner, _, _, _, cohort = setup
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    assert runner.connector._book(venue)["initial_cash"] == "100"
    assert all(t.code_version == VERSION for t in cohort.values())
    assert {t.id for t in runner.trials()} == {cohort[k].id for k in KINDS}
    with pytest.raises(ValueError, match="already admitted"):
        prepare(session, git_commit="fixture")


def test_no_replay_after_window_and_missed_day_is_visible(setup):
    session, runner, api, models, clock, cohort = setup
    market = runner.market(clock[0])
    assert due_boundary(clock[0], market) == timestamp("2026-09-30T14:30:00Z")
    clock[0] = timestamp("2026-09-30T14:32:00Z")
    assert due_boundary(clock[0], market) is None
    runner.tick()
    row = session.scalar(select(JevTurn).where(JevTurn.trial_id == cohort["ungated"].id))
    assert row.payload["candidate_count"] == 0 and row.payload["skip_reason"] == "missed_snapshot_or_entry_window"
    assert not api.submissions and not any(m.calls for m in models.values())


def test_real_roundtrip_labels_rejected_model_forecasts_and_costs(setup):
    session, runner, api, models, clock, cohort = setup
    models["claude"].probability = .2
    assert turn(setup)[0]
    # Actual activities, not modeled fills, open the two passing real arms.
    for submitted in list(api.submissions):
        api.fill(submitted["client_order_id"][4:], qty=submitted["qty"])
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    clock[0] = timestamp("2026-09-30T19:55:01Z")
    api.quote = lambda symbol: {"bp": 99, "ap": 99, "bs": 1, "as": 1, "t": clock[0].isoformat()}
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    for submitted in [s for s in api.submissions if s["side"] == "sell"]:
        api.fill(submitted["client_order_id"][4:], qty=submitted["qty"], price="99")
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    runner.report_cohort(cohort["ungated"], runner.market(clock[0]))
    row = session.scalar(select(JevTurn).where(JevTurn.trial_id == cohort["ungated"].id))
    assert row.payload["labels"]["SPY"]["outcome"] is False
    assert runner.state(cohort["claude"])["calibration"]["count"] == 1
    assert runner.state(cohort["claude"])["calibration"]["beats_always_yes"]
    assert cohort["claude"].trade_count == 0
    assert cohort["ungated"].trade_count == cohort["jev"].trade_count == 1
    costs = account_costs(session, runner.connector._venue().id, clock[0])
    # Account-wide cumulative fee rounding may debit another arm's sell first.
    # Verify the Jev charge directly instead of assuming equal penny allocation.
    assert sum(costs.model_by_request.values()) == D(".001")
    assert cohort["jev"].pnl_after_fees == runner.connector.ledger.realized_after_fees(
        trial_id=cohort["jev"].id, mode="paper")-costs.by_trial[cohort["jev"].id]
    assert models["jev"].labels
    assert all(not runner.state(cohort[k])["ready_for_live"] for k in KINDS)


def test_brier_is_paired_and_always_yes_is_not_a_win():
    assert not calibration([])["beats_always_yes"]
    assert not calibration([(D(1), True), (D(1), False)])["beats_always_yes"]
    result = calibration([(D(".8"), True), (D(".2"), False)])
    assert result["beats_always_yes"] and result["brier"] == "0.04"


def test_uncertain_posts_are_claimed_once_across_restart(setup):
    _, runner, api, _, _, cohort = setup
    api.timeout_submit = True
    assert turn(setup)[0]
    assert len(api.submissions) == 3
    assert not turn(setup)[0]
    for kind in KINDS:
        assert len(runner.orders(cohort[kind])) == 1
        assert runner.state(cohort[kind])["entries"]
    assert len(api.submissions) == 3


def test_invalid_probability_cannot_become_a_gate_pass(setup):
    _, runner, api, models, _, cohort = setup
    models["jev"].probability = 1.1
    ok, row = turn(setup)
    assert ok and row.payload["receipts"]["jev"]["status"] == "invalid_or_expired"
    assert not runner.orders(cohort["jev"])
    assert not runner.state(cohort["random"])["book"]["fills"]
    assert len(api.submissions) == 2


def test_risk_halt_prevents_even_provider_calls(setup, monkeypatch):
    _, runner, api, models, _, _ = setup
    monkeypatch.setattr(runner.connector.risk, "is_globally_halted", lambda *args: True)
    ok, row = turn(setup)
    assert ok and row.payload["skip_reason"] == "risk_halted"
    assert not api.submissions and not any(m.calls for m in models.values())


def test_pending_entries_cancel_after_window_and_no_model_retry(setup):
    _, runner, api, models, clock, cohort = setup
    assert turn(setup)[0]
    clock[0] = timestamp("2026-09-30T14:32:00Z")
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    assert len(api.cancellations) == 3
    assert len(models["jev"].calls) == len(models["claude"].calls) == 1


def test_unavailable_claude_cost_estimate_is_unknown(setup):
    _, runner, _, models, clock, cohort = setup
    models["claude"].unavailable = True
    assert turn(setup)[0]
    runner.report_cohort(cohort["ungated"], runner.market(clock[0]))
    state = runner.state(cohort["claude"])
    assert state["model_estimated_cost_usd"] is None
    assert state["net_less_claude_list_price_estimate"] is None
    assert state["provider_unavailable_days"] == 1


def test_unfilled_selected_trade_blocks_comparison_qualification(setup):
    session, runner, api, models, clock, cohort = setup
    execute = runner.execute
    runner.execute = lambda trial, *args, **kwargs: ("held" if trial.id == cohort["claude"].id
                                                    else execute(trial, *args, **kwargs))
    assert turn(setup)[0]
    for submitted in list(api.submissions):
        api.fill(submitted["client_order_id"][4:], qty=submitted["qty"])
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    clock[0] = timestamp("2026-09-30T19:55:01Z")
    api.quote = lambda symbol: {"bp": 99, "ap": 99, "bs": 1, "as": 1, "t": clock[0].isoformat()}
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    for submitted in [s for s in api.submissions if s["side"] == "sell"]:
        api.fill(submitted["client_order_id"][4:], qty=submitted["qty"], price="99")
    for kind in KINDS:
        runner.manage(cohort[kind], runner.market(clock[0]))
    runner.report_cohort(cohort["ungated"], runner.market(clock[0]))
    state = runner.state(cohort["claude"])
    assert state["paired_execution_gaps"] == [{"day": "2026-09-30", "symbol": "SPY"}]
    assert "unmatched_selected_execution" in state["current_gate"]["reasons"]
    assert not state["ready_for_live"]


def test_model_input_and_deadline_cover_only_candidates_and_market(setup):
    # 2026-10-05: all 40 observations with headlines were ~50k tokens (Jev
    # refused, limit 32k) and a 16s-old non-candidate quote expired 6/8 entries.
    _, runner, api, models, clock, _ = setup
    ranked = [s for s in SYMBOLS if s != "SPY"]
    stale = ranked[-1]
    ids = {s: (api.asset_id if s == "SPY" else str(uuid4())) for s in SYMBOLS}
    api.asset = lambda symbol: {**api.asset_row, "symbol": symbol, "id": ids[symbol]}
    for symbol in SYMBOLS:
        runner.connector.register_equity(symbol)
    news = {"untrusted": True, "status": "ok", "items": [{"headline": "x"*NEWS_HEADLINE_CHARS}]*NEWS_MAX_ITEMS}
    def builder(session, symbol, *, decision_at, boundary):
        rank = len(ranked) if symbol == "SPY" else ranked.index(symbol)
        return {"symbol": symbol, "boundary": boundary.isoformat(), "news": news,
                "features": {"ret_session": str(D(".05")-D(rank)/1000)}, "quality": {"complete_suffix_intervals": 4}}
    runner.state_builder = builder
    observed = clock[0]
    api.quote = lambda symbol: {"bp": 100, "ap": 100, "bs": 1, "as": 1,
        "t": (observed-timedelta(seconds=25) if symbol == stale else clock[0]).isoformat()}
    original = runner.provider_calls
    def slow(calls):
        clock[0] += timedelta(seconds=10)
        return original(calls)
    runner.provider_calls = slow
    ok, row = turn(setup)
    candidates = set(ranked[:8])
    jev, claude = models["jev"].calls[0], models["claude"].calls[0]
    assert ok and jev["state"] == claude["state"]
    assert set(jev["state"]["observations"]) == candidates | {"SPY"}
    assert within_token_limits(jev["state"], _validate_questions(jev["questions"]))
    assert row.payload["deadline"] == (observed+timedelta(seconds=30)).isoformat()
    assert row.payload["receipts"]["jev"]["status"] == row.payload["receipts"]["claude"]["status"] == "ok"
    assert len(api.submissions) == 3*len(candidates)
