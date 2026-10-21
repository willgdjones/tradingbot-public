from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import math
from types import SimpleNamespace as NS

import pytest

from tradingbot.ledger import report_stats as stats

START = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


def trial(**kwargs):
    result = NS(id=1, strategy_id=1, mode="backtest", status="complete",
        code_version="c05-amendment21-v1", data_start=START, data_end=START+timedelta(days=3),
        final_holdout=True, holdout_start=START-timedelta(days=1),
        params={"slot_usd": "100"}, sharpe=None, win_rate=None, trade_count=3, max_drawdown=D(11),
        metrics={"complete_execution": True, "max_marked_drawdown_usd": "11", "daily_exposure": [
            {"date": (START+timedelta(days=i)).date().isoformat(), "marked_equity_usd": value}
            for i, value in enumerate(("100", "110", "99", "108.9"))]})
    result.__dict__.update(kwargs)
    return result


def test_daily_marked_returns_have_known_sharpe_t_basis_and_do_not_mutate():
    t = trial()
    before = deepcopy(t.__dict__)
    r = stats.trial_statistics(t, [], {})
    assert r["sharpe"] == pytest.approx(math.sqrt(21))
    assert r["oos_t_stat"] == pytest.approx(.5)
    assert r["sharpe_samples"] == r["oos_samples"] == 3
    assert r["max_drawdown"] == 11
    assert r["hit_rate"] is None  # period gains do not become winning trades
    assert "0% cash" in r["sharpe_basis"] and "252" in r["sharpe_basis"]
    assert t.__dict__ == before


@pytest.mark.parametrize("change", [
    {"final_holdout": False}, {"holdout_start": START+timedelta(days=1)}, {"mode": "paper"},
])
def test_training_or_pre_cutoff_or_paper_series_never_becomes_oos(change):
    result = stats.trial_statistics(trial(**change), [], {})
    assert result["sharpe"] is not None
    assert result["oos_t_stat"] is None and result["oos_samples"] == 0


@pytest.mark.parametrize("values", [[], [1], [1, 1], [0, 0], [1, "NaN"], [1, "Infinity"]])
def test_undefined_statistics_remain_null(values):
    assert stats.sample_ratios(values, 252) == (None, None)


def test_malformed_or_future_daily_receipt_cannot_be_silently_filtered():
    for changed in ({"date": "2027-01-01"}, {"marked_equity_usd": "NaN"}, {"date": "2026-01-05"}):
        t = trial()
        t.metrics["daily_exposure"][1].update(changed)
        r = stats.trial_statistics(t, [], {})
        assert r["sharpe"] is r["oos_t_stat"] is None


def test_monthly_returns_exclude_partial_edges_but_preserve_their_equity_effects():
    t = trial(code_version="c08-amendment21-v1", data_end=START.replace(month=5, day=15),
        metrics={"complete_execution": True, "ending_marked_equity_usd": "120.1",
                 "monthly_marked_net_usd": {"2026-01": "10", "2026-02": "11", "2026-03": "-12.1",
                                            "2026-04": "10.89", "2026-05": "0.31"}})
    result = stats.trial_statistics(t, [], {})
    assert result["sharpe"] == pytest.approx(1)
    assert result["oos_t_stat"] == pytest.approx(.5)
    assert result["sharpe_samples"] == 3
    assert "boundary months excluded" in result["sharpe_basis"]
    t.metrics["ending_marked_equity_usd"] = "999"
    assert stats.trial_statistics(t, [], {})["sharpe"] is None
    t.metrics["ending_marked_equity_usd"] = "120.1"
    del t.metrics["monthly_marked_net_usd"]["2026-03"]
    assert stats.trial_statistics(t, [], {})["oos_t_stat"] is None


def test_failed_trial_does_not_gain_statistics_from_partial_or_stored_metrics():
    t = trial(status="failed", sharpe=D(99), win_rate=D(1))
    result = stats.trial_statistics(t, [], {})
    assert all(result[k] is None for k in ("sharpe", "max_drawdown", "hit_rate", "oos_t_stat"))


