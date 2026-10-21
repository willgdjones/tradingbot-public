"""Shared cost guard against isolated, rollback-only real Postgres state."""
from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.conftest import FakeAPI, isolate_alpaca_venue
from tradingbot.ai.jev import INPUT_PRICE_PER_MILLION, MAX_CALL_USD, MODEL_ID, PRICING_VERSION
from tradingbot.connectors.alpaca_paper import (
    AlpacaPaperConnector, OrderRejected, PaperEvidenceUnavailable, PaperGuardContext,
)
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, JevRequest, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.forward.ai_paper_costs import AIPaperCostGuard, account_costs


@pytest.fixture
def setup():
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(session)
        clock = [timestamp("2026-09-30T14:00:00Z")]
        api = FakeAPI(clock)
        connector = AlpacaPaperConnector(session, api, now=lambda: clock[0])
        iid = connector.register_equity("SPY")
        connector.initialize_cash(D(100))
        venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
        strategies, trials = [], []
        for _ in range(2):
            strategy = Strategy(key="cost-fixture-" + uuid4().hex, name="Cost fixture",
                                venue_id=venue.id, status="paper", allocation_usd=D(40))
            session.add(strategy)
            session.flush()
            trial = Trial(strategy_id=strategy.id, mode="paper", code_version="cost-fixture",
                          data_start=clock[0]-timedelta(days=1), status="running", params={})
            session.add(trial)
            session.flush()
            strategies.append(strategy)
            trials.append(trial)
        session.add(FxRate(base="USD", quote="GBP", ts=clock[0]-timedelta(days=1), rate=D(".8"), source="fixture"))
        session.commit()
        yield session, connector, api, clock, iid, venue, strategies, trials
    finally:
        session.close()
        try:
            assert outer.is_active, "Tests must never escape their rollback transaction"
            outer.rollback()
        finally:
            connection.close()


def request(setup, *, trial=0, cost=None, reserved=D(0), status="ok", at=None, correlation=None):
    session, _, _, clock, _, _, _, trials = setup
    at = at or clock[0]
    row = JevRequest(id=str(uuid4()), started_ts=at, billing_month=at.date().replace(day=1),
                     completed_ts=at if status in {"ok", "error"} else None,
                     completed_month=at.date().replace(day=1) if cost is not None else None,
                     correlation_id=correlation or f"paper-trial:{trials[trial].id}:signal-{uuid4().hex}",
                     questions={}, requested_model=MODEL_ID, model_id=MODEL_ID,
                     status=status, actual_usd=cost, reserved_usd=reserved,
                     input_price_per_million=INPUT_PRICE_PER_MILLION, pricing_version=PRICING_VERSION,
                     outcomes={})
    session.add(row)
    session.commit()
    return row


def execute(setup, *, arm=0, side="buy", qty=".1", price="100"):
    session, connector, api, clock, iid, _, strategies, trials = setup
    identity = "cost-" + uuid4().hex
    result = connector.submit_limit(request_id=identity, instrument_id=iid,
        strategy_id=strategies[arm].id, trial_id=trials[arm].id, side=side, quantity=D(qty), limit_price=D(price))
    clock[0] += timedelta(seconds=1)
    api.fill(identity, qty=qty, price=price)
    connector.refresh(result.order_id)
    return session.scalar(select(Fill).where(Fill.order_id == result.order_id))


def test_all_trials_share_daily_fee_rounding_and_model_costs(setup):
    session, _, _, clock, _, venue, strategies, trials = setup
    first = execute(setup)
    second = execute(setup, arm=1)
    model = request(setup, cost=D(".00001428"))
    reserved = request(setup, trial=1, status="uncertain", reserved=MAX_CALL_USD,
                       at=clock[0]-timedelta(days=1))
    trials[0].status = "complete"
    session.commit()
    costs = account_costs(session, venue.id, clock[0])
    assert costs.fee_by_fill == {first.id: D(".01"), second.id: D(0)}
    assert costs.total == D(".01") + D(".00001428") + MAX_CALL_USD
    assert costs.daily == costs.total
    assert costs.by_strategy[strategies[0].id] == D(".01001428")
    assert costs.by_trial[trials[1].id] == MAX_CALL_USD
    assert costs.model_by_request[model.id] == D(".00001428")
    assert costs.unknown_request_ids == (reserved.id,)


