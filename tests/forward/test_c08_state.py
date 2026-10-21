from datetime import date
from decimal import Decimal as D

import pytest

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.forward.c08_state import (
    PARAMS, action_plans, calendar_plan, dump_core, eligible_release, phases, restore_core,
)


def rows():
    return [{"date": day, "settlement_date": settled, "open": "09:30", "close": "16:00"}
            for day, settled in [("2026-10-01", "2026-10-02"), ("2026-10-02", "2026-10-05"),
                ("2026-10-05", "2026-10-06"), ("2026-10-06", "2026-10-07"),
                ("2026-10-07", "2026-10-08"), ("2026-10-08", "2026-10-09")]]


def test_calendar_is_finite_and_terminal_has_no_close_order():
    planned = calendar_plan(rows(), start="2026-10-01T21:00:00Z", through=date(2026, 10, 7))
    schedule = phases(planned)
    assert len(schedule) == 7
    assert schedule[0][0] == "2026-10-02:open"
    assert schedule[-1][0] == "2026-10-07:open"
    planned["calendar"][0]["open"] = "09:31"
    with pytest.raises(ValueError, match="changed"):
        phases(planned)


@pytest.mark.parametrize("through", [date(2026, 10, 2), date(2026, 10, 4), date(2026, 10, 8)])
def test_calendar_rejects_incomplete_future_or_settlement_coverage(through):
    with pytest.raises(ValueError):
        calendar_plan(rows(), start="2026-10-01T21:00:00Z", through=through)


def test_reactor_roundtrip_preserves_decimal_pending_target_and_attempts():
    params = {**PARAMS, "uso_id": 1, "blackouts": []}
    core = restore_core(params)
    core.latest = {"key": "publication"}
    core.pending = {"target": D("132.99999999"), "reserve": D("7.00000001"),
                    "decision_equity": D(140), "decision_date": "2026-10-01", "release_key": "publication"}
    core.attempted.add("c08:2026-10-02:buy")
    core.blackout_decisions.add("2026-10-05")
    core.after_forced_exit = True
    state = dump_core(core)
    resumed = restore_core(params, state)
    assert dump_core(resumed) == state
    assert resumed.pending["target"] == D("132.99999999")
    assert resumed.attempted == core.attempted
    resumed.pending["target"] = D(1)
    assert core.pending["target"] == D("132.99999999")
    with pytest.raises(ValueError, match="evaluated"):
        restore_core({**params, "threshold": "-.04"}, state)


def action(**changes):
    return {"identity": "issuer-uso-split", "symbol": "USO", "kind": "reverse_split",
            "announced_at": "2026-10-01T12:00:00Z", "observed_at": "2026-10-01T19:00:00Z",
            "reviewed_at": "2026-10-01T19:01:00Z", "ex_date": "2026-10-06",
            "payable_date": "2026-10-06", **changes}


def test_action_uses_prior_close_and_stays_flat_through_payable():
    plans = action_plans([action()], [MarketSession.from_api(r) for r in rows()], as_of="2026-10-02T20:00:00Z")
    assert plans[0]["decision"] == "2026-10-02"
    assert plans[0]["exit"] == "2026-10-05"
    assert plans[0]["reentry"] == "2026-10-07"


@pytest.mark.parametrize("change", [
    {"reviewed_at": "2026-10-02T20:00:01Z"}, {"kind": "unknown"},
    {"observed_at": "2026-09-30T19:00:00Z"}, {"symbol": "SPY"},
    {"payable_date": "2026-10-09"},
])
def test_late_unknown_conflicting_action_holds(change):
    with pytest.raises(ValueError):
        action_plans([action(**change)], [MarketSession.from_api(r) for r in rows()], as_of="2026-10-05T13:30:00Z")


def eia():
    return {"available_at": "2026-10-01T18:00:00Z", "first_release_vintage_verified": False,
            "layout": {"observation_date": "2026-09-25", "release_date": "2026-09-30"},
            "fields": {"units_verified": True, "commercial_current": "380", "commercial_year_ago": "410"}}


def test_review_must_precede_scheduled_open_not_observation_window():
    source = eia()
    assert eligible_release(source, reviewed_at="2026-10-02T13:30:00Z", scheduled_open="2026-10-02T13:30:00Z") is None
    assert eligible_release(source, reviewed_at="2026-10-02T13:30:01Z", scheduled_open="2026-10-02T13:30:00Z") is None
    result = eligible_release(source, reviewed_at="2026-10-02T13:29:59Z", scheduled_open="2026-10-02T13:30:00Z")
    assert result["available_at"] == timestamp("2026-10-02T13:29:59Z").isoformat()
    assert result["first_release_vintage_verified"] is False


@pytest.mark.parametrize("value", ["0", "NaN", "-1"])
def test_invalid_inventory_cannot_enter_reactor(value):
    source = eia()
    source["fields"]["commercial_year_ago"] = value
    with pytest.raises(ValueError):
        eligible_release(source, reviewed_at="2026-10-01T19:00:00Z", scheduled_open="2026-10-02T13:30:00Z")


@pytest.mark.parametrize("change", [{"amount_per_share": "0"}, {"currency": "EUR"},
    {"reviewed_at": "2026-10-06T13:30:00Z"}, {"payable_date": "2026-10-09"}])
def test_ordinary_income_requires_known_rate_currency_and_payable_coverage(change):
    ordinary = action(**{"kind": "ordinary_cash", "amount_per_share": ".1", "currency": "USD", **change})
    with pytest.raises(ValueError):
        action_plans([ordinary], [MarketSession.from_api(r) for r in rows()], as_of="2026-10-07T13:30:00Z")
