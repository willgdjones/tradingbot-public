from datetime import UTC, datetime
from decimal import Decimal as D

from tradingbot.data.iex_intraday import SYMBOLS
from tradingbot.strategy.ai1_gate import DailyGate, FRACTION
from tradingbot.strategy.jev import View


def view(states, entered=frozenset()):
    at = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)
    return View(at, at, states, {}, D(15), D(15), entered, {})


def test_strongest_eight_are_deterministic_and_slot_bounded():
    states = {s: {"features": {"ret_session": str(D(i)/1000)}, "quality": {"complete_suffix_intervals": 4}}
              for i, s in enumerate(SYMBOLS)}
    core = DailyGate()
    plan = core.plan(view(states))
    assert [s.key for s in plan.decisions] == list(reversed(SYMBOLS[-8:]))
    assert sum(s.alternatives["enter"][0].fraction for s in plan.decisions) == D(".9")
    assert all(s.alternatives["enter"][0].fraction == FRACTION for s in plan.decisions)


def test_missing_features_never_become_signals_and_missing_answers_skip():
    states = {"SPY": {"features": {"ret_session": None}, "quality": {"complete_suffix_intervals": 4}},
              "QQQ": {"features": {"ret_session": "-.01"}, "quality": {"complete_suffix_intervals": 4}}}
    core = DailyGate()
    spec, = core.plan(view(states)).decisions
    assert spec.key == "QQQ"
    assert not core.plan(view(states, frozenset({"QQQ"}))).decisions
    for answer in ({}, {"profit": {"type": "noul", "noul": float("nan")}}, {"profit": {"type": "noul", "noul": .54}}):
        assert core.choose(spec, answer) == "skip"
    assert core.choose(spec, {"profit": {"type": "noul", "noul": .55}}) == "enter"