def test_actual_fees_on_different_fill_are_not_charged_twice(setup):
    session, _, _, clock, _, venue, _, _ = setup
    buy = execute(setup)
    sell = execute(setup, side="sell")
    buy.fee = D(".03")  # actual total already covers modeled buy+sell fee total
    session.commit()
    costs = account_costs(session, venue.id, clock[0])
    assert costs.total == 0 and costs.fee_by_fill == {buy.id: D(0), sell.id: D(0)}


def test_partial_actual_fee_topup_is_exact_account_day_total(setup):
    session, _, _, clock, _, venue, _, _ = setup
    buy = execute(setup)
    sell = execute(setup, side="sell")
    buy.fee = D(".02")
    session.commit()
    costs = account_costs(session, venue.id, clock[0])
    assert costs.total == D(".01")
    assert sum(costs.fee_by_fill.values()) == costs.total
    assert costs.fee_by_fill[sell.id] == D(".01")


def test_settlement_replaces_reservation_without_double_cost(setup):
    session, _, _, clock, _, venue, _, _ = setup
    row = request(setup, status="pending", reserved=MAX_CALL_USD)
    assert account_costs(session, venue.id, clock[0]).total == MAX_CALL_USD
    row.status, row.actual_usd, row.reserved_usd = "ok", D(".00001428"), D(0)
    row.completed_ts = clock[0]
    session.commit()
    costs = account_costs(session, venue.id, clock[0])
    assert costs.total == D(".00001428") and not costs.unknown_request_ids


def test_refused_provider_call_costs_nothing(setup):
    session, _, _, clock, _, venue, _, _ = setup
    request(setup, status="refused")
    costs = account_costs(session, venue.id, clock[0])
    assert costs.total == 0 and not costs.unknown_request_ids


@pytest.mark.parametrize("kwargs", [
    {"correlation": "paper-trial:bogus:signal"},
    {"status": "uncertain", "reserved": D(0)},
    {"cost": D(".001"), "reserved": MAX_CALL_USD},
    {"status": "refused", "reserved": MAX_CALL_USD},
])
def test_inconsistent_provider_receipts_block_guard(setup, kwargs):
    session, _, _, clock, _, venue, _, _ = setup
    request(setup, **kwargs)
    with pytest.raises(ValueError):
        account_costs(session, venue.id, clock[0])


def test_guard_reads_new_provider_reservation_after_capture(setup):
    session, connector, _, clock, iid, venue, strategies, trials = setup
    guard = AIPaperCostGuard()
    guard.capture(connector, additional=[iid], valid_until=clock[0]+timedelta(seconds=30))
    request(setup, status="pending", reserved=MAX_CALL_USD)
    result = guard(connector, PaperGuardContext(phase="submit", now=clock[0], venue=venue,
        instrument_id=iid, strategy_id=strategies[0].id, trial_id=trials[0].id, side="buy"))
    assert result.cash_available == D("99.99") - MAX_CALL_USD
    assert result.strategy_cash == D("39.99") - MAX_CALL_USD
    assert result.strategy_pnl_offsets[strategies[0].id] == -MAX_CALL_USD
    assert result.daily_pnl_offset == -MAX_CALL_USD
    assert result.marks[iid] == 100


def test_guard_uses_t_plus_one_and_reserves_pending_fee(setup):
    _, connector, _, clock, iid, venue, strategies, trials = setup
    execute(setup)
    execute(setup, side="sell")
    guard = AIPaperCostGuard()
    connector.execution_guard = guard
    guard.capture(connector, additional=[iid])
    result = guard(connector, PaperGuardContext(phase="submit", now=clock[0], venue=venue,
        instrument_id=iid, strategy_id=strategies[0].id, trial_id=trials[0].id, side="buy"))
    assert result.cash_available == D("89.96")  # sold $10 remains unsettled; 3c fees + 1c reserve


