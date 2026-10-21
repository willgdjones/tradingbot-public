from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
import json

import pytest
from sqlalchemy import select, text

from connectors.conftest import connector_seed, session, setup, ready, submit  # noqa: F401

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.forward import paper_evidence as e
from tradingbot.db.models import Fill, Order, Strategy, Trial
from tradingbot.db.session import get_engine


def sessions():
    return [MarketSession.from_api({"date": day, "settlement_date": settle,
                                    "open": "09:30", "close": "16:00"})
            for day, settle in [("2026-10-01", "2026-10-02"), ("2026-10-02", "2026-10-05"),
                                ("2026-10-09", "2026-10-13"), ("2026-10-12", "2026-10-13"),
                                ("2026-10-13", "2026-10-14"), ("2026-10-14", "2026-10-15")]]


def fill(i=1, sid=1, side="buy", day="2026-10-01", quantity=".2", price="100", fee="0"):
    return {"id": i, "strategy_id": sid, "fill_at": day + "T14:00:00Z", "side": side,
            "price": price, "quantity": quantity, "fee": fee,
            "settlement_date": "2026-10-13" if side == "sell" else "2026-10-02"}


def build(**kwargs):
    base = dict(initial="140", allocations={1: "140", 2: "140"}, fills=[], orders=[],
                incomes=[], settlements={}, sessions=sessions(), now="2026-10-14T14:00:00Z")
    return e.build_evidence(**(base | kwargs))


def test_one_account_fee_rounding_across_strategies_and_no_duplicate_funding():
    result = build(fills=[fill(1, 1), fill(2, 2)])
    assert result.cash_available == D("99.99")
    assert result.strategy_cash(1) == D("119.99")
    assert result.strategy_cash(2) == D("120")
    assert [r["modeled_fee_usd"] for r in result.details["fees"]] == ["0.01", "0.00"]
    assert result.strategy_pnl_offset(1) == D("-.01")
    # Deterministic even when storage retrieval order changes.
    assert build(fills=[fill(2, 2), fill(1, 1)]) == result


def test_actual_fees_already_in_ledger_are_not_double_debited_in_pnl():
    result = build(fills=[fill(fee=".03")], now="2026-10-01T15:00:00Z")
    assert result.cash_available == D("119.97")
    assert result.daily_pnl_offset == 0
    assert result.strategy_pnl_offset(1) == 0


def test_each_partial_keeps_timestamp_and_next_day_fee_accumulator():
    result = build(fills=[fill(1, quantity=".1"), fill(2, quantity=".1"),
                          fill(3, day="2026-10-02", quantity=".1")], now="2026-10-02T15:00:00Z")
    assert result.cash_available == D("109.98")
    assert result.daily_pnl_offset == D("-.01")
    assert result.strategy_pnl_offset(1) == D("-.02")


def proof(**changes):
    return {"kind": "broker_settlement_completion", "fill_id": 2,
            "completed_at": "2026-10-13T20:00:00Z", "observed_at": "2026-10-13T21:00:00Z", **changes}


def test_calendar_settlement_alone_never_releases_sale_and_receipt_waits_next_open():
    fills = [fill(), fill(2, side="sell", day="2026-10-09", price="101")]
    unknown = build(fills=fills)
    assert unknown.cash_available == D("119.96")
    assert unknown.details["withheld_sale_fill_ids"] == [2]
    before = build(fills=fills, settlements={"2": proof()}, now="2026-10-14T13:29:59Z")
    after = build(fills=fills, settlements={"2": proof()}, now="2026-10-14T13:30:00Z")
    assert before.cash_available == unknown.cash_available
    assert after.cash_available == D("140.16")
    # Receipt observed after today's open waits a later opening, not backdating.
    late = build(fills=fills, settlements={"2": proof(observed_at="2026-10-14T13:30:01Z")})
    assert late.cash_available == unknown.cash_available


