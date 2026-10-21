from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.conftest import FakeAPI, isolate_alpaca_venue
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector, NAME as CONNECTOR
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, Order, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.forward import c08_runner as c08
from tradingbot.forward.c08_state import NAME, PARAMS, calendar_plan, dump_core, restore_core
from tradingbot.forward.paper_evidence import NAME as EVIDENCE, account_evidence
from .test_c08_state import eia, rows


@pytest.fixture
def setup(monkeypatch):
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(session)
        now = [timestamp("2026-10-02T13:30:01Z")]
        api = FakeAPI(now)
        api.account_row["cash"] = "140"
        api.asset_row["symbol"] = "USO"
        calendar = rows()
        api.calendar = lambda day: deepcopy([r for r in calendar if r["date"] == str(day)])
        api.calendar_range = lambda start, end: deepcopy(calendar)
        connector = AlpacaPaperConnector(session, api, now=lambda: now[0])
        connector.initialize_cash(D(140))
        iid = connector.register_equity("USO")
        venue = connector._venue(lock=True)
        venue.metadata_ = {**venue.metadata_, CONNECTOR: {**venue.metadata_[CONNECTOR], "guard_required": EVIDENCE}}
        strategy = Strategy(key="c08-fixture-" + uuid4().hex, name="C08 isolated fixture", venue_id=venue.id,
                            status="paper", allocation_usd=D(140))
        session.add(strategy)
        session.flush()
        review_ref = {"path": "synthetic-review", "sha256": "fixture"}
        params = {**PARAMS, **calendar_plan(calendar, start="2026-10-01T21:00:00Z", through=date(2026, 10, 7)),
                  "uso_id": iid, "blackouts": [], "dependencies": c08.dependencies(), "reactor_sha256": c08.REACTOR,
                  "source_review": review_ref}
        trial = Trial(strategy_id=strategy.id, mode="paper", code_version=NAME, strategy_version=c08.VERSION,
                      params=params, metrics={NAME: {"enabled": True, "phases": {}, "incidents": [], "blackouts": [],
                      "source_review": review_ref, "core": dump_core(restore_core(params))}})
        session.add_all([trial, FxRate(base="USD", quote="GBP", ts=timestamp("2026-10-01T00:00:00Z"),
                                      rate=D(".8"), source="c08-synthetic-test")])
        session.commit()
        admitted = {"review_ref": review_ref, "blackouts": [], "actions": [], "eia": eia(),
                    "review": {"reviewed_at": "2026-10-01T20:30:00Z"}}
        monkeypatch.setattr(c08, "admission", lambda *a, **k: deepcopy(admitted))
        runner = c08.Runner(session, api, trial.id, now=lambda: now[0])
        yield runner, api, now, admitted
    finally:
        session.close()
        try:
            assert outer.is_active, "C08 fixture escaped its rollback transaction"
            outer.rollback()
        finally:
            connection.close()


def fill_entry(setup, quantity=None):
    runner, api, now, _ = setup
    assert runner.step() == "open"
    order = runner.orders()[0]
    now[0] += timedelta(seconds=1)
    api.fill(order.metadata_["client_order_id"][4:], qty=quantity or str(order.size))
    runner.step()
    return order


def test_open_is_once_only_across_restart_and_core_target_is_persisted(setup):
    runner, api, now, _ = setup
    assert runner.step() == "open"
    assert api.submissions[0]["qty"] == "1.329900000"
    assert runner.state()["core"]["pending"]["target"] == "133.00"
    resumed = c08.Runner(runner.session, api, runner.trial_id, now=lambda: now[0])
    resumed.step()
    assert len(api.submissions) == 1
    assert resumed.state()["core"]["attempted"] == ["c08:2026-10-02:buy"]
    assert runner.connector.cash().reserved == D("132.99")


def test_unknown_post_retains_reservation_and_polls_known_intent(setup):
    runner, api, now, _ = setup
    api.timeout_submit = True
    assert runner.step() == "pending"
    assert runner.orders()[0].metadata_["submission_unknown"] is True
    resumed = c08.Runner(runner.session, api, runner.trial_id, now=lambda: now[0])
    resumed.step()
    assert len(api.submissions) == 1
    assert resumed.orders()[0].metadata_["submission_unknown"] is False


