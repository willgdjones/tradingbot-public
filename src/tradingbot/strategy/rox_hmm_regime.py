"""C-ROX — deterministic Gaussian-HMM regime filter on SPY. Pure decision logic.

At each month-end, fit a Gaussian HMM on the daily log-return history observed
*strictly before the next execution* (an expanding window, kept inside the
partition), decode the most-likely current state, and hold ``target_weight``
long iff the current state is **not** the lowest-mean-return ("risk-off") state;
otherwise hold cash. It is a regime *filter/overlay* on a passive long, not a
directional forecast.

The model is deterministic: fixed ``random_state``, ``n_iter`` and ``tol`` and a
single-threaded fit (``threadpool_limits(1)``), so the same returns always yield
the same decision (the "AI" framing of the source idea is dropped — there is no
LLM/Jev call). The HMM is fit on, and Viterbi-decoded over, the window that
*ends at the deciding close t*; it is causal precisely because that window
contains no observation after t. A non-converged or degenerate fit (collapsed /
non-finite variance) is a no-decision, not a silent guess. See
``docs/research/48-rox-hmm-regime-plan.md`` (bead ``tradingbot-rox``).

All configuration lives in ``params`` so ``params`` fully determines behaviour
and the holdout version hash covers exactly the decision logic:

    {"n_states": 2|3, "features": "ret"|"retvol", "target_weight": "0.95",
     "min_obs": 756, "vol_window": 20, "n_iter": 200, "tol": 1e-4,
     "covariance_type": "full", "random_state": 0}
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

import numpy as np

from .interface import PlaceOrder, Strategy

ANNUALISER = 252.0
NY = ZoneInfo("America/New_York")
CENT = Decimal("0.01")
# A covariance eigenvalue at or below this is treated as collapsed/degenerate,
# including singular full covariances whose individual variances are positive.
# Daily log-return variance is ~1e-4; a real low-vol regime stays far above this.
DEGENERATE_VAR = 1e-12


class RegimeUndecided(Exception):
    """No regime decision is possible. ``reason`` is ``"warmup"`` (fewer than
    ``min_obs`` usable observations — the strategy stays flat) or
    ``"fit_failed:*"`` (a non-converging/degenerate HMM fit — the runner retains
    the prior position and logs a no-decision). It is never silently ignored."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RegimeInference:
    """Causal regime read at the deciding day (the last row of the feature
    window). ``state_means`` is the fitted mean daily return per state."""

    n_states: int
    current_state: int
    risk_off_state: int
    state_means: tuple
    long_ok: bool


def _features(returns: np.ndarray, feature_set: str, vol_window: int) -> np.ndarray:
    """Feature matrix whose last row is the deciding day. Column 0 is always the
    daily log return, so ``means_[:, 0]`` is the per-state mean return."""
    if feature_set == "ret":
        return returns.reshape(-1, 1)
    if feature_set == "retvol":
        if returns.size <= vol_window:
            return np.empty((0, 2))
        vol = np.full(returns.size, np.nan)
        for i in range(vol_window - 1, returns.size):
            window = returns[i - vol_window + 1 : i + 1]
            vol[i] = window.std(ddof=1) * np.sqrt(ANNUALISER)
        mask = ~np.isnan(vol)
        return np.column_stack([returns[mask], vol[mask]])
    raise ValueError(f"unknown feature_set {feature_set!r}")


