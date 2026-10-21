from decimal import Decimal as D

import pytest

from tradingbot.forward.jev_virtual import matched_size_factors, random_choices
from tradingbot.strategy.jev import DecisionSpec, Plan, Target


def spec(key, **kw):
    return DecisionSpec(key, {"gate": {"type": "noul", "instructions": "Enter?"}},
                        {"skip": (), "enter": (Target("SPY", D(1)),)}, **kw)


def test_frozen_seed_matches_decision_pass_count_not_execution_outcomes():
    plan = Plan(tuple(spec(str(i)) for i in range(10)))
    selected = {str(i): "enter" if i < 3 else "skip" for i in range(10)}
    choices, audit = random_choices(plan, selected, plan, seed="frozen-before-model")
    assert sum(c == "enter" for c in choices.values()) == 3
    assert choices != selected
    assert audit["entry"]["real_passes"] == 3
    assert random_choices(plan, selected, plan, seed="frozen-before-model")[0] == choices


def test_model_unavailable_yields_no_random_entries():
    plan = Plan((spec("one"),))
    choices, audit = random_choices(plan, {}, plan, seed="seed")
    assert choices == {} and audit["entry"]["real_available"] == 0


def test_partial_outage_counts_unavailable_candidates_as_nonpasses():
    plan = Plan(tuple(spec(str(i)) for i in range(10)))
    selected = {"0": "enter", "1": "enter"}  # eight unavailable; total pass rate 20%
    choices, audit = random_choices(plan, selected, plan, seed="seed")
    assert sum(c == "enter" for c in choices.values()) == 2
    assert audit["entry"]["real_candidates"] == 10 and audit["entry"]["real_available"] == 2


def test_different_control_positions_report_candidate_divergence():
    real, virtual = Plan((spec("a"), spec("b"))), Plan((spec("c"), spec("d"), spec("e")))
    _, audit = random_choices(real, {"a": "enter", "b": "skip"}, virtual, seed="seed")
    assert audit["entry"]["virtual_candidates"] == 3
    assert audit["entry"]["selected"] in {1, 2}


def test_regime_draw_includes_cash_even_when_real_pass_rate_is_zero():
    plan = Plan((spec("regime", action_class="regime", random_mode="uniform"),))
    outcomes = {random_choices(plan, {"regime": "skip"}, plan, seed=str(i))[0]["regime"] for i in range(20)}
    assert outcomes == {"skip", "enter"}


def test_regime_control_can_exclude_unavailable_hold_and_include_cash_exit():
    regime = DecisionSpec("regime", {"q": {"type": "noul", "instructions": "Regime?"}},
        {"skip": (), "trend": (Target("SPY", D(1)),), "chop": (Target("QQQ", D(1)),),
         "risk_off": (Target("SPY", D(0)),)}, action_class="regime", random_mode="uniform",
        random_options=("trend", "chop", "risk_off"))
    plan = Plan((regime,))
    outcomes = {random_choices(plan, {"regime": "risk_off"}, plan, seed=str(i))[0]["regime"] for i in range(30)}
    assert outcomes == {"trend", "chop", "risk_off"}


def test_random_domain_cannot_add_an_undeclared_model_option():
    with pytest.raises(ValueError, match="declared"):
        spec("bad", random_mode="uniform", random_options=("enter", "invented"))


def test_model_cannot_invent_targets_or_overallocate_a_code_option():
    with pytest.raises(ValueError):
        Target("FAKE", D(1))
    with pytest.raises(ValueError):
        Target("SPY", D("NaN"))
    with pytest.raises(ValueError):
        DecisionSpec("bad", {"a": {}}, {"skip": (), "buy": (Target("SPY", D(1)), Target("QQQ", D(1)))})


def test_matched_sizes_preserve_passing_code_factor_distribution():
    plan = Plan(tuple(spec(str(i), minimum_size_factor=D(".5")) for i in range(4)))
    selected = {"0": "enter", "1": "enter", "2": "skip", "3": "skip"}
    control = {"0": "skip", "1": "skip", "2": "enter", "3": "enter"}
    factors = matched_size_factors(plan, selected, {"0": ".6", "1": ".9"}, plan, control, seed="sizes")
    assert set(factors) == {"2", "3"} and sorted(factors.values()) == ["0.6", "0.9"]
