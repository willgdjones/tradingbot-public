"""Unit tests for the J1 Jev Gate arm (bead tradingbot-1tc).

Pure logic over a synthetic View/DecisionSpec/answers — no DB, model or broker.
The runner integration for an arm="J1" policy is covered by
tests/forward/test_jev_intraday.py (its FixtureStrategy). Here we pin J1's base
rule, gate, targets/stop and Jev question shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from tradingbot.ai.jev import _validate_questions
from tradingbot.strategy.jev import DecisionSpec, Plan, Target, View
from tradingbot.strategy.jev_j1 import BLOCK_CONFIDENCE, DIMENSIONS, ENTER, SKIP, STOP_ATR_MULTIPLE, J1Gate

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def state(*, close="101", prior_high="100", vol_ratio="1.5", atr="0.5", hurdle="12.5"):
    return {
        "symbol": "x", "session_phase": "morning",
        "features": {"current_close": close, "prior_1h_high": prior_high, "volume_ratio": vol_ratio,
                     "atr14": atr, "ret_1h": "0.01", "ret_1d": "0.02", "rsi14": "61.00",
                     "ema20_pos": "0.004", "realized_vol_15m": "0.0012"},
        "cost": {"spread_bps": "10.0000", "fee_bps": "2.5000", "hurdle_bps": hurdle, "slot_usd": "140"},
    }


def view(states, *, positions=None, entered=frozenset()):
    return View(now=NOW, boundary=NOW, states=states, positions=positions or {},
                available_cash=D("140"), allocation=D("25"), entered_today=entered, memory={})


def ans(choice, confidence=0.9):
    return {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {choice: 1.0}}


def answers(**overrides):
    base = {d: ans("ok") for d in DIMENSIONS}
    base.update(overrides)
    return base


def only_spec(plan: Plan) -> DecisionSpec:
    assert len(plan.decisions) == 1
    return plan.decisions[0]


# --- plan(): base rule + spec shape ----------------------------------------
def test_breakout_emits_one_gated_entry_spec():
    spec = only_spec(J1Gate({}).plan(view({"AAPL": state()})))
    assert spec.key == "J1-AAPL" and spec.skip == SKIP and spec.baseline == ENTER
    assert spec.action_class == "entry" and spec.random_mode == "matched"
    assert set(spec.alternatives) == {ENTER, SKIP} and spec.alternatives[SKIP] == ()
    (target,) = spec.alternatives[ENTER]
    assert target.symbol == "AAPL" and target.stop_distance == STOP_ATR_MULTIPLE * D("0.5")
    assert D(0) < target.fraction <= 1
    # Five Choice gate dimensions, each accepted by the real wrapper validator.
    assert set(spec.questions) == set(DIMENSIONS)
    validated = _validate_questions(spec.questions)
    assert len(validated) == 5 and all(validated[d]["type"] == "choice" for d in DIMENSIONS)
    assert set(spec.questions["data_quality"]["criteria"]) == {"ok", "conflict", "block", "insufficient"}


def test_cost_hurdle_is_stated_in_execution_question():
    spec = only_spec(J1Gate({}).plan(view({"AAPL": state(hurdle="12.5")})))
    assert "12.5" in spec.questions["execution_quality"]["instructions"]
    assert "cost hurdle" in spec.questions["execution_quality"]["instructions"].lower()


@pytest.mark.parametrize("bad", [
    {"close": "99"},                 # below the prior 1h high
    {"close": "100"},                # equal, not strictly above
    {"vol_ratio": "1"},              # not above average
    {"vol_ratio": "0.8"},
])
def test_no_breakout_emits_nothing(bad):
    assert J1Gate({}).plan(view({"AAPL": state(**bad)})).decisions == ()


def test_missing_or_nonpositive_atr_skips():
    assert J1Gate({}).plan(view({"AAPL": state(atr=None)})).decisions == ()
    assert J1Gate({}).plan(view({"AAPL": state(atr="0")})).decisions == ()


def test_missing_feature_skips():
    assert J1Gate({}).plan(view({"AAPL": state(prior_high=None)})).decisions == ()
    assert J1Gate({}).plan(view({"AAPL": None})).decisions == ()


def test_held_or_entered_today_skipped():
    states = {"AAPL": state()}
    assert J1Gate({}).plan(view(states, positions={"AAPL": {"quantity": "1"}})).decisions == ()
    assert J1Gate({}).plan(view(states, entered=frozenset({"AAPL"}))).decisions == ()


def test_multiple_breakouts_distinct_capped():
    states = {s: state() for s in ("AAPL", "MSFT", "NVDA", "XLK", "SPY")}
    plan = J1Gate({}).plan(view(states))
    keys = [d.key for d in plan.decisions]
    assert len(plan.decisions) == 5 and len(set(keys)) == 5 and len(plan.decisions) <= 40


# --- choose(): the gate -----------------------------------------------------
def spec_for(sym="AAPL"):
    return only_spec(J1Gate({}).plan(view({sym: state()})))


def test_all_ok_enters():
    assert J1Gate({}).choose(spec_for(), answers()) == ENTER


def test_any_block_skips():
    assert J1Gate({}).choose(spec_for(), answers(risk_check=ans("block"))) == SKIP
    assert J1Gate({}).choose(spec_for(), answers(data_quality=ans("block", 0.2))) == SKIP


def test_conflict_blocks_only_at_confidence_threshold():
    assert J1Gate({}).choose(spec_for(), answers(market_regime=ans("conflict", 0.55))) == SKIP
    assert J1Gate({}).choose(spec_for(), answers(market_regime=ans("conflict", 0.9))) == SKIP
    assert J1Gate({}).choose(spec_for(), answers(market_regime=ans("conflict", 0.54))) == ENTER


def test_insufficient_and_missing_do_not_block():
    assert J1Gate({}).choose(spec_for(), answers(data_quality=ans("insufficient", 0.99))) == ENTER
    partial = answers()
    del partial["signal_alignment"]
    assert J1Gate({}).choose(spec_for(), partial) == ENTER


def test_default_size_factor_is_one():
    spec = spec_for()
    assert J1Gate({}).size_factor(spec, answers()) == D(1)


def test_block_confidence_constant():
    assert BLOCK_CONFIDENCE == D("0.55")