def test_crash_after_claim_never_retries_or_reconstructs_an_order(setup, monkeypatch):
    runner, api, now, _ = setup
    def crash(**kwargs):
        raise SystemExit("simulated process loss")
    monkeypatch.setattr(runner.connector, "submit_limit", crash)
    with pytest.raises(SystemExit):
        runner.step()
    assert runner.state()["phases"]["2026-10-02:open"]["status"] == "claimed"
    resumed = c08.Runner(runner.session, api, runner.trial_id, now=lambda: now[0])
    assert resumed.step() == "held_for_resolution"
    assert not api.submissions
    assert resumed.state()["hold"]["key"] == "interrupted-2026-10-02:open"


@pytest.mark.parametrize("elapsed", [60, 61, 3600])
def test_missed_open_never_catches_up_off_window(setup, elapsed):
    runner, api, now, _ = setup
    now[0] = timestamp("2026-10-02T13:30:00Z") + timedelta(seconds=elapsed)
    assert runner.step() == "observing"
    assert runner.state()["phases"]["2026-10-02:open"]["status"] == "missed_window"
    runner.step()
    assert not api.submissions
    assert runner.state()["core"]["attempted"] == []


def test_later_open_may_use_original_pending_target_after_cash_delay(setup):
    runner, api, now, _ = setup
    # Other-account funds remain capped by the shared $140 book. A small broker
    # ceiling rejects the first intent without discarding the reactor's target.
    api.account_row["cash"] = "1"
    assert runner.step().startswith("submission_held")
    assert runner.state()["core"]["pending"]["target"] == "133.00"
    api.account_row["cash"] = "140"
    now[0] = timestamp("2026-10-05T13:30:01Z")
    assert runner.step() == "open"
    assert len(api.submissions) == 1
    assert runner.state()["core"]["pending"]["decision_date"] == "2026-10-02"


def test_partial_entry_cancel_after_window_retains_only_owned_shares(setup):
    runner, api, now, _ = setup
    order = fill_entry(setup, ".5")
    now[0] = timestamp("2026-10-02T13:31:01Z")
    runner.step()
    assert runner.ctx.position(runner.iid) == D(".5")
    assert runner.session.get(Order, order.id).status == "canceled"
    assert not runner.orders() and len(api.cancellations) == 1
    assert "hold" not in runner.state()
    assert D(runner.state()["net_with_fee_income_scenario"]) == D("-.01")


@pytest.mark.parametrize("failure", ["stale_quote", "source"])
def test_stale_quote_or_source_is_durable_hold_before_submission(setup, monkeypatch, failure):
    runner, api, _, _ = setup
    if failure == "stale_quote":
        api.quote_age = timedelta(seconds=31)
    else:
        def reject(*a, **k): raise ValueError("source watch expired")
        monkeypatch.setattr(c08, "admission", reject)
    assert runner.step() == "held_for_resolution"
    assert runner.state()["phases"]["2026-10-02:open"]["status"] == "evidence_held"
    assert not api.submissions


def test_submission_rechecks_opening_window_after_network_reads(setup, monkeypatch):
    runner, api, now, _ = setup
    old = api.account
    def delayed():
        now[0] = timestamp("2026-10-02T13:31:00Z")
        return old()
    monkeypatch.setattr(api, "account", delayed)
    assert runner.step().startswith("submission_held_")
    assert not api.submissions
    assert runner.state()["core"]["attempted"] == ["c08:2026-10-02:buy"]


def action_plan(setup):
    runner, _, _, admitted = setup
    plan = {"identity": "synthetic split", "decision": "2026-10-02", "exit": "2026-10-05",
            "reentry": "2026-10-07", "reviewed_at": "2026-10-01T20:00:00Z"}
    admitted["blackouts"] = [plan]
    return runner