def test_unknown_scalar_sharpe_keeps_its_unknown_basis_and_is_not_inverted_to_t():
    t = trial(code_version="older-runner", sharpe=D("1.2"), win_rate=D(".5"))
    r = stats.trial_statistics(t, [], {})
    assert r["sharpe"] == 1.2 and r["hit_rate"] == .5
    assert "not recorded" in r["sharpe_basis"]
    assert r["oos_t_stat"] is None


def executions():
    return [NS(id=i, instrument_id=7, trial_id=1, strategy_id=1, mode="backtest",
               fill_ts=START+timedelta(hours=i), side=side, price=D(price), size=D(1),
               fee=D(fee), realized_pnl=D(pnl))
        for i, side, price, fee, pnl in [(1, "buy", "10", ".1", "0"),
            (2, "sell", "10.15", ".1", ".15"), (3, "buy", "10", ".4", "0")]]


def test_net_hit_rate_and_open_fee_realized_drawdown_do_not_invent_sharpe():
    fills = executions()
    trips = stats.execution_trips(fills, {7: D(1)})
    result = stats.execution_statistics(fills, trips)
    assert result["hit_rate"] == 0  # gross winner, net loser
    assert result["hit_rate_samples"] == 1  # still-open cycle is excluded
    assert result["max_drawdown"] == D(".45")
    assert result["sharpe"] is result["oos_t_stat"] is None
    assert stats.execution_statistics([], [])["max_drawdown"] is None


def test_contract_multiplier_and_breakeven_denominator():
    fills = executions()
    assert stats.execution_trips(fills, {7: D(100)})[0].net_pnl == D("14.80")
    trips = [NS(net_pnl=D(1)), NS(net_pnl=D(0)), NS(net_pnl=D(-1))]
    assert stats.execution_statistics([], trips)["hit_rate"] == pytest.approx(1/3)


def test_execution_binding_and_audit_status_remain_explicit():
    fills = executions()
    fills[0].mode = "paper"
    result = stats.trial_statistics(trial(), fills, {7: D(1)})
    assert result["hit_rate"] is result["sharpe"] is None
    status = stats.evidence_status(trial(), NS(config={"evidence_audit": {"promotion_eligible": False}}))
    assert status.startswith("FAILED AUDIT")
    t = trial(); t.metrics["promotion_eligible"] = False
    assert stats.evidence_status(t, NS(config={})).startswith("Research only")


@pytest.mark.parametrize("invalid", [None, "training", "open_cycle", "income_gap", "before_cutoff"])
def test_legacy_final_execution_t_requires_whole_interval_flat_reconciled_pnl(invalid):
    fills = executions()[:2]
    fills[1].price, fills[1].realized_pnl = D(11), D(1)
    fills.extend([NS(id=i, instrument_id=7, trial_id=1, strategy_id=1, mode="backtest",
        fill_ts=START+timedelta(hours=i), side=side, price=D(price), size=D(1), fee=D(".1"), realized_pnl=D(pnl))
        for i, side, price, pnl in [(3, "buy", "10", "0"), (4, "sell", "9", "-1")]])
    t = trial(code_version="equity-research-v1", pnl_after_fees=D("-.4"), trade_count=2)
    if invalid == "training": t.final_holdout = False
    if invalid == "open_cycle": fills[-1].size = D(".5")
    if invalid == "income_gap": t.pnl_after_fees = D(".5")
    if invalid == "before_cutoff": fills[0].fill_ts = t.holdout_start-timedelta(days=1)
    r = stats.trial_statistics(t, fills, {7: D(1)})
    assert r["sharpe"] is None
    if invalid is None:
        assert r["oos_t_stat"] == pytest.approx(-.2)
        assert r["oos_samples"] == 2 and "net USD" in r["oos_basis"]
    else:
        assert r["oos_t_stat"] is None