@pytest.mark.parametrize("changes", [{"kind": "nominal_t1"}, {"fill_id": 1},
    {"completed_at": "2026-10-12T20:00:00Z"}, {"observed_at": "2026-10-12T20:00:00Z"},
    {"observed_at": "2026-10-15T20:00:00Z"}])
def test_invalid_completion_proof_holds(changes):
    with pytest.raises(ValueError, match="documented completion"):
        build(fills=[fill(2, side="sell", day="2026-10-09")], settlements={"2": proof(**changes)})


def income(**changes):
    return {"strategy_id": 1, "event_id": "DBA:2026-10-02:ordinary_cash",
            "recognized_at": "2026-10-02T13:30:00Z", "modeled_release_at": "2026-10-12T13:30:00Z",
            "source_observed_at": "2026-10-01T20:00:00Z", "cash_amount": "1",
            "amount_per_share": "2", "quantity_before_ex_open": ".5",
            "execution_fill": False, "broker_credit_verified": False, **changes}


def test_income_recognized_in_ex_open_pnl_once_and_payable_not_actual_cash():
    before = build(incomes=[income()], now="2026-10-02T13:29:59Z")
    ex = build(incomes=[income()], now="2026-10-02T13:30:00Z")
    paid = build(incomes=[income()], now="2026-10-12T13:30:00Z")
    assert before.strategy_pnl_offset(1) == 0
    assert ex.strategy_pnl_offset(1) == ex.daily_pnl_offset == 1
    assert ex.strategy_cash(1) == 140
    assert paid.strategy_cash(1) == 141
    assert paid.strategy_pnl_offset(1) == 1 and paid.daily_pnl_offset == 0
    assert ex.cash_available == paid.cash_available == 140
    assert paid.details["actual_income_credit_usd"] == "0"


@pytest.mark.parametrize("changes", [{"cash_amount": "2"}, {"source_observed_at": "2026-10-02T13:31:00Z"},
    {"broker_credit_verified": True}, {"execution_fill": True}])
def test_unverified_or_changed_income_cannot_become_credit(changes):
    with pytest.raises(ValueError):
        build(incomes=[income(**changes)])


def test_duplicates_or_unknown_strategy_or_future_fill_hold():
    for rows in [[fill(), fill()], [fill(sid=3)], [fill(day="2026-10-15")]]:
        with pytest.raises(ValueError):
            build(fills=rows)
    with pytest.raises(ValueError, match="Duplicate"):
        build(incomes=[income(), income()])


def test_reservations_include_partial_remainder_and_fee_across_strategies():
    result = build(fills=[fill(quantity=".1")], orders=[
        {"id": 1, "strategy_id": 1, "side": "buy", "remaining": ".1", "limit_price": "100"},
        {"id": 2, "strategy_id": 2, "side": "buy", "remaining": ".5", "limit_price": "100"}])
    assert result.cash_available == D("69.97")
    assert result.strategy_cash(1) == D("119.98")
    assert result.strategy_cash(2) == D("89.99")


def test_mark_inventory_change_between_capture_and_lock_is_not_ignored(monkeypatch):
    monkeypatch.setattr(e, "required_instrument_ids", lambda *a: {1, 2})
    quotes = {1: {"t": "2026-10-01T14:00:00Z", "bp": "100", "ap": "102"}}
    with pytest.raises(ValueError, match="full-portfolio"):
        e.fresh_marks(None, quotes, "2026-10-01T14:00:00Z", sessions()[0])
    quotes[2] = {"t": "2026-10-01T13:59:30Z", "bp": "10", "ap": "11"}
    assert e.fresh_marks(None, quotes, "2026-10-01T14:00:00Z", sessions()[0]) == {1: D(101), 2: D("10.5")}
    with pytest.raises(ValueError, match="Stale"):
        e.fresh_marks(None, quotes, "2026-10-01T14:00:01Z", sessions()[0])
    quotes[2]["t"] = "2026-10-01T14:00:02Z"
    with pytest.raises(ValueError, match="future"):
        e.fresh_marks(None, quotes, "2026-10-01T14:00:00Z", sessions()[0])


