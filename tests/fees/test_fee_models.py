"""Published venue examples plus rounding and state regressions.

Sources checked 2026-09-30:
https://docs.polymarket.us/fees
https://docs.polymarket.us/partners/orders/data-model
https://kalshi.com/docs/kalshi-fee-schedule.pdf (effective 2026-07-07)
https://docs.kalshi.com/getting_started/fee_rounding
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from tradingbot.fees import (
    PM_US_STANDARD_2026_09_25,
    FeeFill,
    KalshiOrderFees,
    KalshiSchedule,
    Liquidity,
    PolymarketUSOrderFees,
    Side,
    decode_commission,
)

D = Decimal
AT = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def fill(price="0.5", quantity="1", role="taker", side="buy", at=AT):
    return FeeFill(D(price), D(quantity), Liquidity(role), Side(side), at)


def pm():
    return PolymarketUSOrderFees(PM_US_STANDARD_2026_09_25)


def kalshi(precision="0.01", maker="0", taker="1"):
    return KalshiOrderFees(
        KalshiSchedule("test-resolved-policy", AT, D(taker), D(maker)), D(precision)
    )


@pytest.mark.parametrize("price,taker,maker", [
    ("0.10", "6.26", "-1.12"),
    ("0.65", "15.81", "-2.84"),
    ("0.30", "14.60", "-2.62"),
    ("0.90", "6.26", "-1.12"),
    ("0.50", "17.38", "-3.12"),
])
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_pm_published_thousand_contract_examples(price, taker, maker, side):
    assert pm().charge(fill(price, "1000", side=side)).net_fee == D(taker)
    assert pm().charge(fill(price, "1000", "maker", side)).net_fee == D(maker)


@pytest.mark.parametrize("price,taker,maker", [
    ("0.01", "0.07", "-0.01"),
    ("0.10", "0.63", "-0.11"),
    ("0.20", "1.11", "-0.20"),
    ("0.50", "1.74", "-0.31"),
    ("0.97", "0.20", "-0.04"),
    ("0.99", "0.07", "-0.01"),
])
def test_pm_published_hundred_lot_table(price, taker, maker):
    assert pm().charge(fill(price, "100")).net_fee == D(taker)
    assert pm().charge(fill(price, "100", "maker")).net_fee == D(maker)


def test_pm_execution_report_fractional_quantity_example():
    assert pm().charge(fill("0.97", "3.12")).net_fee == D("0.01")
    assert decode_commission(100, price_scale=100, quantity_scale=100) == D("0.01")
    assert decode_commission(20, price_scale=100, quantity_scale=1) == D("0.20")
    assert decode_commission(-4, price_scale=100, quantity_scale=1) == D("-0.04")
    assert decode_commission(None, price_scale=100, quantity_scale=100) == 0


def test_pm_taker_caps_cumulative_rounding():
    model = pm()
    charges = [model.charge(fill()) for _ in range(4)]
    assert [c.net_fee for c in charges] == list(map(D, ["0.02", "0.01", "0.02", "0.02"]))
    assert charges[1].rounding_rebate == D("0.01")
    assert sum(c.net_fee for c in charges) == D("0.07")
    # A different order starts a new accumulator.
    assert pm().charge(fill()).net_fee == D("0.02")


def test_pm_never_increases_a_fill_to_catch_up():
    model = pm()
    assert all(model.charge(fill("0.01")).net_fee == 0 for _ in range(20))
    assert pm().charge(fill("0.01", "20")).net_fee == D("0.01")


def test_pm_makers_round_independently_and_do_not_pollute_taker_cap():
    model = pm()
    assert model.charge(fill()).net_fee == D("0.02")
    assert model.charge(fill(quantity="2", role="maker")).net_fee == D("-0.01")
    assert model.charge(fill(quantity="2", role="maker")).net_fee == D("-0.01")
    assert model.charge(fill()).net_fee == D("0.01")


@pytest.mark.parametrize("quantity,expected", [("1.6", "0"), ("4.8", "-0.02")])
def test_pm_negative_half_even_ties(quantity, expected):
    assert pm().charge(fill(quantity=quantity, role="maker")).net_fee == D(expected)


@pytest.mark.parametrize("price,one,hundred", [
    ("0.01", "0.01", "0.07"), ("0.05", "0.01", "0.34"),
    ("0.10", "0.01", "0.63"), ("0.15", "0.01", "0.90"),
    ("0.20", "0.02", "1.12"), ("0.25", "0.02", "1.32"),
    ("0.30", "0.02", "1.47"), ("0.35", "0.02", "1.60"),
    ("0.40", "0.02", "1.68"), ("0.45", "0.02", "1.74"),
    ("0.50", "0.02", "1.75"), ("0.55", "0.02", "1.74"),
    ("0.60", "0.02", "1.68"), ("0.65", "0.02", "1.60"),
    ("0.70", "0.02", "1.47"), ("0.75", "0.02", "1.32"),
    ("0.80", "0.02", "1.12"), ("0.85", "0.01", "0.90"),
    ("0.90", "0.01", "0.63"), ("0.95", "0.01", "0.34"),
    ("0.99", "0.01", "0.07"),
])
def test_kalshi_published_table_matches_cent_cleared_case(price, one, hundred):
    assert kalshi().charge(fill(price)).net_fee == D(one)
    assert kalshi().charge(fill(price, "100")).net_fee == D(hundred)


def test_kalshi_official_fractional_price_example():
    result = kalshi().charge(fill("0.055"))
    assert result.exact_fee == D("0.00363825")
    assert result.trade_fee == D("0.003639")
    assert result.rounding_fee == D("0.001361")
    assert result.net_fee == D("0.005")
    # Direct-member precision cannot be inferred from the cent-rounded PDF table.
    assert kalshi("0.0001").charge(fill("0.055")).net_fee == D("0.0037")
    assert kalshi("0.0001").charge(fill("0.01")).net_fee == D("0.0007")


def test_kalshi_side_changes_balance_rounding():
    assert kalshi().charge(fill("0.057", side="buy")).net_fee == D("0.013")
    assert kalshi().charge(fill("0.057", side="sell")).net_fee == D("0.007")


def test_kalshi_accumulator_survives_taker_to_maker_transition():
    model = kalshi(maker="1")
    results = [model.charge(fill()) for _ in range(3)]
    results.append(model.charge(fill(quantity="4", role="maker")))
    assert [x.net_fee for x in results] == list(map(D, ["0.02", "0.02", "0.02", "0.01"]))
    assert results[-1].rounding_rebate == D("0.01")
    assert model.rounding_carry == 0


def test_kalshi_rebate_capped_at_gross_fee_carries_excess_forward():
    model = kalshi()
    for _ in range(3):
        result = model.charge(fill("0.055", role="maker"))
        assert result.net_fee == D("0.005")
        assert result.rounding_rebate == 0
    assert model.rounding_carry == D("0.015")
    result = model.charge(fill())
    assert result.rounding_rebate == D("0.01")
    assert result.net_fee == D("0.01")
    assert model.rounding_carry == D("0.0075")


def test_kalshi_explicit_independent_multipliers():
    assert kalshi().charge(fill(quantity="100", role="maker")).net_fee == 0
    assert kalshi(maker="1").charge(fill(quantity="100", role="maker")).net_fee == D("0.44")
    assert kalshi(maker="2").charge(fill(quantity="100", role="maker")).net_fee == D("0.88")
    assert kalshi(taker="0").charge(fill(quantity="100")).net_fee == 0
    assert kalshi(taker="0.5").charge(fill(quantity="100")).net_fee == D("0.88")


@pytest.mark.parametrize("precision", ["0.01", "0.0001"])
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_kalshi_balance_alignment_and_nonnegative_fees(precision, side):
    model = kalshi(precision, maker="1")
    total_rounding = total_rebates = Fraction(0)
    for i in range(1, 100):
        execution = fill(str(D(i) / 100), "1.23", "maker" if i % 2 else "taker", side)
        result = model.charge(execution)
        revenue = Fraction(execution.price) * Fraction(execution.quantity) * (-1 if side == "buy" else 1)
        assert ((revenue - Fraction(result.net_fee)) / Fraction(precision)).denominator == 1
        assert result.net_fee >= 0
        total_rounding += Fraction(result.rounding_fee)
        total_rebates += Fraction(result.rounding_rebate)
        assert total_rounding - total_rebates == Fraction(model.rounding_carry)


def test_independent_of_ambient_decimal_precision():
    with localcontext() as context:
        context.prec = 2
        assert pm().charge(fill("0.65", "1000")).net_fee == D("15.81")
        assert kalshi().charge(fill("0.055")).trade_fee == D("0.003639")
        assert decode_commission(100, price_scale=100, quantity_scale=100) == D("0.01")


@pytest.mark.parametrize("price", ["0", "1", "-0.1", "1.1", "NaN", "Infinity"])
def test_reject_invalid_prices(price):
    with pytest.raises(ValueError):
        fill(price)


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity"])
def test_reject_invalid_quantities(quantity):
    with pytest.raises(ValueError):
        fill(quantity=quantity)


@pytest.mark.parametrize("value", [0.5, True])
def test_reject_binary_floats_and_bools(value):
    with pytest.raises(TypeError):
        FeeFill(value, D(1), Liquidity.TAKER, Side.BUY, AT)


def test_reject_unknown_role_side_and_naive_time():
    for role, side, at in [("other", "buy", AT), ("maker", "other", AT), ("maker", "buy", AT.replace(tzinfo=None))]:
        with pytest.raises(ValueError):
            FeeFill(D("0.5"), D(1), role, side, at)


def test_schedule_boundaries_are_explicit_and_rejection_does_not_change_state():
    start = PM_US_STANDARD_2026_09_25.effective_from
    model = pm()
    with pytest.raises(ValueError):
        model.charge(fill(at=start - timedelta(microseconds=1)))
    assert model.charge(fill(at=start)).net_fee == D("0.02")
    policy = KalshiSchedule("bounded", AT, D(1), D(0), AT + timedelta(days=1))
    k = KalshiOrderFees(policy, D("0.01"))
    with pytest.raises(ValueError):
        k.charge(fill(at=policy.effective_until))
    assert k.rounding_carry == 0


@pytest.mark.parametrize("precision", ["0", "0.001", "-1", "NaN"])
def test_reject_unknown_clearing_precision(precision):
    with pytest.raises(ValueError):
        kalshi(precision)


def test_reject_excess_revenue_precision_without_mutating_order():
    model = kalshi()
    with pytest.raises(ValueError):
        model.charge(fill("0.1234567"))
    assert model.rounding_carry == 0


@pytest.mark.parametrize("scale", [0, -1, True, 100.0])
def test_commission_scale_must_be_explicit_positive_integer(scale):
    with pytest.raises(ValueError):
        decode_commission(100, price_scale=scale, quantity_scale=100)