def test_forced_exit_requires_actual_prior_close_and_partial_exit_holds(setup):
    runner = action_plan(setup)
    _, api, now, _ = setup
    fill_entry(setup)
    now[0] = timestamp("2026-10-02T20:00:01Z")
    assert runner.step() == "no_intent"
    assert runner.state()["core"]["blackout_decisions"] == ["2026-10-05"]
    now[0] = timestamp("2026-10-05T13:30:01Z")
    assert runner.step() == "open"
    exit_order = runner.orders()[0]
    assert exit_order.side == "sell"
    now[0] += timedelta(seconds=1)
    api.fill(exit_order.metadata_["client_order_id"][4:], qty=".2")
    assert runner.step() == "held_for_resolution"
    assert runner.ctx.position(runner.iid) == D("1.1299")


def test_missed_blackout_close_holds_owned_position_without_late_decision(setup):
    runner = action_plan(setup)
    _, api, now, _ = setup
    fill_entry(setup)
    now[0] = timestamp("2026-10-05T13:30:01Z")
    assert runner.step() == "held_for_resolution"
    assert runner.state()["hold"]["key"] == "missed-2026-10-02:close"
    assert len(api.submissions) == 1


def test_terminal_success_waits_for_real_exit_and_unproven_sale_cash_is_withheld(setup):
    runner, api, now, _ = setup
    fill_entry(setup)
    now[0] = timestamp("2026-10-07T13:30:01Z")
    assert runner.step() == "open"
    order = runner.orders()[0]
    assert order.side == "sell" and order.size == D("1.3299")
    now[0] += timedelta(seconds=1)
    api.fill(order.metadata_["client_order_id"][4:], qty=str(order.size))
    assert runner.step() == "complete"
    assert runner.session.get(Trial, runner.trial_id).status == "complete"
    venue = runner.connector._venue(lock=True)
    evidence = account_evidence(runner.session, venue, now[0], runner.sessions)
    assert evidence.details["withheld_sale_fill_ids"]
    assert evidence.cash_available < 8
    assert len(api.submissions) == 2
    trial = runner.session.get(Trial, runner.trial_id)
    assert trial.trade_count == 1 and trial.fees_total > 0
    assert trial.pnl == 0 and trial.pnl_after_fees == -trial.fees_total
    assert trial.metrics["execution_audit"]["ready_for_live"] is False


def test_terminal_missed_with_shares_is_not_completion(setup):
    runner, api, now, _ = setup
    fill_entry(setup)
    now[0] = timestamp("2026-10-07T13:31:00Z")
    assert runner.step() == "held_for_resolution"
    assert runner.session.get(Trial, runner.trial_id).status == "running"
    assert len(api.submissions) == 1


def test_disabled_preparation_has_no_network_or_order_work(setup, monkeypatch):
    runner, api, _, _ = setup
    state = runner.state()
    state["enabled"] = False
    runner.save(state)
    monkeypatch.setattr(api, "account", lambda: pytest.fail("disabled runner called account"))
    assert runner.step() == "prepared_held"
    assert not api.submissions


def test_source_failure_is_a_failed_null_metric_trial_without_allocation_change(setup, monkeypatch):
    runner, api, now, _ = setup
    old = runner.trial()
    old.status = "abandoned"
    strategy = runner.session.get(Strategy, runner.strategy_id)
    strategy.status, strategy.allocation_usd = "idea", D(0)
    runner.session.commit()
    monkeypatch.setattr(c08, "historical_evidence", lambda session: {"rows": [{"strategy_id": strategy.id}]})
    def hold(*a, **k): raise ValueError("issuer watch unresolved")
    monkeypatch.setattr(c08, "admission", hold)
    result = c08.prepare(runner.session, api, through=date(2026, 10, 7), review_ref={"synthetic": "hold"},
                         commit="fixture", now=timestamp("2026-10-01T21:00:00Z"))
    trial = runner.session.get(Trial, result["trial_id"])
    assert result["status"] == trial.status == "failed"
    assert trial.trade_count is trial.pnl_after_fees is trial.max_drawdown is None
    assert strategy.allocation_usd == 0 and strategy.status == "idea"
    assert not api.submissions
    assert runner.connector._book(runner.connector._venue())["initial_cash"] == "140"