def guarded(ready):
    connector, api, clock, instrument, *_ = ready
    calendar = [MarketSession.from_api(r) for day in ("2026-09-30", "2026-10-01", "2026-10-02")
                for r in api.calendar(timestamp(day + "T14:00:00Z").date())]
    guard = e.EvidenceGuard(calendar, additional={instrument.id})
    connector.execution_guard = guard
    return guard


def test_guard_persists_account_evidence_and_never_retries_unknown_post(ready):
    connector, api, clock, *_ = ready
    guard = guarded(ready)
    api.timeout_submit = True
    guard.capture(connector)
    first = submit(ready)
    assert first.submission_unknown
    # A restart/lost quote batch cannot turn a known tag into a new POST.
    connector.execution_guard = e.EvidenceGuard(guard.sessions)
    assert submit(ready).order_id == first.order_id
    assert len(api.submissions) == 1
    row = connector.session.get(Order, first.order_id)
    assert row.metadata_["account_evidence"]["initial_shared_cash_usd"] == "100"


def test_guard_pending_fee_cash_reserve_blocks_other_strategy_overspend(ready):
    from tradingbot.connectors.alpaca_paper import OrderRejected
    connector, api, *_ = ready
    guard = guarded(ready)
    guard.capture(connector)
    with pytest.raises(OrderRejected, match="settled cash"):
        submit(ready, quantity="1")  # $100 needs a separate modeled CAT cent
    assert not api.submissions
    guard.capture(connector)
    assert submit(ready, quantity=".9999").status == "open"


def test_guard_reages_batch_after_capture_and_honors_frozen_deadline(ready):
    connector, api, clock, *_ = ready
    guard = guarded(ready)
    guard.capture(connector, valid_until=clock[0] + timedelta(seconds=5))
    clock[0] += timedelta(seconds=5)
    with pytest.raises(ValueError, match="Fresh unchanged"):
        submit(ready)
    assert not api.submissions


def test_guard_rejects_evidence_change_after_capture_under_lock(ready):
    connector, api, *_ = ready
    guard = guarded(ready)
    guard.capture(connector)
    venue = connector._venue(lock=True)
    venue.metadata_ = {**venue.metadata_, e.NAME: {"review": "changed"}}
    connector.session.commit()
    with pytest.raises(ValueError, match="unchanged"):
        submit(ready)
    assert not api.submissions


def test_guard_refresh_preserves_fill_when_quote_capture_unavailable(ready):
    from tradingbot.connectors.alpaca_paper import PaperEvidenceUnavailable
    connector, api, clock, *_ = ready
    guard = guarded(ready)
    guard.capture(connector)
    result = submit(ready)
    clock[0] += timedelta(seconds=31)
    api.fill("one")
    with pytest.raises(PaperEvidenceUnavailable):
        connector.refresh(result.order_id)
    assert connector.session.scalar(select(Fill).where(Fill.order_id == result.order_id)) is not None
    assert connector.session.get(Order, result.order_id).status == "filled"
    guard.capture(connector)
    assert connector.refresh(result.order_id).status == "filled"


def migration_review(ready):
    connector, _, clock, _, _, trial = ready
    trial.code_version = "alpaca_tom_forward_v1"
    connector.session.commit()
    return {"schema": e.NAME + ":migration", "decision": "enable_account_guard", "reviewer": "test",
            "reason": "Test explicit shared accounting migration; preserve source strategy and paper funding.",
            "modeled_income_is_not_broker_cash": True, "preserve_existing_trials_and_funding": True,
            "reviewed_at": clock[0].isoformat(), "identity": e.migration_identity(connector.session)}


