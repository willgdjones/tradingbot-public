"""Luck odds: the probability a strategy's result is noise, not edge (PRD §4).

A one-sample Student's t-test of per-trade P&L against a zero-edge null. Pure
stdlib — the Student's t survival function is built from the regularized
incomplete beta function (Numerical Recipes continued fraction), so no scipy.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

_FPMIN = 1e-300
_EPS = 3.0e-16
_MAXIT = 300


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def reg_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_sf(t: float, df: float) -> float:
    """Survival function P(T > t) for Student's t with ``df`` degrees of freedom."""
    if df <= 0:
        raise ValueError("Degrees of freedom must be positive")
    x = df / (df + t * t)
    ib = reg_incomplete_beta(df / 2.0, 0.5, x)
    if t > 0:
        return 0.5 * ib
    if t < 0:
        return 1.0 - 0.5 * ib
    return 0.5


def t_test_pvalue(
    samples: Sequence[Decimal | float],
    mu0: float = 0.0,
    alternative: str = "greater",
) -> float | None:
    """One-sample t-test p-value. ``alternative``: 'greater', 'less', 'two-sided'.

    Returns ``None`` when there are fewer than two samples (a p-value is not
    defined). With zero variance the result is treated as deterministic.
    """
    n = len(samples)
    if n < 2:
        return None
    xs = [float(v) for v in samples]
    mean = sum(xs) / n
    var = sum((v - mean) ** 2 for v in xs) / (n - 1)
    df = n - 1

    if var == 0.0:
        # Deterministic sample: the mean's relation to mu0 decides everything.
        if mean == mu0:
            base = 0.5
        elif mean > mu0:
            base = 0.0
        else:
            base = 1.0
        if alternative == "greater":
            return base
        if alternative == "less":
            return 1.0 - base if base in (0.0, 1.0) else 0.5
        return 0.0 if mean != mu0 else 1.0

    se = math.sqrt(var / n)
    t = (mean - mu0) / se
    if alternative == "greater":
        return student_t_sf(t, df)
    if alternative == "less":
        return 1.0 - student_t_sf(t, df)
    if alternative == "two-sided":
        return 2.0 * student_t_sf(abs(t), df)
    raise ValueError(f"Unknown alternative: {alternative!r}")


def luck_probability(pnls: Sequence[Decimal | float]) -> float | None:
    """Probability the positive result is luck: the one-sided p-value testing
    H0 (edge <= 0) against H1 (edge > 0) over per-trade net P&L. Lower is better.
    ``None`` if fewer than two trades."""
    return t_test_pvalue(pnls, mu0=0.0, alternative="greater")


ZERO = Decimal(0)


def max_drawdown(pnls: Sequence[Decimal]) -> Decimal:
    """Largest peak-to-trough decline of the cumulative-P&L curve, as a
    non-negative USD magnitude (PRD §4: filter survivors on drawdown, not just
    return). ``pnls`` are per-round-trip net P&Ls **in time order**; the curve
    starts flat at 0, so a first losing trip already counts as drawdown. Returns 0
    when the curve never falls below a prior peak (or there are no trips).

    This is the same absolute-equity definition the equity research runtime uses
    (``peak_equity - equity``), so backtest and research drawdowns are comparable.
    """
    peak = equity = worst = ZERO
    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        drop = peak - equity
        if drop > worst:
            worst = drop
    return worst
