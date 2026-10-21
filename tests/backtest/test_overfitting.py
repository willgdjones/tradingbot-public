"""CSCV PBO and deflated Sharpe over the trials ledger (tradingbot-cs9)."""

from __future__ import annotations

import math
import random
import uuid
from datetime import UTC, datetime
from itertools import combinations
from statistics import NormalDist

import pytest

from tradingbot.backtest.overfitting import (
    cscv_pbo,
    deflated_sharpe,
    expected_max_sharpe,
    family_report,
    probabilistic_sharpe,
    selection_families,
    sharpe,
)
from tradingbot.db import enums
from tradingbot.db.models import BacktestDataset, Strategy, Trial


def noise(rng, rows, variants, drift=()):
    return [[rng.gauss(drift[j] if j < len(drift) else 0.0, 1.0) for j in range(variants)]
            for _ in range(rows)]


def naive_pbo(matrix, blocks):
    """Reference CSCV: Sharpe recomputed from the raw rows of every split."""
    rows, variants = len(matrix), len(matrix[0])
    size, extra = divmod(rows, blocks)
    bounds, start = [], 0
    for b in range(blocks):
        bounds.append(range(start, start + size + (b < extra)))
        start = bounds[-1].stop
    overfit = 0
    splits = list(combinations(range(blocks), blocks // 2))
    for train in splits:
        pick = lambda chosen: [[matrix[i][j] for b in chosen for i in bounds[b]] for j in range(variants)]
        in_sample = [sharpe(c) for c in pick(train)]
        out = [sharpe(c) for c in pick([b for b in range(blocks) if b not in train])]
        best = in_sample.index(max(in_sample))
        below = sum(v < out[best] for v in out) + (sum(v == out[best] for v in out) + 1) / 2
        overfit += below / (variants + 1) <= 0.5
    return overfit / len(splits)


def test_block_sums_match_raw_split_sharpes():
    matrix = noise(random.Random(7), 37, 5)
    for blocks in (4, 6, 8):
        assert cscv_pbo(matrix, blocks)["pbo"] == pytest.approx(naive_pbo(matrix, blocks))


def test_skill_less_variants_overfit_about_half_the_time():
    result = cscv_pbo(noise(random.Random(1), 160, 10), 16)
    assert result["splits"] == math.comb(16, 8)
    assert 0.3 < result["pbo"] < 0.7


def test_one_genuine_edge_is_not_overfit():
    result = cscv_pbo(noise(random.Random(2), 160, 10, drift=(0.5,)), 16)
    assert result["pbo"] < 0.05
    assert result["prob_oos_loss"] < 0.05
    assert result["median_logit"] > 0


def test_blocks_shrink_to_fit_and_degenerate_inputs_are_refused():
    assert cscv_pbo(noise(random.Random(3), 20, 3), 16)["blocks"] == 10
    with pytest.raises(ValueError, match="two variants"):
        cscv_pbo([[1.0]] * 40)
    with pytest.raises(ValueError, match="8 periods"):
        cscv_pbo(noise(random.Random(4), 7, 3))
    with pytest.raises(ValueError, match="identical"):
        cscv_pbo([[0.0, 0.0, 0.0]] * 40)


def test_expected_max_sharpe_matches_the_paper_approximation():
    assert expected_max_sharpe(1, 1.0) == 0.0
    # Bailey & López de Prado's closed form for 100 trials; simulated E[max] is about 2.51.
    assert expected_max_sharpe(100, 1.0) == pytest.approx(2.531, abs=0.002)
    assert expected_max_sharpe(100, 0.25) == pytest.approx(expected_max_sharpe(100, 1.0) / 2)
    assert expected_max_sharpe(10, 1.0) < expected_max_sharpe(1000, 1.0)


def test_probabilistic_sharpe_known_values():
    assert probabilistic_sharpe(0.2, 0.2, 60, 0.0, 3.0) == pytest.approx(0.5)
    z = 0.1 * math.sqrt(100) / math.sqrt(1 + 0.5 * 0.01)
    assert probabilistic_sharpe(0.1, 0.0, 101, 0.0, 3.0) == pytest.approx(NormalDist().cdf(z))
    # Negative skew and fat tails widen the error band, lowering confidence.
    assert probabilistic_sharpe(0.1, 0.0, 101, -1.0, 9.0) < probabilistic_sharpe(0.1, 0.0, 101, 0.0, 3.0)


def test_deflation_grows_with_the_number_of_trials():
    series = [r[0] for r in noise(random.Random(5), 120, 1, drift=(0.25,))]
    one, many = deflated_sharpe(series, 1, 0.01), deflated_sharpe(series, 200, 0.01)
    assert one["benchmark_sharpe"] == 0.0
    assert many["dsr"] < one["dsr"]
    assert deflated_sharpe([0.0] * 30, 5, 0.01)["dsr"] is None


def add_trial(session, dataset, strategy, *, version, monthly=None, final=False,
              status=enums.TrialStatus.COMPLETE):
    trial = Trial(strategy_id=strategy.id, mode=enums.Mode.BACKTEST, params={}, status=status,
                  dataset_key=dataset.key, holdout_start=dataset.holdout_start,
                  strategy_version=version, final_holdout=final,
                  metrics=None if monthly is None else {"monthly_marked_net_usd": monthly})
    session.add(trial)
    session.flush()
    return trial


def test_ledger_families_align_months_and_pick_the_final_version(session):
    tag = uuid.uuid4().hex[:10]
    dataset = BacktestDataset(key=f"pbo-test-{tag}", data_start=datetime(2010, 1, 1, tzinfo=UTC),
                              holdout_start=datetime(2018, 1, 1, tzinfo=UTC),
                              data_end=datetime(2021, 1, 1, tzinfo=UTC))
    strategy = Strategy(key=f"pbo-test-{tag}", name="PBO test",
                        config={"research_family": f"pbo-test-{tag}"})
    session.add_all([dataset, strategy])
    session.flush()
    rng = random.Random(6)
    months = [f"{y}-{m:02d}" for y in range(2010, 2018) for m in range(1, 13)]
    versions = [f"{tag}-v{i}" for i in range(4)]
    trials = []
    for i, version in enumerate(versions):
        series = {m: str(round(rng.gauss(0.4 if i == 2 else 0.0, 1.0), 6)) for m in months}
        if i == 0:  # an exit-month series that omits quiet months
            series = {m: v for k, (m, v) in enumerate(series.items()) if k % 3}
        trials.append(add_trial(session, dataset, strategy, version=version, monthly=series))
    add_trial(session, dataset, strategy, version=f"{tag}-failed", status=enums.TrialStatus.FAILED)
    final = add_trial(session, dataset, strategy, version=versions[2], final=True,
                      monthly={"2018-01": "1"})

    [group] = selection_families(session, dataset_key=dataset.key)
    assert group.family == f"pbo-test-{tag}"
    assert group.attempted == 5
    assert [v.trial_id for v in group.variants] == [t.id for t in trials]
    assert group.final_trial_ids == [final.id]
    assert group.months() == months
    assert group.column(group.variants[0], months)[0] == 0.0

    report = family_report(group, blocks=16, ledger_trials=200, ledger_variance=0.02)
    assert report["months"] == 96 and report["variants"] == 4
    assert report["pbo"]["blocks"] == 16
    [chosen] = report["selected"]
    assert chosen["trial_id"] == trials[2].id and chosen["selected_by"] == "final_holdout"
    assert chosen["dsr_ledger"] < chosen["dsr_family"]