def test_explicit_account_migration_preserves_funding_and_trial_identity(ready, monkeypatch):
    connector, _, clock, _, strategy, trial = ready
    review = migration_review(ready)
    params, allocation = deepcopy(trial.params), strategy.allocation_usd
    monkeypatch.setattr(e, "receipt", lambda ref: json.dumps(review).encode())
    with get_engine().connect() as lock:
        e.enable_account_guard(connector.session, {"path": "fixture", "sha256": "fixture"}, lock, now=clock[0])
    venue = connector._venue()
    assert venue.metadata_[e.CONNECTOR]["guard_required"] == e.NAME
    assert e.migration_identity(connector.session) == review["identity"]
    assert trial.params == params and strategy.allocation_usd == allocation
    assert connector.cash().available == 100


def test_migration_refuses_active_runner_and_changed_review(ready, monkeypatch):
    connector, _, clock, _, _, trial = ready
    review = migration_review(ready)
    monkeypatch.setattr(e, "receipt", lambda ref: json.dumps(review).encode())
    with get_engine().connect() as active, get_engine().connect() as lock:
        active.execute(text("SELECT pg_advisory_lock(60426, :trial)"), {"trial": trial.id})
        try:
            with pytest.raises(ValueError, match="runner is active"):
                e.enable_account_guard(connector.session, {}, lock, now=clock[0])
        finally:
            active.execute(text("SELECT pg_advisory_unlock(60426, :trial)"), {"trial": trial.id})
        review["identity"]["book"]["initial_cash"] = "140"
        with pytest.raises(ValueError, match="identity changed"):
            e.enable_account_guard(connector.session, {}, lock, now=clock[0])
    assert "guard_required" not in connector._book(connector._venue())


def scheduled(ready, monkeypatch):
    connector, api, clock, instrument, *_ = ready
    monkeypatch.setattr(e, "receipt", lambda ref: b"immutable issuer fixture")
    event = {"symbol": "SPY", "kind": "ordinary_cash", "currency": "USD", "ex_date": "2026-10-01",
             "payable_date": "2026-10-01", "amount_per_share": "50",
             "observed_at": "2026-09-29T14:00:00Z", "reviewed_at": "2026-09-29T15:00:00Z",
             "source_receipt": {"path": "fixture", "sha256": "a" * 64}}
    guard = guarded(ready)
    venue = connector._venue(lock=True)
    e.schedule_income_event(connector.session, venue, event, guard.sessions, instrument_id=instrument.id, now=clock[0])
    connector.session.commit()
    return guard, event


def buy_and_fill(ready, request="one", quantity=".6"):
    connector, api, clock, *_ = ready
    result = submit(ready, request_id=request, quantity=quantity)
    clock[0] += timedelta(seconds=1)
    api.fill(request, qty=quantity)
    connector.refresh(result.order_id)
    return result


def test_queued_income_precedes_first_ex_open_risk_check_without_strategy_runner(ready, monkeypatch):
    connector, api, clock, instrument, strategy, _ = ready
    result = buy_and_fill(ready)
    guard, _ = scheduled(ready, monkeypatch)
    clock[0] = timestamp("2026-10-01T13:30:00Z")
    api.quote = lambda symbol: {"t": clock[0].isoformat(), "bp": 20, "ap": 20}
    guard.capture(connector)
    # The only action is the generic connector's known-order refresh. No C05,
    # C08 or source runner has recognized/stored a direct entitlement yet.
    assert connector.refresh(result.order_id).status == "filled"
    assert strategy.status == "paper"  # raw -$48 would falsely cross the -$40 kill
    venue = connector._venue(lock=True)
    evidence = e.account_evidence(connector.session, venue, clock[0], guard.sessions)
    assert evidence.strategy_pnl_offset(strategy.id) == D("29.99")
    assert evidence.daily_pnl_offset == D(30)
    assert D(evidence.details["income_receivable_usd"]) == 30
    assert evidence.cash_available == D("39.99")
    assert not venue.metadata_[e.NAME].get("incomes")


