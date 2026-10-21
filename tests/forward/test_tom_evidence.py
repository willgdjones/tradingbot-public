from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

from forward.test_turn_of_month import setup  # noqa: F401
from tradingbot.connectors.alpaca_paper import NAME as CONNECTOR_NAME
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, Order
from tradingbot.forward.paper_evidence import NAME as EVIDENCE_NAME
from tradingbot.forward.turn_of_month import Runner


def opt_in(runner):
    venue = runner.connector._venue(lock=True)
    venue.metadata_ = {**venue.metadata_, CONNECTOR_NAME: {
        **venue.metadata_[CONNECTOR_NAME], "guard_required": EVIDENCE_NAME}}
    runner.session.commit()


def test_shared_guard_preserves_spy_schedule_and_no_repeat_on_restart(setup):
    runner, api, now = setup
    params = deepcopy(runner.trial().params)
    opt_in(runner)
    now[0] = timestamp("2026-09-25T19:59:00Z")
    assert runner.step() == "open"
    assert api.submissions[0]["qty"] == "0.249000000"
    assert runner.trial().params == params
    restarted = Runner(runner.session, api, runner.trial_id, now=lambda: now[0])
    restarted.step()
    assert len(api.submissions) == 1
    assert restarted.trial().params == params
    order = runner.session.scalar(select(Order).where(Order.trial_id == runner.trial_id))
    assert "account_evidence" in order.metadata_


def test_guard_enabled_spy_retains_known_fills_when_batch_is_stale(setup):
    runner, api, now = setup
    opt_in(runner)
    now[0] = timestamp("2026-09-25T19:59:00Z")
    assert runner.step() == "open"
    order = runner.orders()[0]
    now[0] += timedelta(seconds=1)
    api.fill(order.metadata_["client_order_id"][4:], qty=".249")
    api.quote_age = timedelta(seconds=31)
    assert runner.step() == "evidence_hold"
    assert runner.session.scalar(select(Fill.id).where(Fill.order_id == order.id)) is not None
    assert runner.session.get(Order, order.id).status == "filled"
    assert len(api.submissions) == 1
    api.quote_age = timedelta(0)
    runner.step()
    assert D(runner.state()["modeled_regulatory_fees"]) == D(".01")
    assert D(runner.state()["net_with_fee_scenario"]) == D("-.01")


def test_account_cash_does_not_grow_when_spy_joins_shared_guard(setup):
    runner, api, now = setup
    before = runner.connector.cash()
    opt_in(runner)
    runner.step()
    assert runner.connector.cash() == before
    assert not api.submissions
    now[0] = timestamp("2026-09-25T20:01:00Z")
    assert runner.step() == "outside_session"
    assert not api.submissions


def test_stale_spy_evidence_holds_before_claim_then_missed_window_recorded(setup):
    runner, api, now = setup
    opt_in(runner)
    now[0] = timestamp("2026-09-25T19:59:00Z")
    api.quote_age = timedelta(seconds=31)
    assert runner.step() == "evidence_hold"
    assert "2026-09-25" not in runner.state()["attempts"]
    now[0] = timestamp("2026-09-25T20:01:00Z")
    assert runner.step() == "outside_session"
    assert runner.state()["attempts"]["2026-09-25"]["status"] == "missed_window"
    assert not api.submissions
