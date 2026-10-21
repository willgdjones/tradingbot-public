"""Pure-logic tests for the C-ROX HMM regime filter (tradingbot-rox).

No DB or price pipeline: the decision is a pure function of a daily log-return
series. Synthetic series use two clearly separated regimes (calm bull vs
turbulent bear) so the fitted labelling is robust and deterministic.
"""
from decimal import Decimal

import numpy as np

from tradingbot.strategy.rox_hmm_regime import (
    HmmRegimeFilter,
    RegimeUndecided,
    infer_regime,
)

BULL = {"mean": 0.0008, "sd": 0.005, "n": 240}   # positive drift, low vol
BEAR = {"mean": -0.0015, "sd": 0.025, "n": 240}  # negative drift, high vol
MIN_OBS = 150  # small so the synthetic series is enough; production default is 756


def _block(spec, rng):
    return rng.normal(spec["mean"], spec["sd"], spec["n"])


def _returns(order):
    rng = np.random.default_rng(0)
    return np.concatenate([_block(BULL if tag == "bull" else BEAR, rng) for tag in order])


def _params(**over):
    base = {"n_states": 2, "features": "ret", "target_weight": "0.95",
            "min_obs": MIN_OBS, "n_iter": 200, "tol": 1e-4,
            "covariance_type": "full", "random_state": 0}
    base.update(over)
    return base


def test_ends_calm_goes_long():
    returns = _returns(["bull", "bear", "bull"])  # current day is calm
    bot = HmmRegimeFilter("rox-test", _params())
    assert bot.decide(returns, Decimal(0)) == Decimal("0.95")


def test_ends_turbulent_goes_flat():
    returns = _returns(["bull", "bear"])  # current day is in the bear regime
    bot = HmmRegimeFilter("rox-test", _params())
    assert bot.decide(returns, Decimal("0.95")) == Decimal(0)


def test_risk_off_is_lowest_mean_return():
    returns = _returns(["bull", "bear"])
    inference = infer_regime(returns, _params())
    lowest = min(range(inference.n_states), key=lambda s: inference.state_means[s])
    assert inference.risk_off_state == lowest


def test_warmup_is_flat_and_raises_warmup():
    returns = _returns(["bull"])[:MIN_OBS - 10]  # fewer than min_obs observations
    bot = HmmRegimeFilter("rox-test", _params())
    assert bot.decide(returns, Decimal("0.95")) == Decimal(0)
    try:
        infer_regime(returns, _params())
        raise AssertionError("expected RegimeUndecided")
    except RegimeUndecided as undecided:
        assert undecided.reason == "warmup"


def test_deterministic_across_repeat_fits():
    returns = _returns(["bull", "bear", "bull"])
    a = infer_regime(returns, _params())
    b = infer_regime(returns, _params())
    assert (a.current_state, a.risk_off_state) == (b.current_state, b.risk_off_state)
    assert a.state_means == b.state_means


def test_decide_retains_prior_on_fit_failure(monkeypatch):
    import tradingbot.strategy.rox_hmm_regime as rox

    def boom(returns, params):
        raise RegimeUndecided("fit_failed:not_converged")

    monkeypatch.setattr(rox, "infer_regime", boom)
    bot = HmmRegimeFilter("rox-test", _params())
    # A failed/degenerate fit is a no-decision: keep whatever was held, never guess.
    assert bot.decide([0.0] * 10, Decimal("0.95")) == Decimal("0.95")
    assert bot.decide([0.0] * 10, Decimal(0)) == Decimal(0)


def test_retvol_feature_set_classifies():
    returns = _returns(["bull", "bear"])  # ends turbulent
    bot = HmmRegimeFilter("rox-test", _params(features="retvol", vol_window=20))
    assert bot.decide(returns, Decimal("0.95")) == Decimal(0)


def test_three_state_runs():
    returns = _returns(["bull", "bear", "bull"])
    bot = HmmRegimeFilter("rox-test", _params(n_states=3))
    assert bot.decide(returns, Decimal(0)) in (Decimal(0), Decimal("0.95"))