def test_terminal_open_waits_within_window_but_partial_or_vetoed_exit_holds(setup):
    runner, api, now, _ = setup
    fill_entry(setup)
    now[0] = timestamp("2026-10-07T13:30:01Z")
    assert runner.step() == "open"
    now[0] += timedelta(seconds=1)
    assert runner.step() == "awaiting_terminal_fill"
    assert "hold" not in runner.state()


def test_risk_vetoed_exit_preserves_permanent_kill_and_holds(setup):
    runner, api, now, _ = setup
    fill_entry(setup)
    runner.connector.risk.kill_strategy(runner.strategy_id, "paper", D(-60), now[0])
    runner.session.commit()
    now[0] = timestamp("2026-10-07T13:30:01Z")
    assert runner.step().startswith("submission_held")
    assert runner.state()["hold"]["key"] == "exit-2026-10-07:open"
    assert runner.connector.risk.is_strategy_killed(runner.strategy_id)
    assert len(api.submissions) == 1


def test_activation_requires_admitted_shared_book_and_preserves_funding(setup, monkeypatch):
    runner, api, now, _ = setup
    state = runner.state()
    state["enabled"] = False
    runner.save(state)
    strategy = runner.session.get(Strategy, runner.strategy_id)
    strategy.status, strategy.allocation_usd = "idea", D(0)
    runner.session.commit()
    now[0] = timestamp("2026-10-01T21:00:00Z")
    decision = {"trial_id": runner.trial_id, "decision": "activate_paper",
                "promotion_checklist_complete": True, "account_integration_verified": True,
                "what_could_blow_up_this_account": "Synthetic risk review covers gaps, stale quotes, missing actions, uncertain submissions, account reservations, fees and shared daily losses.",
                "reviewed_at": now[0].isoformat()}
    monkeypatch.setattr(c08, "read_receipt", lambda ref: json.dumps(decision).encode())
    venue = runner.connector._venue(lock=True)
    book = deepcopy(venue.metadata_[CONNECTOR])
    venue.metadata_ = {**venue.metadata_, CONNECTOR: {k: v for k, v in book.items() if k != "guard_required"}}
    runner.session.commit()
    with pytest.raises(ValueError, match="migration"):
        c08.activate(runner.session, api, runner.trial_id, decision_ref={"test": "decision"}, now=now[0])
    runner.session.rollback()
    venue = runner.connector._venue(lock=True)
    venue.metadata_ = {**venue.metadata_, CONNECTOR: book}
    runner.session.commit()
    c08.activate(runner.session, api, runner.trial_id, decision_ref={"test": "decision"}, now=now[0])
    assert runner.state()["enabled"]
    assert strategy.allocation_usd == 140
    assert runner.connector._book(runner.connector._venue()) == book
    assert not api.submissions


def test_explicit_flat_resolution_keeps_attempt_history_and_cannot_clear_exposure(setup, monkeypatch):
    runner, api, now, _ = setup
    api.quote_age = timedelta(seconds=31)
    assert runner.step() == "held_for_resolution"
    before = deepcopy(runner.state()["phases"])
    now[0] = timestamp("2026-10-02T13:31:01Z")
    decision = {"trial_id": runner.trial_id, "hold_key": runner.state()["hold"]["key"],
                "decision": "resume_flat_at_future_open", "reviewer": "fixture",
                "reason": "Synthetic stale quote issue reviewed while flat; wait for a future scheduled open.",
                "reviewed_at": now[0].isoformat()}
    monkeypatch.setattr(c08, "read_receipt", lambda ref: json.dumps(decision).encode())
    c08.resolve_flat_hold(runner.session, runner.trial_id, {"test": "resolution"}, now=now[0])
    assert "hold" not in runner.state()
    assert runner.state()["phases"] == before
    assert len(runner.state()["resolutions"]) == 1
    assert not api.submissions


