"""Independent C-ROX estimator contract checks; no historical market outcomes."""
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest
from threadpoolctl import threadpool_info

from tradingbot.strategy import rox_hmm_regime as rox


PARAMS = {
    "min_obs": 3, "n_states": 2, "features": "ret", "n_iter": 200,
    "tol": 1e-4, "covariance_type": "full", "target_weight": "0.95",
}
RETURNS = [.01, -.02, .03, .25]


@pytest.fixture
def model(monkeypatch):
    class Model:
        def __init__(self):
            self.means_ = np.array([[-.01], [.01]])
            self.covars_ = np.array([[[.01]], [[.02]]])
            self.startprob_ = np.array([.5, .5])
            self.transmat_ = np.array([[.9, .1], [.1, .9]])
            self.monitor_ = SimpleNamespace(
                history=[100., 100.00001], iter=20, n_iter=200, converged=True,
            )
            self.fit_rows = self.inference_rows = None
            self.fit_threads = []

        def fit(self, values):
            self.fit_rows = values.copy()
            self.fit_threads = [p["num_threads"] for p in threadpool_info()]
            return self

        def predict(self, values):
            self.inference_rows = values.copy()
            return np.zeros(len(values), dtype=int)

        def score_samples(self, values):
            raise AssertionError("the amended plan explicitly uses Viterbi")

    value = Model()
    monkeypatch.setattr("hmmlearn.hmm.GaussianHMM", lambda **kwargs: value)
    return value


def test_fit_and_decode_share_the_window_ending_at_deciding_close(model):
    result = rox.infer_regime(RETURNS, PARAMS)
    np.testing.assert_array_equal(model.fit_rows[:, 0], RETURNS)
    np.testing.assert_array_equal(model.inference_rows[:, 0], RETURNS)
    assert result.current_state == result.risk_off_state == 0
    assert not result.long_ok


def test_warmup_counts_usable_features_before_fitting(model):
    with pytest.raises(rox.RegimeUndecided, match="warmup"):
        rox.infer_regime(RETURNS[:2], PARAMS)
    assert model.fit_rows is None
    rox.infer_regime(RETURNS[:3], PARAMS)
    assert len(model.fit_rows) == 3


@pytest.mark.parametrize("history, iteration", [
    ([100., 101.], 200),  # hmmlearn also calls iteration exhaustion converged
    ([100., 99.], 20),  # decreasing likelihood satisfies its delta < tol check
    ([100., float("nan")], 20),
    ([float("inf"), float("inf")], 20),
    ([100.], 1),
])
def test_converged_flag_alone_is_insufficient(model, history, iteration):
    model.monitor_.history = history
    model.monitor_.iter = iteration
    with pytest.raises(rox.RegimeUndecided, match="fit_failed:"):
        rox.infer_regime(RETURNS, PARAMS)


def test_actual_convergence_on_last_allowed_iteration_is_valid(model):
    model.monitor_.iter = 200
    assert rox.infer_regime(RETURNS, PARAMS).current_state == 0


def test_real_estimator_iteration_exhaustion_has_no_decision():
    returns = np.random.default_rng(17).normal(0, .01, 100)
    with pytest.raises(rox.RegimeUndecided, match="fit_failed:"):
        rox.infer_regime(returns, {**PARAMS, "n_iter": 1})


@pytest.mark.parametrize("fault", ["zero_variance", "nan_mean", "nan_off_diagonal", "singular_covariance"])
def test_degenerate_fitted_parameters_have_no_decision(model, fault):
    params = PARAMS
    if fault == "zero_variance":
        model.covars_[0, 0, 0] = 0
    elif fault == "nan_mean":
        model.means_[0, 0] = float("nan")
    else:
        params = {**PARAMS, "features": "retvol", "vol_window": 2}
        model.means_ = np.array([[-.01, .1], [.01, .2]])
        bad = [[.01, float("nan")], [float("nan"), .02]] if fault == "nan_off_diagonal" else [[.01, .01], [.01, .01]]
        model.covars_ = np.array([bad, [[.02, 0], [0, .03]]])
    with pytest.raises(rox.RegimeUndecided, match="fit_failed:"):
        rox.infer_regime(RETURNS, params)


def test_fit_constrains_loaded_numeric_thread_pools(model):
    rox.infer_regime(RETURNS, PARAMS)
    assert model.fit_threads and all(n == 1 for n in model.fit_threads)


def test_risk_off_ties_prefer_larger_return_variance_then_lower_index(model):
    model.means_[:] = -.01
    assert rox.infer_regime(RETURNS, PARAMS).risk_off_state == 1
    model.covars_[:] = .01
    assert rox.infer_regime(RETURNS, PARAMS).risk_off_state == 0


def test_target_and_audit_use_one_inference(monkeypatch):
    calls = []

    def infer(returns, params):
        calls.append(tuple(returns))
        # Deliberately vary successive receipts: a second fit must never supply
        # an audit record inconsistent with the inference used to trade.
        long_ok = len(calls) == 1
        return rox.RegimeInference(2, 1 if long_ok else 0, 0, (-.01, .01), long_ok)

    monkeypatch.setattr(rox, "infer_regime", infer)
    bot = rox.HmmRegimeStrategy({**PARAMS, "symbol_id": 1})
    bot.on_start(None)
    bot._returns = RETURNS.copy()
    bot._decide(SimpleNamespace(meta={"next_open_in_partition": True}), "2026-01-30")
    assert len(calls) == 1
    assert bot._pending == Decimal("0.95")
    assert bot.decisions[-1]["regime"]["long_ok"] is True
    assert bot.decisions[-1]["target_weight"] == "0.95"
