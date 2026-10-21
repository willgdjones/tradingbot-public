"""Unit tests for the J4 Jev Regime switcher arm (bead tradingbot-32i).

Pure logic over a synthetic View — no DB, model or broker. Runner integration
for a regime arm is covered by tests/forward/test_jev_intraday.py.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D

from tradingbot.ai.jev import _validate_questions
from tradingbot.data.iex_intraday import NY
from tradingbot.strategy.jev import DecisionSpec, Plan, Target, View
from tradingbot.strategy.jev_j4 import (CHOP, CHOP_FRACTION, ETF_SYMBOLS, REGIMES, RISK_OFF, SKIP, TREND,
                                        TREND_FRACTION, J4Regime)

# ret_1d (momentum) and rsi14 (oversold) for a handful of ETFs.
FEATURES = {
    "SPY": ("0.02", "55"), "QQQ": ("0.03", "70"), "DIA": ("0.025", "40"),
    "IWM": ("0.01", "30"), "XLK": ("-0.01", "25"),
}


def state(ret_1d, rsi14):
    return {"symbol": "x", "session_phase": "morning",
            "features": {"ret_1d": ret_1d, "rsi14": rsi14}}


def view(*, at="09:45", positions=None):
    boundary = datetime(2026, 10, 1, int(at[:2]), int(at[3:]), tzinfo=NY)
    states = {sym: state(r, rsi) for sym, (r, rsi) in FEATURES.items()}
    return View(now=boundary, boundary=boundary, states=states, positions=positions or {},
                available_cash=D("25"), allocation=D("25"), entered_today=frozenset(), memory={})


def only_spec(plan: Plan) -> DecisionSpec:
    assert len(plan.decisions) == 1
    return plan.decisions[0]


def longs(targets):
    return {t.symbol for t in targets if t.fraction > 0}


def exits(targets):
    return {t.symbol for t in targets if t.fraction == 0}


def test_decision_only_at_scheduled_times():
    assert J4Regime({}).plan(view(at="09:45")).decisions != ()
    assert J4Regime({}).plan(view(at="12:30")).decisions != ()
    assert J4Regime({}).plan(view(at="10:00")).decisions == ()
    assert J4Regime({}).plan(view(at="15:45")).decisions == ()


def test_regime_spec_shape_and_baskets():
    spec = only_spec(J4Regime({}).plan(view()))
    assert spec.action_class == "regime" and spec.random_mode == "uniform"
    assert spec.random_options == REGIMES and spec.baseline is None and spec.skip == SKIP
    assert set(spec.alternatives) == {TREND, CHOP, RISK_OFF, SKIP}
    assert spec.alternatives[SKIP] == ()
    # trend = top-3 by 1d momentum; chop = 2 most oversold by RSI
    assert longs(spec.alternatives[TREND]) == {"QQQ", "DIA", "SPY"}
    assert longs(spec.alternatives[CHOP]) == {"XLK", "IWM"}
    assert all(t.fraction == TREND_FRACTION for t in spec.alternatives[TREND] if t.fraction > 0)
    assert all(t.fraction == CHOP_FRACTION for t in spec.alternatives[CHOP] if t.fraction > 0)
    assert J4Regime({}).ungated_twin is False and J4Regime({}).arm == "J4"


def test_question_validates_as_three_way_choice():
    spec = only_spec(J4Regime({}).plan(view()))
    validated = _validate_questions(spec.questions)
    assert set(validated) == {"regime"} and validated["regime"]["type"] == "choice"
    assert set(validated["regime"]["criteria"]) == {TREND, CHOP, RISK_OFF}


def test_held_positions_reconciled_as_exits():
    # Holding GLD (not an ETF candidate in FEATURES) and QQQ (a trend long).
    spec = only_spec(J4Regime({}).plan(view(positions={"GLD": {"quantity": "1"}, "QQQ": {"quantity": "1"}})))
    # risk_off flattens everything held.
    assert exits(spec.alternatives[RISK_OFF]) == {"GLD", "QQQ"} and longs(spec.alternatives[RISK_OFF]) == set()
    # trend keeps QQQ as a long (not an exit) and sells the unheld-elsewhere GLD.
    assert "QQQ" in longs(spec.alternatives[TREND]) and "QQQ" not in exits(spec.alternatives[TREND])
    assert "GLD" in exits(spec.alternatives[TREND])
    # chop (XLK, IWM) sells both held names.
    assert exits(spec.alternatives[CHOP]) == {"GLD", "QQQ"}


def test_missing_features_excluded_from_ranking():
    boundary = datetime(2026, 10, 1, 9, 45, tzinfo=NY)
    states = {"SPY": state("0.02", "55"), "QQQ": state(None, None), "IWM": state("0.01", None)}
    v = View(now=boundary, boundary=boundary, states=states, positions={}, available_cash=D("25"),
             allocation=D("25"), entered_today=frozenset(), memory={})
    spec = only_spec(J4Regime({}).plan(v))
    assert longs(spec.alternatives[TREND]) == {"SPY", "IWM"}   # QQQ has no ret_1d
    assert longs(spec.alternatives[CHOP]) == {"SPY"}            # only SPY has rsi14


def test_choose_returns_model_regime_or_skip():
    spec = only_spec(J4Regime({}).plan(view()))
    for regime in REGIMES:
        assert J4Regime({}).choose(spec, {"regime": {"type": "choice", "choice": regime, "confidence": 0.8}}) == regime
    assert J4Regime({}).choose(spec, {"regime": {"choice": "bogus"}}) == SKIP
    assert J4Regime({}).choose(spec, {}) == SKIP


def test_regime_call_observes_the_rotation_universe_and_held_names():
    held = {"AAPL": {"quantity": "1", "avg_price": "100", "stop_distance": None}}
    spec = only_spec(J4Regime().plan(view(positions=held)))
    scope = J4Regime().observation_symbols(spec)
    assert scope == frozenset(ETF_SYMBOLS) | {"AAPL"}
