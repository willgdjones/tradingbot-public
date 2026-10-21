"""Account evidence cannot loosen execution gates or discard real receipts."""

from decimal import Decimal as D

import pytest
from sqlalchemy import select

from tradingbot.connectors.alpaca_paper import (
    AlpacaPaperConnector, NAME, OrderRejected,
    PaperEvidenceUnavailable, PaperGuardResult,
)
from tradingbot.db.models import Fill, Order
from .conftest import submit


@pytest.mark.parametrize("field,message", [
    ("cash_available", "settled cash"), ("strategy_cash", "allocation"),
])
def test_guard_cash_is_additional_ceiling(ready, field, message):
    connector, api, *_ = ready
    connector.execution_guard = lambda c, context: PaperGuardResult(**{field: D(19)})
    with pytest.raises(OrderRejected, match=message):
        submit(ready)
    assert not api.submissions
    connector.execution_guard = lambda c, context: PaperGuardResult(**{field: D(1000)})
    api.account_row["cash"] = "19"
    with pytest.raises(OrderRejected, match="settled cash"):
        submit(ready)


def test_required_guard_blocks_new_unconfigured_consumer_but_not_idempotency(ready):
    connector, api, clock, instrument, strategy, trial = ready
    result = submit(ready)
    venue = connector._venue(lock=True)
    venue.metadata_ = {**venue.metadata_, NAME: {**venue.metadata_[NAME], "guard_required": "paper_evidence_v1"}}
    connector.session.commit()
    unconfigured = AlpacaPaperConnector(connector.session, api, now=lambda: clock[0])
    args = (unconfigured, api, clock, instrument, strategy, trial)
    assert submit(args).order_id == result.order_id
    with pytest.raises(OrderRejected, match="requires its account evidence"):
        submit(args, request_id="two")
    assert len(api.submissions) == 1


def test_guard_receipt_persists_before_unknown_post_and_is_not_recomputed(ready):
    connector, api, *_ = ready
    seen = []
    def guard(c, context):
        assert c.session.in_transaction() and context.phase == "submit"
        assert context.quote.bid == 100 and context.quantity == D("0.2")
        seen.append(context)
        return PaperGuardResult(details={"cash_policy": "documented-completion"})
    connector.execution_guard = guard
    api.timeout_submit = True
    assert submit(ready).submission_unknown
    result = submit(ready)
    order = connector.session.get(Order, result.order_id)
    assert result.submission_unknown and len(seen) == len(api.submissions) == 1
    assert order.metadata_["account_evidence"]["cash_policy"] == "documented-completion"
    assert connector.cash().reserved == 20


def test_offsets_apply_before_permanent_risk_triggers(ready, monkeypatch):
    connector, api, clock, instrument, strategy, _ = ready
    monkeypatch.setattr(connector.risk, "daily_pnl", lambda *a, **k: D(-51))
    monkeypatch.setattr(connector.risk, "strategy_pnl", lambda sid, *a, **k: D(-41) if sid == strategy.id else D(0))
    connector.execution_guard = lambda c, context: PaperGuardResult(
        daily_pnl_offset=D(2), strategy_pnl_offsets={strategy.id: D(2)},
        marks={instrument.id: D(100)},
    )
    assert submit(ready).status == "open"
    assert not connector.risk.is_strategy_killed(strategy.id)
    assert not connector.risk.daily_halt_active("paper", clock[0].date())
    connector.execution_guard = lambda c, context: PaperGuardResult(
        daily_pnl_offset=D(-1), strategy_pnl_offsets={strategy.id: D(-1)},
    )
    with pytest.raises(OrderRejected, match="killed"):
        submit(ready, request_id="two")
    assert connector.risk.is_strategy_killed(strategy.id)
    assert connector.risk.daily_halt_active("paper", clock[0].date())
    assert len(api.submissions) == 1


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), 1.0])
def test_invalid_guard_money_fails_closed(ready, value):
    connector, api, *_ = ready
    connector.execution_guard = lambda c, context: PaperGuardResult(daily_pnl_offset=value)
    with pytest.raises(OrderRejected, match="Non-finite or non-Decimal"):
        submit(ready)
    assert not api.submissions


def test_refresh_saves_fills_when_guard_fails_and_cancel_remains_available(ready):
    connector, api, *_ = ready
    order = submit(ready)
    api.fill("one", qty="0.1")
    def unavailable(c, context):
        raise ValueError("unavailable portfolio marks")
    connector.execution_guard = unavailable
    with pytest.raises(PaperEvidenceUnavailable):
        connector.refresh(order.order_id)
    assert connector.session.scalar(select(Fill.size).where(Fill.order_id == order.order_id)) == D("0.1")
    assert connector.cash().reserved == 10
    assert connector.cancel(order.order_id).status == "canceled"
    assert len(api.cancellations) == 1
    assert connector.cash().reserved == 0
