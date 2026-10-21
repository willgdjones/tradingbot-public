"""Unit tests for the C01 SPY monthly-trend decision rule (pure)."""
from decimal import Decimal as D

from tradingbot.strategy.spy_monthly_trend import SpyMonthlyTrend


def _strat(L=10, w="0.95"):
    return SpyMonthlyTrend(key=f"c01_L{L}",
                           params={"lookback_months": L, "target_weight": w, "symbol": "SPY"})


def test_warmup_is_cash_until_L_history():
    s = _strat(L=3)
    assert s.decide([D(100)], D(0)) == D(0)
    assert s.decide([D(100), D(101)], D(0)) == D(0)
    # exactly L observations -> rule engages
    assert s.decide([D(100), D(101), D(102)], D(0)) == D("0.95")


def test_above_mean_goes_long_below_goes_cash():
    s = _strat(L=3)
    assert s.decide([D(90), D(100), D(110)], D(0)) == D("0.95")   # 110 > mean 100
    assert s.decide([D(110), D(100), D(90)], D("0.95")) == D(0)   # 90 < mean 100


def test_exact_equality_retains_previous_state():
    s = _strat(L=3)
    # closes 90,100,110 -> current 110? need current == mean. Use 90,110,100 -> mean 100, current 100.
    closes = [D(90), D(110), D(100)]
    assert sum(closes) / 3 == D(100) and closes[-1] == D(100)
    assert s.decide(closes, D("0.95")) == D("0.95")  # was long -> stay long
    assert s.decide(closes, D(0)) == D(0)            # was cash -> stay cash


def test_target_weight_is_configurable():
    s = _strat(L=2, w="0.90")
    assert s.decide([D(100), D(110)], D(0)) == D("0.90")