def test_queued_income_pre_ex_pending_order_holds_unknown_ownership(ready, monkeypatch):
    connector, api, clock, *_ = ready
    buy_and_fill(ready)
    submit(ready, request_id="unresolved", quantity=".1")
    guard, _ = scheduled(ready, monkeypatch)
    clock[0] = timestamp("2026-10-01T13:30:00Z")
    with pytest.raises(ValueError, match="pre-ex order"):
        e.account_evidence(connector.session, connector._venue(lock=True), clock[0], guard.sessions)


def test_queued_income_same_ex_buy_does_not_increase_entitlement(ready, monkeypatch):
    connector, api, clock, instrument, strategy, _ = ready
    buy_and_fill(ready, quantity=".2")
    guard, _ = scheduled(ready, monkeypatch)
    clock[0] = timestamp("2026-10-01T13:30:00Z")
    guard.capture(connector)
    result = submit(ready, request_id="exbuy", quantity=".1")
    api.fill("exbuy", qty=".1")
    connector.refresh(result.order_id)
    evidence = e.account_evidence(connector.session, connector._venue(lock=True), clock[0], guard.sessions)
    assert D(evidence.details["income_receivable_usd"]) == 10
    assert evidence.strategy_pnl_offset(strategy.id) == D("9.98")


def test_income_schedule_idempotence_late_notice_and_conflicting_rate(ready, monkeypatch):
    connector, _, clock, instrument, *_ = ready
    guard, event = scheduled(ready, monkeypatch)
    venue = connector._venue(lock=True)
    before = deepcopy(venue.metadata_)
    e.schedule_income_event(connector.session, venue, event, guard.sessions, instrument_id=instrument.id, now=clock[0])
    assert venue.metadata_ == before
    with pytest.raises(ValueError, match="facts changed"):
        e.schedule_income_event(connector.session, venue, {**event, "amount_per_share": "51"},
                                guard.sessions, instrument_id=instrument.id, now=clock[0])
    venue.metadata_ = {k: v for k, v in before.items() if k != e.NAME}
    with pytest.raises(ValueError, match="before ex-open"):
        e.schedule_income_event(connector.session, venue, event, guard.sessions,
                                instrument_id=instrument.id, now=timestamp("2026-10-01T13:30:00Z"))


def test_queued_income_all_account_owners_and_direct_receipts_are_not_double_counted(ready, monkeypatch):
    from uuid import uuid4
    connector, api, clock, instrument, strategy, _ = ready
    buy_and_fill(ready)
    other = Strategy(key="income-other-" + uuid4().hex, name="Other owner", venue_id=instrument.venue_id,
                     status="paper", allocation_usd=D(100))
    connector.session.add(other)
    connector.session.flush()
    trial = Trial(strategy_id=other.id, mode="paper")
    connector.session.add(trial)
    connector.session.commit()
    result = connector.submit_limit(request_id="other", instrument_id=instrument.id, strategy_id=other.id,
        trial_id=trial.id, side="buy", quantity=D(".3"), limit_price=D(100))
    clock[0] += timedelta(seconds=1)
    api.fill("other", qty=".3")
    connector.refresh(result.order_id)
    guard, _ = scheduled(ready, monkeypatch)
    clock[0] = timestamp("2026-10-01T13:30:00Z")
    venue = connector._venue(lock=True)
    before = e.account_evidence(connector.session, venue, clock[0], guard.sessions)
    assert D(before.details["income_receivable_usd"]) == 45
    assert before.strategy_pnl_offset(other.id) == 15
    event = venue.metadata_[e.NAME]["scheduled_income"][0]
    direct = {k: event[k] for k in ("event_id", "symbol", "recognized_at", "modeled_release_at",
               "amount_per_share", "source_observed_at", "source_receipt")}
    direct.update(strategy_id=strategy.id, quantity_before_ex_open=".6", cash_amount="30",
                  execution_fill=False, broker_credit_verified=False)
    e.save_evidence(venue, income=direct)
    after = e.account_evidence(connector.session, venue, clock[0], guard.sessions)
    assert before == after
    assert after.cash_available == D("9.99")
