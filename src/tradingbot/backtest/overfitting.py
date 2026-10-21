"""Backtest-overfitting checks over the trials ledger (tradingbot-cs9).

Two multiple-testing checks, reported as promotion evidence
(``docs/promotion-checklist.md`` §2):

* **PBO**, the probability of backtest overfitting, estimated by combinatorially
  symmetric cross-validation (CSCV; Bailey, Borwein, López de Prado & Zhu 2014,
  "The Probability of Backtest Overfitting"). The training months are cut into
  ``S`` contiguous blocks. Every choice of ``S/2`` blocks is an in-sample set and
  its complement is out-of-sample. PBO is the share of splits in which the
  variant with the best in-sample Sharpe ranks at or below the out-of-sample
  median.
* **DSR**, the deflated Sharpe ratio (Bailey & López de Prado 2014, "The Deflated
  Sharpe Ratio"). It is the probabilistic Sharpe ratio of the chosen variant,
  measured against the Sharpe that the best of ``N`` skill-less trials would be
  expected to reach given the spread of the trials' Sharpe ratios.

A *selection family* is the set of completed training trials (``final_holdout``
false) that share a dataset split and a holdout family
(:func:`tradingbot.backtest.holdout.family_identity`). The chosen variant is the
training trial whose ``strategy_version`` matches the family's final-holdout
trial; with no final trial, it is the best full-sample in-sample Sharpe.

Inputs are each trial's ``metrics.monthly_marked_net_usd``. A trial without one
falls back to ``metrics.monthly_net_usd_derived``, which
:mod:`tradingbot.backtest.monthly_backfill` derives from the trial's own recorded
evidence and reconciles with its net result (tradingbot-9os). Sharpe ratios are per
month and computed on USD P&L, which equals the return Sharpe only while the
allocation is constant; compounding books drift from that. Trials with neither
series cannot enter either check and are counted separately.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from itertools import combinations
from statistics import NormalDist

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutViolation, family_identity
from tradingbot.db import enums
from tradingbot.db.models import Strategy, Trial

EULER_GAMMA = 0.5772156649015329
SERIES_KEY = "monthly_marked_net_usd"
DERIVED_KEY = "monthly_net_usd_derived"
DEFAULT_BLOCKS = 16
_NORMAL = NormalDist()


def _sharpe_from_sums(n: int, total: float, squares: float) -> float:
    """Per-period Sharpe (mean / sample std) from count, sum and sum of squares.

    A flat series has Sharpe 0; a constant non-zero series is ±inf, so it still
    ranks above or below every variable one."""
    if n < 2:
        return 0.0
    mean = total / n
    variance = max(squares - total * total / n, 0.0) / (n - 1)
    if variance <= 1e-12 * max(squares / n, 1e-300):
        return 0.0 if mean == 0 else math.copysign(math.inf, mean)
    return mean / math.sqrt(variance)


def sharpe(values: Sequence[float]) -> float:
    """Per-period Sharpe ratio of a series (mean / sample standard deviation)."""
    return _sharpe_from_sums(len(values), math.fsum(values), math.fsum(v * v for v in values))


def moments(values: Sequence[float]) -> tuple[float, float] | None:
    """Skewness and (non-excess) kurtosis from population moments; None if flat."""
    n = len(values)
    if n < 2:
        return None
    mean = math.fsum(values) / n
    m2 = math.fsum((v - mean) ** 2 for v in values) / n
    if m2 <= 0:
        return None
    m3 = math.fsum((v - mean) ** 3 for v in values) / n
    m4 = math.fsum((v - mean) ** 4 for v in values) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def _average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks, ascending (1 = worst), with ties sharing their average rank."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def cscv_pbo(matrix: Sequence[Sequence[float]], blocks: int = DEFAULT_BLOCKS) -> dict:
    """CSCV probability of backtest overfitting for a T x N matrix (rows are
    periods in time order, columns are variants).

    ``blocks`` (S) is reduced to the largest even number that leaves at least two
    rows per block, and must stay at least 4. In-sample ties go to the first
    column; out-of-sample ranks share ties. A logit of exactly 0 (the median)
    counts as overfit, as in the paper's integral up to and including 0."""
    rows = len(matrix)
    variants = len(matrix[0]) if rows else 0
    if variants < 2:
        raise ValueError("PBO needs at least two variants")
    if any(len(row) != variants for row in matrix):
        raise ValueError("ragged return matrix")
    if all(len(set(row)) == 1 for row in matrix):
        raise ValueError("every variant has identical returns; selection is uninformative")
    blocks = min(blocks, rows // 2) // 2 * 2
    if blocks < 4:
        raise ValueError(f"PBO needs at least 8 periods, got {rows}")

    size, extra = divmod(rows, blocks)
    stats = []  # per block: (rows, sums per variant, sums of squares per variant)
    start = 0
    for b in range(blocks):
        stop = start + size + (b < extra)
        part = matrix[start:stop]
        stats.append((len(part),
                      [math.fsum(r[j] for r in part) for j in range(variants)],
                      [math.fsum(r[j] * r[j] for r in part) for j in range(variants)]))
        start = stop

    def performance(chosen: Sequence[int]) -> list[float]:
        n = sum(stats[b][0] for b in chosen)
        return [_sharpe_from_sums(n, math.fsum(stats[b][1][j] for b in chosen),
                                  math.fsum(stats[b][2][j] for b in chosen))
                for j in range(variants)]

    logits, losses = [], 0
    for train in combinations(range(blocks), blocks // 2):
        test = [b for b in range(blocks) if b not in train]
        in_sample, out_of_sample = performance(train), performance(test)
        best = max(range(variants), key=in_sample.__getitem__)
        omega = _average_ranks(out_of_sample)[best] / (variants + 1)
        logits.append(math.log(omega / (1 - omega)))
        losses += out_of_sample[best] < 0
    logits.sort()
    half = len(logits) // 2
    median = logits[half] if len(logits) % 2 else (logits[half - 1] + logits[half]) / 2
    return {
        "pbo": sum(v <= 0 for v in logits) / len(logits),
        "median_logit": median,
        "prob_oos_loss": losses / len(logits),
        "splits": len(logits),
        "blocks": blocks,
        "periods": rows,
        "variants": variants,
    }


def expected_max_sharpe(trials: int, variance: float) -> float:
    """Expected maximum Sharpe of ``trials`` skill-less trials whose Sharpe
    estimates have the given variance (the DSR benchmark SR0)."""
    if trials <= 1 or variance <= 0:
        return 0.0
    return math.sqrt(variance) * ((1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / trials)
                                  + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (trials * math.e)))


def probabilistic_sharpe(observed: float, benchmark: float, periods: int,
                         skew: float, kurtosis: float) -> float | None:
    """Probability that the true per-period Sharpe exceeds ``benchmark``, given
    the observed Sharpe over ``periods`` and the series' skew and kurtosis."""
    if periods < 2 or not math.isfinite(observed):
        return None
    spread = 1 - skew * observed + (kurtosis - 1) / 4 * observed ** 2
    if spread <= 0:
        return None
    return _NORMAL.cdf((observed - benchmark) * math.sqrt(periods - 1) / math.sqrt(spread))


def deflated_sharpe(values: Sequence[float], trials: int, sharpe_variance: float) -> dict:
    """Deflated Sharpe ratio of a selected series after ``trials`` attempts."""
    observed = sharpe(values)
    shape = moments(values)
    benchmark = expected_max_sharpe(trials, sharpe_variance)
    dsr = None if shape is None else probabilistic_sharpe(observed, benchmark, len(values), *shape)
    return {"sharpe": observed, "benchmark_sharpe": benchmark, "trials": trials,
            "sharpe_variance": sharpe_variance, "dsr": dsr}


def sample_variance(values: Sequence[float]) -> float:
    finite = [v for v in values if math.isfinite(v)]
    if len(finite) < 2:
        return 0.0
    mean = math.fsum(finite) / len(finite)
    return math.fsum((v - mean) ** 2 for v in finite) / (len(finite) - 1)


# ---------------------------------------------------------------------------
# Trials-ledger adapter
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Variant:
    trial_id: int
    strategy_key: str
    strategy_version: str | None
    monthly: Mapping[str, float]
    source: str = SERIES_KEY  # or "monthly_net_usd_derived:<basis>"


@dataclass
class SelectionFamily:
    dataset_key: str
    family: str
    variants: list[Variant] = field(default_factory=list)
    attempted: int = 0  # every non-final training trial, including failures
    final_trial_ids: list[int] = field(default_factory=list)
    final_versions: set[str] = field(default_factory=set)

    def months(self) -> list[str]:
        """Every calendar month from the family's first to last recorded month.

        Series that book P&L by exit month omit quiet months, so a month absent
        from a variant's series is zero P&L (see :meth:`column`)."""
        recorded = {m for v in self.variants for m in v.monthly}
        if not recorded:
            return []
        year, month = map(int, min(recorded).split("-"))
        last, out = max(recorded), []
        while (current := f"{year:04d}-{month:02d}") <= last:
            out.append(current)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return out

    def column(self, variant: Variant, months: Sequence[str]) -> list[float]:
        return [variant.monthly.get(m, 0.0) for m in months]


def _month_map(series) -> dict[str, float] | None:
    if not isinstance(series, dict) or not series:
        return None
    return {month: float(Decimal(str(value))) for month, value in series.items()}


def _monthly(metrics: dict | None) -> tuple[dict[str, float], str] | None:
    """The trial's own monthly series, else its derived one, with its source."""
    metrics = metrics or {}
    if (original := _month_map(metrics.get(SERIES_KEY))) is not None:
        return original, SERIES_KEY
    derived = metrics.get(DERIVED_KEY)
    if isinstance(derived, dict) and (series := _month_map(derived.get("months"))) is not None:
        return series, f"{DERIVED_KEY}:{derived.get('basis')}"
    return None


def selection_families(session: Session, *, dataset_key: str | None = None) -> list[SelectionFamily]:
    """Group backtest trials into selection families (dataset split x holdout family)."""
    query = (select(Trial, Strategy).join(Strategy, Strategy.id == Trial.strategy_id)
             .where(Trial.mode == enums.Mode.BACKTEST, Trial.dataset_key.is_not(None))
             .order_by(Trial.id))
    if dataset_key is not None:
        query = query.where(Trial.dataset_key == dataset_key)
    families: dict[tuple[str, str], SelectionFamily] = {}
    for trial, strategy in session.execute(query):
        try:
            family = family_identity(strategy, trial.params or {})[0]
        except HoldoutViolation:
            family = trial.dataset_key  # legacy rows without a declared family
        group = families.setdefault((trial.dataset_key, family),
                                    SelectionFamily(trial.dataset_key, family))
        if trial.final_holdout:
            group.final_trial_ids.append(trial.id)
            if trial.strategy_version:
                group.final_versions.add(trial.strategy_version)
            continue
        group.attempted += 1
        found = _monthly(trial.metrics)
        if trial.status == enums.TrialStatus.COMPLETE and found is not None:
            group.variants.append(Variant(trial.id, strategy.key, trial.strategy_version, *found))
    return list(families.values())


def ledger_trial_count(session: Session) -> int:
    """Completed non-final backtest trials anywhere in the ledger: the widest
    honest count of how many variants this project has tried."""
    return session.scalar(select(func.count()).select_from(Trial).where(
        Trial.mode == enums.Mode.BACKTEST, Trial.status == enums.TrialStatus.COMPLETE,
        Trial.final_holdout.is_(False)))


def _finite(value: float | None) -> float | None:
    return value if value is None or math.isfinite(value) else None


def family_report(group: SelectionFamily, *, blocks: int = DEFAULT_BLOCKS,
                  ledger_trials: int | None = None, ledger_variance: float | None = None) -> dict:
    months = group.months()
    columns = [group.column(v, months) for v in group.variants]
    sharpes = [sharpe(c) for c in columns]
    report = {
        "dataset_key": group.dataset_key, "family": group.family,
        "attempted": group.attempted, "variants": len(columns), "months": len(months),
        "first_month": months[0] if months else None, "last_month": months[-1] if months else None,
        "final_trial_ids": group.final_trial_ids,
        "series_sources": sorted({v.source for v in group.variants}),
        "variant_sharpes": {v.trial_id: _finite(s) for v, s in zip(group.variants, sharpes)},
        "pbo": None, "selected": None,
    }
    if len(columns) >= 2:
        try:
            report["pbo"] = cscv_pbo([list(row) for row in zip(*columns)], blocks)
        except ValueError as exc:
            report["pbo_error"] = str(exc)
    chosen = [i for i, v in enumerate(group.variants) if v.strategy_version in group.final_versions]
    if not columns:
        return report
    if chosen:
        by = "final_holdout"
    else:
        chosen = [max(range(len(columns)), key=sharpes.__getitem__)]
        by = "best_in_sample"
    selected = []
    for i in chosen:
        values = columns[i]
        family = deflated_sharpe(values, len(columns), sample_variance(sharpes))
        entry = {"trial_id": group.variants[i].trial_id, "strategy_key": group.variants[i].strategy_key,
                 "selected_by": by, "sharpe_monthly": _finite(family["sharpe"]),
                 "sharpe_annualized": _finite(family["sharpe"] * math.sqrt(12)),
                 "dsr_family": family["dsr"], "benchmark_family": family["benchmark_sharpe"]}
        if ledger_trials is not None and ledger_variance is not None:
            wide = deflated_sharpe(values, ledger_trials, ledger_variance)
            entry.update(dsr_ledger=wide["dsr"], benchmark_ledger=wide["benchmark_sharpe"])
        selected.append(entry)
    report["selected"] = selected
    return report


def ledger_report(session: Session, *, blocks: int = DEFAULT_BLOCKS,
                  dataset_key: str | None = None, variance_min_months: int = 0) -> dict:
    """``variance_min_months`` keeps families with fewer months out of the
    ledger-wide Sharpe variance. Under no skill a Sharpe estimate's variance is
    about 1/T, so a few short series can dominate it and over-deflate long ones."""
    groups = selection_families(session, dataset_key=dataset_key)
    all_sharpes = [sharpe(g.column(v, months)) for g in groups if g.variants
                   and len(months := g.months()) >= variance_min_months for v in g.variants]
    trials = ledger_trial_count(session)
    variance = sample_variance(all_sharpes)
    return {
        "generated_ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "series": SERIES_KEY, "derived_series": DERIVED_KEY, "blocks": blocks,
        "ledger": {"completed_training_trials": trials, "trials_with_series": len(all_sharpes),
                   "sharpe_variance": variance, "variance_min_months": variance_min_months},
        "families": [family_report(g, blocks=blocks, ledger_trials=trials, ledger_variance=variance)
                     for g in groups if g.variants],
        "families_without_series": sorted({g.dataset_key if g.family == g.dataset_key
                                           else f"{g.dataset_key} [{g.family}]"
                                           for g in groups if not g.variants}),
    }


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def format_report(report: dict) -> str:
    lines = [f"{'family':<34} {'N':>3} {'T':>4} {'PBO':>5} {'P(loss)':>7} {'trial':>6} "
             f"{'SR/yr':>6} {'DSR(N)':>6} {'DSR(L)':>6}"]
    for fam in sorted(report["families"], key=lambda f: f["family"]):
        pbo = fam["pbo"] or {}
        derived = "*" if any(s != SERIES_KEY for s in fam.get("series_sources", ())) else ""
        for chosen in fam["selected"] or [{}]:
            lines.append(
                f"{(fam['family'][:33] + derived):<34} {fam['variants']:>3} {fam['months']:>4} "
                f"{_fmt(pbo.get('pbo')):>5} {_fmt(pbo.get('prob_oos_loss')):>7} "
                f"{chosen.get('trial_id', '-'):>6} {_fmt(chosen.get('sharpe_annualized')):>6} "
                f"{_fmt(chosen.get('dsr_family')):>6} {_fmt(chosen.get('dsr_ledger')):>6}")
    ledger = report["ledger"]
    floor = ledger.get("variance_min_months") or 0
    lines.append(f"ledger: {ledger['completed_training_trials']} completed training trials, "
                 f"{ledger['trials_with_series']} with monthly series"
                 f"{f' of {floor}+ months' if floor else ''}, "
                 f"Sharpe variance {ledger['sharpe_variance']:.4f}")
    lines.append(f"* at least one variant uses the derived {DERIVED_KEY} series")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    from tradingbot.db.session import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blocks", type=int, default=DEFAULT_BLOCKS)
    parser.add_argument("--dataset-key")
    parser.add_argument("--variance-min-months", type=int, default=0,
                        help="leave shorter families out of the ledger-wide Sharpe variance")
    parser.add_argument("--json", help="write the full report to this path")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        report = ledger_report(session, blocks=args.blocks, dataset_key=args.dataset_key,
                               variance_min_months=args.variance_min_months)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
            fh.write("\n")
    print(format_report(report))


if __name__ == "__main__":
    main()