def infer_regime(daily_log_returns: Sequence[float], params: dict) -> RegimeInference:
    """Fit the HMM on ``daily_log_returns`` (chronological, ending at the
    deciding day) and return the current-day regime read. Raises
    :class:`RegimeUndecided` on warm-up or a failed/degenerate fit."""
    n_states = int(params.get("n_states", 2))
    feature_set = str(params.get("features", "ret"))
    vol_window = int(params.get("vol_window", 20))
    min_obs = int(params.get("min_obs", 756))

    returns = np.asarray([float(x) for x in daily_log_returns], dtype=float)
    features = _features(returns, feature_set, vol_window)
    if features.shape[0] < min_obs:
        raise RegimeUndecided("warmup")

    from hmmlearn.hmm import GaussianHMM
    from threadpoolctl import threadpool_limits

    model = GaussianHMM(
        n_components=n_states,
        covariance_type=str(params.get("covariance_type", "full")),
        n_iter=int(params.get("n_iter", 200)),
        tol=float(params.get("tol", 1e-4)),
        random_state=int(params.get("random_state", 0)),
    )
    try:
        with threadpool_limits(limits=1):  # single-threaded: deterministic EM
            model.fit(features)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
        raise RegimeUndecided(f"fit_failed:{type(exc).__name__}") from exc
    monitor = getattr(model, "monitor_", None)
    history = list(getattr(monitor, "history", ()))
    # hmmlearn also calls reaching n_iter, or any negative delta, converged.
    # Require finite evidence that EM actually met the frozen tolerance.
    if (monitor is None or not monitor.converged or len(history) < 2
            or not np.all(np.isfinite(history[-2:]))
            or not 0 <= history[-1] - history[-2] < float(params.get("tol", 1e-4))):
        raise RegimeUndecided("fit_failed:not_converged")

    covars = np.asarray(model.covars_)
    var_diag = np.array([np.diag(np.atleast_2d(covars[s])) for s in range(n_states)])
    if not (np.all(np.isfinite(model.means_)) and np.all(np.isfinite(covars))):
        raise RegimeUndecided("fit_failed:nonfinite")
    try:
        eigenvalues = np.linalg.eigvalsh(covars)
    except np.linalg.LinAlgError as exc:
        raise RegimeUndecided("fit_failed:degenerate") from exc
    if float(eigenvalues.min()) <= DEGENERATE_VAR:
        raise RegimeUndecided("fit_failed:degenerate")
    try:
        with threadpool_limits(limits=1):
            state_seq = model.predict(features)  # Viterbi over the window ending at t
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
        raise RegimeUndecided(f"fit_failed:{type(exc).__name__}") from exc

    means = model.means_[:, 0]
    var_ret = var_diag[:, 0]
    # Risk-off = lowest mean return; break ties by higher variance then lower index.
    order = sorted(range(n_states), key=lambda s: (float(means[s]), -float(var_ret[s]), s))
    risk_off = int(order[0])
    current = int(state_seq[-1])
    return RegimeInference(
        n_states=n_states,
        current_state=current,
        risk_off_state=risk_off,
        state_means=tuple(float(m) for m in means),
        long_ok=(current != risk_off),
    )


@dataclass
class HmmRegimeFilter:
    """Pure month-end decision: target weight for the next month given the daily
    log-return history up to (and including) the deciding day's close and the
    currently held weight. Identical code runs in backtest, paper and live."""

    key: str
    params: dict

    @property
    def target(self) -> Decimal:
        return Decimal(str(self.params.get("target_weight", "0.95")))

    def decide(self, daily_log_returns: Sequence[float], prev_weight: Decimal) -> Decimal:
        try:
            inference = infer_regime(daily_log_returns, self.params)
        except RegimeUndecided as undecided:
            if undecided.reason == "warmup":
                return Decimal(0)  # flat until the model is identifiable in-partition
            return prev_weight  # degenerate fit: no-decision, retain prior position
        return self.target if inference.long_ok else Decimal(0)