def test_stale_marks_and_deadline_cannot_be_rescued_by_new_order_quote(setup):
    _, connector, _, clock, iid, venue, strategies, trials = setup
    guard = AIPaperCostGuard()
    deadline = clock[0] + timedelta(seconds=10)
    guard.capture(connector, additional=[iid], valid_until=deadline)
    clock[0] = deadline
    with pytest.raises(ValueError, match="deadline"):
        guard(connector, PaperGuardContext(phase="submit", now=clock[0], venue=venue,
              instrument_id=iid, strategy_id=strategies[0].id, trial_id=trials[0].id))
    guard.capture(connector, additional=[iid])
    clock[0] += timedelta(seconds=31)
    with pytest.raises(ValueError, match="Stale"):
        guard(connector, PaperGuardContext(phase="refresh", now=clock[0], venue=venue))


def test_stronger_existing_guard_is_preserved(setup):
    session, connector, _, clock, iid, venue, _, _ = setup
    guard = AIPaperCostGuard()
    guard.capture(connector, additional=[iid])
    venue.metadata_ = {**venue.metadata_, "alpaca_paper_v1": {
        **venue.metadata_["alpaca_paper_v1"], "guard_required": "paper_evidence_v1"}}
    session.commit()
    with pytest.raises(ValueError, match="existing evidence guard"):
        guard(connector, PaperGuardContext(phase="refresh", now=clock[0], venue=venue))


def test_model_expense_trips_existing_strategy_kill_before_http_order(setup):
    session, connector, api, clock, iid, _, strategies, trials = setup
    strategies[0].allocation_usd = D(".01")
    session.commit()
    request(setup, cost=D(".002"))
    request(setup, cost=D(".002"))
    guard = AIPaperCostGuard()
    guard.capture(connector, additional=[iid])
    connector.execution_guard = guard
    with pytest.raises(OrderRejected):
        connector.submit_limit(request_id="risk-cost-test", instrument_id=iid,
            strategy_id=strategies[0].id, trial_id=trials[0].id,
            side="buy", quantity=D(".000001"), limit_price=D(100))
    assert not api.submissions
    assert session.get(Strategy, strategies[0].id, populate_existing=True).status == "killed"


def test_fill_is_preserved_when_risk_capture_is_missing(setup):
    session, connector, api, clock, iid, _, strategies, trials = setup
    result = connector.submit_limit(request_id="known-fill", instrument_id=iid,
        strategy_id=strategies[0].id, trial_id=trials[0].id, side="buy", quantity=D(".1"), limit_price=D(100))
    clock[0] += timedelta(seconds=1)
    api.fill("known-fill", qty=".1")
    connector.execution_guard = AIPaperCostGuard()
    with pytest.raises(PaperEvidenceUnavailable):
        connector.refresh(result.order_id)
    assert session.scalar(select(Fill.id).where(Fill.order_id == result.order_id)) is not None


# --- hwm Race 2: concurrent-receipt boundary at the quarter-hour overlap ---

def test_receipt_committed_just_after_view_is_deferred_not_raised(setup):
    session, _, _, clock, _, venue, _, _ = setup
    # A concurrent cohort commits a Jev receipt 0.3 s after this as-of-now view opens.
    request(setup, cost=D(".00001428"), at=clock[0] + timedelta(seconds=0.3))
    costs = account_costs(session, venue.id, clock[0])  # must not raise
    assert costs.total == D(0)  # not in this view; counted on the next read


def test_receipt_beyond_tolerance_still_raises(setup):
    session, _, _, clock, _, venue, _, _ = setup
    request(setup, cost=D(".00001428"), at=clock[0] + timedelta(seconds=5))
    with pytest.raises(ValueError, match="Future provider receipt"):
        account_costs(session, venue.id, clock[0])


def test_fill_committed_just_after_view_is_deferred_not_raised(setup):
    session, _, _, clock, _, venue, _, _ = setup
    fill = execute(setup)  # clock advanced inside; fill_ts is just after the view below
    view = fill.fill_ts - timedelta(seconds=0.3)
    costs = account_costs(session, venue.id, view)  # must not raise
    assert fill.id not in costs.fee_by_fill  # deferred to the next read


def test_fill_beyond_tolerance_still_raises(setup):
    session, _, _, clock, _, venue, _, _ = setup
    fill = execute(setup)
    view = fill.fill_ts - timedelta(seconds=5)
    with pytest.raises(ValueError, match="future paper fill"):
        account_costs(session, venue.id, view)