def test_modeled_income_is_audited_once_without_transport_credit(setup, tmp_path, monkeypatch):
    runner, _, now, admitted = setup
    fill_entry(setup)
    before = runner.connector.cash()
    directory = tmp_path / "data/forward/c08-integration/synthetic"
    directory.mkdir(parents=True)
    (directory / "issuer.raw").write_text("Synthetic issuer distribution of USD0.10 per USO share.")
    admitted["review"]["watch"] = {"path": "data/forward/c08-integration/synthetic/watch.json"}
    admitted["actions"] = [{"kind": "ordinary_cash", "symbol": "USO", "currency": "USD",
        "amount_per_share": ".10", "ex_date": "2026-10-05", "payable_date": "2026-10-06",
        "observed_at": "2026-10-01T20:00:00Z", "issuer_source": "issuer.raw"}]
    monkeypatch.setattr(c08, "ROOT", tmp_path)
    from tradingbot.forward import paper_evidence
    monkeypatch.setattr(paper_evidence, "ROOT", tmp_path)
    now[0] = timestamp("2026-10-05T13:30:01Z")
    runner._income(admitted)
    runner._income(admitted)
    venue = runner.connector._venue(lock=True)
    assert len(venue.metadata_[EVIDENCE]["incomes"]) == 1
    evidence = account_evidence(runner.session, venue, now[0], runner.sessions)
    assert D(evidence.details["income_receivable_usd"]) == D(".13299")
    assert evidence.strategy_pnl_offset(runner.strategy_id) == D(".12299")
    assert runner.connector.cash() == before


def test_documented_completion_is_bound_to_sale_and_waits_for_next_open(setup, monkeypatch):
    runner, api, now, _ = setup
    fill_entry(setup)
    now[0] = timestamp("2026-10-07T13:30:01Z")
    runner.step()
    order = runner.orders()[0]
    now[0] += timedelta(seconds=1)
    api.fill(order.metadata_["client_order_id"][4:], qty=str(order.size))
    assert runner.step() == "complete"
    fill = runner.session.scalar(select(Fill).where(Fill.order_id == order.id))
    trial = runner.session.get(Trial, runner.trial_id)
    trial.params = {**trial.params, "calendar": [*trial.params["calendar"],
        {"date": "2026-10-09", "settlement_date": "2026-10-13", "open": "09:30", "close": "16:00"}]}
    runner.session.commit()
    proof = {"kind": "broker_settlement_completion", "reviewer": "synthetic fixture",
             "completion_documented": True, "calendar_label_only": False,
             "basis": "Synthetic broker completion document matched to the exact account and execution.",
             "fill_id": fill.id, "venue_fill_id_sha256": c08.digest(fill.venue_fill_id.encode()),
             "account_fingerprint": runner.connector._book(runner.connector._venue())["account"],
             "completed_at": "2026-10-08T16:00:00Z", "observed_at": "2026-10-08T17:00:00Z",
             "reviewed_at": "2026-10-08T20:00:00Z", "raw_receipt": {"test": "raw"}}
    monkeypatch.setattr(c08, "read_receipt", lambda ref: json.dumps(proof).encode())
    from tradingbot.forward import paper_evidence
    monkeypatch.setattr(paper_evidence, "receipt", lambda ref: b"synthetic verified bytes")
    now[0] = timestamp("2026-10-08T20:01:00Z")
    proof["calendar_label_only"] = True
    with pytest.raises(ValueError, match="actual broker"):
        c08.admit_completion(runner.session, runner.trial_id, {"test": "proof"}, now=now[0])
    proof["calendar_label_only"] = False
    result = c08.admit_completion(runner.session, runner.trial_id, {"test": "proof"}, now=now[0])
    assert D(result["cash_available_usd"]) < 8 and not result["transport_cash_credited"]
    now[0] = timestamp("2026-10-09T13:30:00Z")
    result = c08.admit_completion(runner.session, runner.trial_id, {"test": "proof"}, now=now[0])
    assert D(result["cash_available_usd"]) > 139