class HmmRegimeStrategy(Strategy):
    """Event-driven C-ROX runtime: one SPY long/flat position toggled monthly by
    the HMM regime read. It accumulates the daily total-return factor from
    completed closes (so the HMM sees total-return log returns), decides at each
    month-end close, and reaches the target weight at the next session's open as
    a taker order; a regime flip to risk-off sells to flat. The same code runs in
    backtest, paper and live — the pure logic stays in :class:`HmmRegimeFilter`.

    Expected ``params`` adds execution keys to the filter's model keys:
    ``symbol_id`` (int), ``month_ends`` (list of ISO decision days),
    ``slot_usd``, ``cash_reserve_weight``, ``buy_fee_reserve_usd``,
    ``quantity_step``. Expected event ``meta``: ``phase`` ("open"/"close"),
    ``ex_date_distribution`` (default "0"), ``next_open_in_partition`` (on the
    month-end close), ``terminal_open`` (on the partition's last open).
    """

    key = "rox_hmm_regime_filter"

    def on_start(self, ctx):
        self._symbol = int(self.params["symbol_id"])
        self._filter = HmmRegimeFilter(self.key, self.params)
        self._month_ends = set(self.params.get("month_ends", []))
        self._last_close: Decimal | None = None
        self._factor = Decimal(1)
        self._returns: list[float] = []
        self._prev_weight = Decimal(0)
        self._pending: Decimal | None = None
        self._attempted: set[str] = set()
        self.decisions: list[dict] = []
        self.skips: list[dict] = []

    def on_event(self, ctx, event):
        if event.instrument_id != self._symbol:
            return []
        day = event.time.astimezone(NY).date().isoformat()
        phase = event.meta.get("phase")
        if phase == "close":
            self._observe_close(event)
            if day in self._month_ends and day not in self._attempted:
                self._attempted.add(day)
                self._decide(event, day)
            return []
        if phase == "open":
            return self._execute_open(ctx, event, day)
        return []

    def _observe_close(self, event):
        close = event.as_snapshot().reference_price
        dividend = Decimal(str(event.meta.get("ex_date_distribution", "0")))
        if close is None or not close.is_finite() or close <= 0 or not dividend.is_finite() or dividend < 0:
            raise ValueError("invalid completed close/distribution")
        if self._last_close is not None:
            ratio = (close + dividend) / self._last_close
            self._factor *= ratio
            self._returns.append(float(ratio.ln()))  # daily total-return log return
        self._last_close = close

    def _decide(self, event, day):
        if not event.meta.get("next_open_in_partition", False):
            self.skips.append({"date": day, "reason": "month-end entry open outside partition"})
            return
        try:
            inference = infer_regime(self._returns, self.params)
            target_weight = self._filter.target if inference.long_ok else Decimal(0)
            regime = {"current_state": inference.current_state,
                      "risk_off_state": inference.risk_off_state, "long_ok": inference.long_ok,
                      "state_means": [str(m) for m in inference.state_means]}
        except RegimeUndecided as undecided:
            target_weight = Decimal(0) if undecided.reason == "warmup" else self._prev_weight
            regime = {"undecided": undecided.reason}
        self.decisions.append({"date": day, "n_returns": len(self._returns),
                               "prev_weight": str(self._prev_weight),
                               "target_weight": str(target_weight), "regime": regime})
        self._prev_weight = target_weight  # intended stance (execution uses actual position)
        self._pending = target_weight

    def _execute_open(self, ctx, event, day):
        snapshot = ctx.snapshot(self._symbol)
        if snapshot is None:
            return []
        quantity = ctx.position(self._symbol)
        if event.meta.get("terminal_open", False):
            key = day + ":term"
            if quantity > 0 and key not in self._attempted and snapshot.bid and snapshot.bid > 0:
                self._attempted.add(key)
                return [PlaceOrder(instrument_id=self._symbol, side="sell", size=quantity,
                    limit_price=snapshot.bid.quantize(CENT, rounding=ROUND_FLOOR),
                    intended_liquidity="taker", tag="rox:" + key, reason="C-ROX terminal liquidation")]
            return []
        if self._pending is None:
            return []
        target_weight, self._pending = self._pending, None
        if target_weight == 0 and quantity > 0:
            key = day + ":sell"
            if key in self._attempted or snapshot.bid is None or snapshot.bid <= 0:
                return []
            self._attempted.add(key)
            return [PlaceOrder(instrument_id=self._symbol, side="sell", size=quantity,
                limit_price=snapshot.bid.quantize(CENT, rounding=ROUND_FLOOR),
                intended_liquidity="taker", tag="rox:" + key, reason="C-ROX regime->flat")]
        if target_weight > 0 and quantity == 0:
            key = day + ":buy"
            if key in self._attempted or snapshot.ask is None or snapshot.ask <= 0:
                return []
            self._attempted.add(key)
            equity = ctx.marked_equity()
            if equity is None or not equity.is_finite() or equity <= 0:
                raise ValueError("decision-time marked equity is required")
            dollars = min(target_weight * equity, Decimal(str(self.params.get("slot_usd", "140"))))
            reserve = Decimal(str(self.params.get("cash_reserve_weight", "0.05"))) * equity
            cash = ctx.available_cash(self._symbol)
            if cash is None or not cash.is_finite():
                self.skips.append({"date": day, "reason": "unavailable settled cash evidence"})
                return []
            fee_reserve = Decimal(str(self.params.get("buy_fee_reserve_usd", "0.01")))
            budget = min(dollars, max(Decimal(0), cash - reserve - fee_reserve))
            if budget < 1:
                self.skips.append({"date": day, "reason": "under $1 after settled-cash/reserve checks"})
                return []
            limit = snapshot.ask.quantize(CENT, rounding=ROUND_CEILING)
            size = (budget / limit).quantize(Decimal(str(self.params.get("quantity_step", "0.000000001"))),
                                             rounding=ROUND_FLOOR)
            if size * snapshot.ask < 1:
                self.skips.append({"date": day, "reason": "floored order under $1"})
                return []
            return [PlaceOrder(instrument_id=self._symbol, side="buy", size=size, limit_price=limit,
                intended_liquidity="taker", tag="rox:" + key, reason="C-ROX regime->long")]
        return []
