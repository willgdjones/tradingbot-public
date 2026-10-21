"""Derived monthly series for the PBO/DSR coverage gaps (tradingbot-9os)."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tradingbot.backtest.monthly_backfill import (
    DERIVED_KEY,
    EXIT_MONTH,
    MONTH_END,
    Unreconciled,
    backfill,
    from_daily_equity,
    from_fills,
    from_monthly_marks,
    from_monthly_net,
    from_monthly_returns,
)
from tradingbot.backtest.overfitting import SERIES_KEY, ledger_report, selection_families
from tradingbot.db import enums
from tradingbot.db.models import BacktestDataset, Strategy, Trial
from tradingbot.ledger import Ledger


def fill(i, side, price, size, ts, fee="0.01", instrument=1):
    price, size = D(price), D(size)
    return SimpleNamespace(id=i, side=side, price=price, size=size, notional=price * size,
                           fee=D(fee), fill_ts=datetime.fromisoformat(ts), instrument_id=instrument)


def test_fills_book_each_round_trip_in_the_new_york_month_that_closes_it():
    fills = [fill(1, "buy", "100", "2", "2016-01-27T20:59:00+00:00"),
             # 03:00 UTC on 1 Feb is still 31 Jan in New York.
             fill(2, "sell", "103", "2", "2016-02-01T03:00:00+00:00"),
             fill(3, "buy", "50", "1", "2016-02-25T20:59:00+00:00", instrument=2),
             fill(4, "sell", "49", "0.5", "2016-02-29T20:59:00+00:00", instrument=2),
             fill(5, "sell", "48", "0.5", "2016-03-02T20:59:00+00:00", instrument=2)]
    derived = from_fills({"net_usd": "4.45"}, fills)
    assert derived.basis == EXIT_MONTH
    assert derived.months == {"2016-01": D("5.98"), "2016-03": D("-1.53")}
    assert derived.difference == 0

    with pytest.raises(Unreconciled, match="still open"):
        from_fills({"net_usd": "0"}, fills[:-1])
    with pytest.raises(Unreconciled, match="series totals"):
        from_fills({"net_usd": "4.40"}, fills)
    contract = [fill(1, "buy", "0.4", "10", "2026-01-05T15:00:00+00:00"),
                fill(2, "sell", "0.5", "10", "2026-01-06T15:00:00+00:00")]
    contract[0].notional *= 100
    with pytest.raises(Unreconciled, match="multiplier"):
        from_fills({"net_usd": "0.98"}, contract)


RETURNS = {"monthly_returns": [0.0, 0.1, -0.05, 0.02], "start_equity": "100",
           "end_equity": "106.0", "net_pnl": "6.0", "by_year": {"2020": 0.045, "2021": 0.02}}


def test_monthly_returns_end_at_the_partition_and_book_the_terminal_liquidation():
    # The exclusive end at midnight UTC on 1 Feb is still January in New York.
    derived = from_monthly_returns(RETURNS, datetime(2021, 2, 1, tzinfo=UTC))
    assert derived.basis == MONTH_END
    # Marks 100 -> 100 -> 110 -> 104.5 -> 106.59; the open liquidation realised 106.
    assert derived.months == {"2020-10": D(0), "2020-11": D(10), "2020-12": D("-5.5"),
                              "2021-01": D("2.09") - D("0.59")}
    assert derived.notes == {"terminal_residual_usd": "-0.590000", "baseline_month": "2020-09"}
    assert derived.difference == 0


@pytest.mark.parametrize("data_end", [datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 3, 1, tzinfo=UTC),
                                      datetime(2020, 12, 1, tzinfo=UTC)])
def test_monthly_returns_refuse_a_misaligned_calendar(data_end):
    # The baseline year's recorded return pins the alignment: a one-month shift
    # moves a non-zero month across the year end or loses the baseline year.
    with pytest.raises(Unreconciled, match="misaligned"):
        from_monthly_returns(RETURNS, data_end)


def test_monthly_marks_must_chain_from_initial_cash():
    marks = {"2025-09": {"start_equity": "140", "end_equity": "90.51"},
             "2025-10": {"start_equity": "90.51", "end_equity": "90.51"},
             "2025-11": {"start_equity": "90.51", "end_equity": "95"}}
    metrics = {"monthly_marks": marks, "initial_cash": "140", "pnl_after_fees": "-45"}
    derived = from_monthly_marks(metrics)
    assert derived.months == {"2025-09": D("-49.49"), "2025-10": D("0"), "2025-11": D("4.49")}

    broken = copy.deepcopy(metrics)
    broken["monthly_marks"]["2025-11"]["start_equity"] = "91"
    with pytest.raises(Unreconciled, match="chain breaks at 2025-11"):
        from_monthly_marks(broken)
    gap = copy.deepcopy(metrics)
    gap["monthly_marks"]["2026-01"] = gap["monthly_marks"].pop("2025-11")
    with pytest.raises(Unreconciled, match="chain breaks"):
        from_monthly_marks(gap)
    with pytest.raises(Unreconciled, match="initial_cash"):
        from_monthly_marks({**metrics, "initial_cash": "100"})


def daily(date, equity, owned="0"):
    return {"date": date, "marked_equity_usd": equity, "owned_value_usd": owned}


def test_daily_equity_takes_the_last_mark_of_each_month_from_a_flat_start():
    rows = [daily("2006-01-03", "140"), daily("2006-01-31", "141.5", "100"),
            daily("2006-02-01", "139", "100"), daily("2006-02-28", "138.25", "0")]
    metrics = {"daily_exposure": rows, "ending_marked_equity_usd": "138.25",
               "net_usd": "-1.749", "cash_reconciliation_tolerance_usd": "0.002"}
    derived = from_daily_equity(metrics)
    assert derived.months == {"2006-01": D("1.5"), "2006-02": D("-3.25")}
    assert derived.tolerance_usd == D("0.002")

    with pytest.raises(Unreconciled, match="flat"):
        from_daily_equity({**metrics, "daily_exposure": [daily("2006-01-03", "140", "5")] + rows[1:]})
    with pytest.raises(Unreconciled, match="ending_marked_equity_usd"):
        from_daily_equity({**metrics, "ending_marked_equity_usd": "138"})
    with pytest.raises(Unreconciled, match="series totals"):
        from_daily_equity({**metrics, "net_usd": "-1.7"})


def test_exit_month_copy_must_total_net_usd():
    metrics = {"monthly_net_usd": {"2006-01": "0", "2006-02": "1.25"}, "net_usd": "1.25"}
    assert from_monthly_net(metrics).months == {"2006-01": D("0"), "2006-02": D("1.25")}
    with pytest.raises(Unreconciled):
        from_monthly_net({**metrics, "net_usd": "1.30"})


@pytest.fixture()
def family(session):
    tag = uuid.uuid4().hex[:10]
    dataset = BacktestDataset(key=f"backfill-test-{tag}", data_start=datetime(2016, 1, 1, tzinfo=UTC),
                              holdout_start=datetime(2016, 4, 1, tzinfo=UTC),
                              data_end=datetime(2016, 6, 1, tzinfo=UTC))
    strategy = Strategy(key=f"backfill-test-{tag}", name="Backfill test",
                        config={"research_family": f"backfill-test-{tag}"})
    session.add_all([dataset, strategy])
    session.flush()

    def add(*, metrics, final=False, status=enums.TrialStatus.COMPLETE):
        trial = Trial(strategy_id=strategy.id, mode=enums.Mode.BACKTEST, params={}, status=status,
                      dataset_key=dataset.key, holdout_start=dataset.holdout_start,
                      strategy_version=uuid.uuid4().hex, final_holdout=final, metrics=metrics,
                      data_start=dataset.data_start, data_end=dataset.holdout_start)
        session.add(trial)
        session.flush()
        return trial

    return SimpleNamespace(dataset=dataset, strategy=strategy, add=add)


def exit_months(net="1.5"):
    return {"monthly_net_usd": {"2016-01": "0.5", "2016-02": "0", "2016-03": "1.0"},
            "net_usd": net, "trades": 2, "luck": {"p_value": 0.4}}


def test_backfill_adds_only_the_derived_key_to_eligible_training_trials(session, family, instrument_id):
    derivable = family.add(metrics=exit_months())
    final = family.add(metrics=exit_months(), final=True)
    original = family.add(metrics={**exit_months(), SERIES_KEY: {"2016-01": "1.5"}})
    unreconciled = family.add(metrics=exit_months(net="9"))
    failed = family.add(metrics=exit_months(), status=enums.TrialStatus.FAILED)
    nothing = family.add(metrics={"net_usd": "0"})
    traded = family.add(metrics={"net_usd": "0.13", "fills": 2})
    ledger = Ledger(session)
    for side, price, day in (("buy", "0.40", 5), ("sell", "0.42", 9)):
        order = ledger.record_order(instrument_id=instrument_id, strategy_id=family.strategy.id,
                                    trial_id=traded.id, mode=enums.Mode.BACKTEST, side=side,
                                    order_type="limit", size=D(10), limit_price=D(price))
        ledger.record_fill(order=order, price=D(price), size=D(10), liquidity="taker",
                           fill_ts=datetime(2016, 2, day, 15, tzinfo=UTC), fee=D("0.035"),
                           usd_gbp_rate=D("0.8"))
    session.commit()
    before = {t.id: copy.deepcopy(t.metrics) for t in (derivable, final, original, unreconciled,
                                                         failed, nothing, traded)}

    dry = {r["trial_id"]: r["status"] for r in backfill(session, dataset_key=family.dataset.key)}
    assert dry == {derivable.id: "derivable", unreconciled.id: "unreconciled",
                   nothing.id: "no_source", traded.id: "derivable"}
    session.expire_all()
    assert {t.id: t.metrics for t in (derivable, traded)} == {i: before[i] for i in (derivable.id, traded.id)}

    rows = backfill(session, commit=True, dataset_key=family.dataset.key)
    assert {r["trial_id"]: r["status"] for r in rows} == {**dry, derivable.id: "written",
                                                            traded.id: "written"}
    session.expire_all()
    for trial in (derivable, traded):
        metrics = dict(trial.metrics)
        added = metrics.pop(DERIVED_KEY)
        assert metrics == before[trial.id]  # every original key is untouched
        assert added["derived_by"] == "tradingbot-9os" and added["basis"] == EXIT_MONTH
        assert D(added["reference"]["difference"]) == 0
    months = lambda trial: {m: D(v) for m, v in trial.metrics[DERIVED_KEY]["months"].items()}
    assert months(derivable) == {"2016-01": D("0.5"), "2016-02": D(0), "2016-03": D(1)}
    assert months(traded) == {"2016-02": D("0.13")}  # (0.42 - 0.40) x 10 - 2 x 0.035
    for trial in (final, original, unreconciled, failed, nothing):
        assert trial.metrics == before[trial.id]
    # Idempotent: a written trial is no longer a candidate.
    again = backfill(session, commit=True, dataset_key=family.dataset.key)
    assert {r["trial_id"] for r in again} == {unreconciled.id, nothing.id}

    [group] = selection_families(session, dataset_key=family.dataset.key)
    sources = {v.trial_id: v.source for v in group.variants}
    assert sources == {derivable.id: f"{DERIVED_KEY}:{EXIT_MONTH}", original.id: SERIES_KEY,
                       traded.id: f"{DERIVED_KEY}:{EXIT_MONTH}"}
    # The trial's own series wins over a derived one.
    original.metrics = {**original.metrics, DERIVED_KEY: {"months": {"2016-01": "99"}, "basis": "x"}}
    session.flush()
    [group] = selection_families(session, dataset_key=family.dataset.key)
    assert {v.trial_id: dict(v.monthly) for v in group.variants}[original.id] == {"2016-01": 1.5}


def test_short_families_can_be_left_out_of_the_ledger_variance(session, family):
    other = Strategy(key=family.strategy.key + "-short", name="Short",
                     config={"research_family": family.strategy.key + "-short"})
    session.add(other)
    session.flush()
    long_months = [f"{y}-{m:02d}" for y in (2016, 2017, 2018) for m in range(1, 13)]
    for i in range(3):
        family.add(metrics={SERIES_KEY: {m: str((i + 1) * (k % 3 - 1)) for k, m in enumerate(long_months)}})
        session.add(Trial(strategy_id=other.id, mode=enums.Mode.BACKTEST, params={},
                          status=enums.TrialStatus.COMPLETE, dataset_key=family.dataset.key,
                          holdout_start=family.dataset.holdout_start, final_holdout=False,
                          metrics={SERIES_KEY: {"2016-01": str(i), "2016-02": "1", "2016-03": "-2"}}))
    session.flush()

    every = ledger_report(session, dataset_key=family.dataset.key)
    floored = ledger_report(session, dataset_key=family.dataset.key, variance_min_months=36)
    assert every["ledger"]["trials_with_series"] == 6
    assert floored["ledger"]["trials_with_series"] == 3
    assert floored["ledger"]["variance_min_months"] == 36
    assert floored["ledger"]["sharpe_variance"] < every["ledger"]["sharpe_variance"]
    assert len(floored["families"]) == 2  # the floor only changes the variance
