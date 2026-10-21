from datetime import date, timedelta
from decimal import Decimal as D
import json

import pytest

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.forward.c05_readiness import PARAMS, SYMBOLS
from tradingbot.forward.c05_state import action_plans, calendar_plan, dump_core, observe_close, phases, restore_core


def calendar():
    # Synthetic session fixture, not an admissible live exchange calendar.
    day, rows = date(2026, 1, 1), []
    while day <= date(2026, 12, 31):
        if day.weekday() < 5:
            rows.append({"date": str(day), "settlement_date": str(day + timedelta(days=3 if day.weekday() == 4 else 1)),
                         "open": "09:30", "close": "16:00"})
        day += timedelta(days=1)
    return rows


def params():
    return {**PARAMS, **calendar_plan(calendar(), start="2026-10-01T20:50:00Z", through=date(2026, 11, 30)),
            "instrument_ids": {s: i + 1 for i, s in enumerate(SYMBOLS)}, "blackouts": []}


class Context:
    now = timestamp("2026-10-30T20:05:00Z")
    def marked_equity(self): return D(140)
    def position(self, iid): return D(0)


def vintage(day="2026-10-30"):
    return {s: {"last_session": day, "adjusted_closes": ["100"] * 126 + ["101"],
                "observed_at": day + "T20:01:00Z"} for s in SYMBOLS}


def test_future_calendar_monthly_decision_no_backfill_and_finite_terminal():
    plan = params()
    assert plan["session_dates"][0] == "2026-10-02"
    assert "2026-10-30" in plan["month_ends"]
    schedule = phases(plan)
    assert schedule[-1][0] == "2026-11-30:open"
    assert all(p[2] > timestamp(plan["start"]) for p in schedule)
    assert plan["next_session"]["2026-10-30"] == "2026-11-02"


def test_complete_vintage_feeds_unchanged_reactor_and_json_roundtrip_retains_targets():
    plan, ctx = params(), Context()
    core = restore_core(plan)
    # Previous basis deliberately differs; no mixed-basis signal can remain.
    core.history = {s: [D(999)] * 126 for s in SYMBOLS}
    session = next(MarketSession.from_api(r) for r in calendar() if r["date"] == "2026-10-30")
    observe_close(core, ctx, vintage(), session)
    assert set(core.signals.values()) == {True}
    assert set(core.targets.values()) == {D("26.6")}
    assert core.reserve == D(7) and len(core.history["GLD"]) == 127
    saved = json.loads(json.dumps(dump_core(core)))
    restored = restore_core(plan, saved)
    assert dump_core(restored) == saved
    with pytest.raises(ValueError, match="Duplicate"):
        observe_close(restored, ctx, vintage(), session)


def test_equality_is_cash_and_old_vintage_not_today_is_rejected():
    core, ctx = restore_core(params()), Context()
    rows = vintage()
    rows["USO"]["adjusted_closes"][-1] = "100"
    session = next(MarketSession.from_api(r) for r in calendar() if r["date"] == "2026-10-30")
    observe_close(core, ctx, rows, session)
    assert core.signals["USO"] is False and core.targets["USO"] == 0
    with pytest.raises(ValueError, match="today"):
        observe_close(restore_core(params()), ctx, vintage("2026-10-29"), session)


def test_attempted_tags_pending_cash_delay_and_buy_allocations_survive_restart():
    core = restore_core(params())
    core.attempted.add("c05:2026-11-02:1:buy")
    core.pending.add("GLD")
    core.targets["GLD"] = D("26.6")
    core.reasons["GLD"] = "monthly rebalance"
    core.causal_exits.add(("USO", "2026-11-04"))
    core.buy_day, core.buy_allocations = "2026-11-02", {"GLD": (D(12), False)}
    restored = restore_core(params(), json.loads(json.dumps(dump_core(core))))
    assert restored.pending == {"GLD"}
    assert restored.buy_allocations == {"GLD": (D(12), False)}
    assert restored.attempted == core.attempted and restored.causal_exits == core.causal_exits


def action(**changes):
    return {"identity": "SLV:test", "symbol": "SLV", "kind": "share_exchange",
            "announced_at": "2026-10-01T14:00:00Z", "observed_at": "2026-10-01T14:01:00Z",
            "reviewed_at": "2026-10-01T15:00:00Z", "ex_date": "2026-10-08",
            "effective_date": "2026-10-07", "payable_date": "2026-10-07",
            "expected_delivery_date": "2026-10-12", **changes}


def test_c05_local_action_allows_before_ex_payable_and_latest_delivery_endpoint():
    sessions = [MarketSession.from_api(r) for r in calendar()]
    plan = action_plans([action()], sessions, as_of="2026-10-01T16:00:00Z")[0]
    assert plan["decision"] == "2026-10-06" and plan["exit"] == "2026-10-07"
    assert plan["actual_payable"] == "2026-10-07" and plan["reentry"] == "2026-10-13"
    assert plan["endpoint_is_broker_credit"] is False
    null = action_plans([action(payable_date=None, expected_delivery_date=None)], sessions, as_of="2026-10-01T16:00:00Z")[0]
    assert null["actual_payable"] is None and null["reentry"] == "2026-10-09"


def test_late_notice_or_unknown_kind_cannot_create_retrospective_forced_exit():
    sessions = [MarketSession.from_api(r) for r in calendar()]
    with pytest.raises(ValueError, match="causal"):
        action_plans([action(observed_at="2026-10-06T20:01:00Z", reviewed_at="2026-10-06T20:02:00Z")],
                     sessions, as_of="2026-10-06T20:03:00Z")
    with pytest.raises(ValueError, match="Unsupported"):
        action_plans([action(kind="merger")], sessions, as_of="2026-10-01T16:00:00Z")
