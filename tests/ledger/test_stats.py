"""Luck p-value / Student's t-test tests (values cross-checked against scipy)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradingbot.ledger.stats import (
    luck_probability,
    max_drawdown,
    reg_incomplete_beta,
    student_t_sf,
    t_test_pvalue,
)

D = Decimal


def test_reg_incomplete_beta_symmetry_midpoint():
    # I_0.5(a, a) == 0.5 for equal parameters.
    assert reg_incomplete_beta(3.0, 3.0, 0.5) == pytest.approx(0.5, abs=1e-9)


def test_student_t_sf_zero_is_half():
    assert student_t_sf(0.0, 4) == pytest.approx(0.5, abs=1e-12)


def test_student_t_sf_symmetry():
    assert student_t_sf(-1.3, 7) == pytest.approx(1.0 - student_t_sf(1.3, 7), abs=1e-12)


def test_student_t_sf_known_value():
    # P(T>4.242640687) for df=4, computed from the closed form of I_x(2, 1/2):
    # 0.5 * I_{4/22}(2, 0.5) = 0.00661780
    assert student_t_sf(4.242640687, 4) == pytest.approx(0.00661780, abs=1e-6)


def test_student_t_sf_large_df_approaches_normal():
    # For large df the t-tail approaches the normal: P(Z>1.96) ~= 0.0249979
    assert student_t_sf(1.959963985, 5_000_000) == pytest.approx(0.025, abs=1e-4)


def test_t_test_one_sided_known_value():
    # samples 1..5: mean 3, s^2 2.5, t = 3/sqrt(0.5) = 4.2426, df 4 -> sf = 0.00661780
    p = t_test_pvalue([1, 2, 3, 4, 5], mu0=0.0, alternative="greater")
    assert p == pytest.approx(0.00661780, abs=1e-6)


def test_t_test_two_sided_is_double():
    one = t_test_pvalue([1, 2, 3, 4, 5], alternative="greater")
    two = t_test_pvalue([1, 2, 3, 4, 5], alternative="two-sided")
    assert two == pytest.approx(2.0 * one, abs=1e-9)


def test_t_test_symmetric_mean_zero_is_half():
    assert t_test_pvalue([-2, -1, 1, 2], alternative="greater") == pytest.approx(0.5, abs=1e-9)


def test_t_test_needs_two_samples():
    assert t_test_pvalue([1.0]) is None
    assert luck_probability([]) is None


def test_t_test_zero_variance():
    assert t_test_pvalue([2, 2, 2], alternative="greater") == 0.0  # deterministic positive
    assert t_test_pvalue([-2, -2], alternative="greater") == 1.0
    assert t_test_pvalue([0, 0], alternative="greater") == 0.5


def test_luck_probability_accepts_decimal():
    strong = luck_probability([Decimal("1.0"), Decimal("1.1"), Decimal("0.9"), Decimal("1.2")])
    weak = luck_probability([Decimal("1.0"), Decimal("-0.9"), Decimal("0.8"), Decimal("-1.1")])
    assert 0.0 <= strong < 0.05  # consistent winners: unlikely to be luck
    assert weak > 0.2  # noisy: could well be luck


# -- max_drawdown ----------------------------------------------------------
def test_max_drawdown_empty_and_all_positive_is_zero():
    assert max_drawdown([]) == D("0")
    assert max_drawdown([D("1"), D("2"), D("0.5")]) == D("0")


def test_max_drawdown_leading_loss_counts_from_flat():
    # Curve starts at 0, so a first losing trip is already a drawdown.
    assert max_drawdown([D("-3")]) == D("3")


def test_max_drawdown_peak_to_trough():
    # equity: +5, +3 (dd 2), +8 (new peak), +2 (dd 6), +9. Worst = 6.
    pnls = [D("5"), D("-2"), D("5"), D("-6"), D("7")]
    assert max_drawdown(pnls) == D("6")


def test_max_drawdown_is_order_sensitive():
    up_then_down = [D("4"), D("-10")]   # peak 4 -> -6, dd 10
    down_then_up = [D("-10"), D("4")]   # 0 -> -10 (dd 10) -> -6
    assert max_drawdown(up_then_down) == D("10")
    assert max_drawdown(down_then_up) == D("10")
    mixed = [D("2"), D("3"), D("-4")]   # peak 5 -> 1, dd 4
    assert max_drawdown(mixed) == D("4")
