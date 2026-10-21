"""Derived monthly net series for training trials that lack one (tradingbot-9os).

The overfitting check (:mod:`tradingbot.backtest.overfitting`) needs a monthly USD
P&L series for every training variant. Older replays stored their per-period
evidence in other shapes, so their sweeps got neither PBO nor deflated Sharpe.
This module derives the series from what each trial already recorded. It does not
re-run a strategy or open any artifact.

Each derivation must reconcile with the trial's own recorded net result. The
series is then written under a NEW metrics key (:data:`DERIVED_KEY`), together
with its basis and source. Existing metrics are never edited. Final-holdout trials
and trials that already carry a series are never touched.

Sources, in the order tried:

* ``monthly_net_usd`` (c06): round-trip net booked by New York exit month.
* ``monthly_returns`` (c01): compounded month-end marked returns. The months end
  at the partition's last month. The first curve month is the flat baseline. The
  terminal open liquidation is booked in the final month.
* ``monthly_marks`` (longshot): month start and end equity, chained.
* ``daily_exposure`` (c07): daily marked equity from a flat start, last value
  per month.
* Ledger fills linked by ``trial_id`` (turn of month): each flat-to-flat round
  trip's cash flow, booked in the New York month of the fill that closes it.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tradingbot.backtest.overfitting import DERIVED_KEY, SERIES_KEY
from tradingbot.db import enums
from tradingbot.db.models import Fill, Trial

NEW_YORK = ZoneInfo("America/New_York")
BEAD = "tradingbot-9os"
TOLERANCE_USD = Decimal("0.0001")
EXIT_MONTH = "exit_month_realized"
MONTH_END = "month_end_equity"
ZERO = Decimal(0)


class Unreconciled(ValueError):
    """A source exists but does not yield a series that matches the trial."""


@dataclass(frozen=True)
class Derived:
    months: dict[str, Decimal]
    basis: str
    source: str
    reference_metric: str
    reference_usd: Decimal
    tolerance_usd: Decimal = TOLERANCE_USD
    notes: dict = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        return sum(self.months.values(), ZERO)

    @property
    def difference(self) -> Decimal:
        return self.total - self.reference_usd

    def check(self) -> Derived:
        if not self.months:
            raise Unreconciled(f"{self.source}: empty series")
        if abs(self.difference) > self.tolerance_usd:
            raise Unreconciled(f"{self.source}: series totals {self.total}, "
                               f"{self.reference_metric} is {self.reference_usd}")
        return self

    def payload(self, derived_ts: datetime) -> dict:
        return {
            "months": {m: str(v) for m, v in sorted(self.months.items())},
            "basis": self.basis, "source": self.source,
            "reference": {"metric": self.reference_metric, "value": str(self.reference_usd),
                          "difference": str(self.difference)},
            "tolerance_usd": str(self.tolerance_usd), **self.notes,
            "derived_by": BEAD, "derived_ts": derived_ts.isoformat(timespec="seconds"),
        }


def _d(value) -> Decimal:
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def _tolerance(metrics: Mapping) -> Decimal:
    stored = metrics.get("cash_reconciliation_tolerance_usd")
    return max(TOLERANCE_USD, _d(stored)) if stored is not None else TOLERANCE_USD


def _month(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _shift(label: str, months: int) -> str:
    year, month = map(int, label.split("-"))
    index = year * 12 + month - 1 + months
    return _month(index // 12, index % 12 + 1)


def from_monthly_net(metrics: Mapping) -> Derived:
    months = {m: _d(v) for m, v in metrics["monthly_net_usd"].items()}
    return Derived(months, EXIT_MONTH, "metrics.monthly_net_usd", "net_usd",
                   _d(metrics["net_usd"]), _tolerance(metrics)).check()


def from_monthly_returns(metrics: Mapping, data_end: datetime) -> Derived:
    """Compounded month-end returns -> USD per month.

    ``returns[i]`` is the change between consecutive month-end marks, so the
    labels are the ``len(returns)`` months ending at the partition's last month
    (``data_end`` is exclusive). The month before them is the baseline, worth
    ``start_equity`` because the replay is flat until its first decision. The
    curve is marked at closes, but the replay liquidates at the final session's
    open. That residual is booked in the final month so the series totals
    ``net_pnl``. The first calendar year's recorded return checks the alignment.
    """
    returns = [_d(r) for r in metrics["monthly_returns"]]
    if not returns:
        raise Unreconciled("metrics.monthly_returns: empty")
    last = (data_end - timedelta(microseconds=1)).astimezone(NEW_YORK)
    labels = [_shift(_month(last.year, last.month), i - len(returns) + 1) for i in range(len(returns))]
    equity = start = _d(metrics["start_equity"])
    months, marks = {}, {}
    for label, change in zip(labels, returns):
        new = equity * (1 + change)
        months[label], marks[label] = new - equity, new
        equity = new
    baseline_year = _shift(labels[0], -1)[:4]
    by_year = metrics.get("by_year")
    if by_year is not None:
        # The curve starts in the baseline year, so an aligned series has its return.
        if by_year.get(baseline_year) is None:
            raise Unreconciled(f"metrics.monthly_returns: no by_year return for {baseline_year}; "
                               "months are misaligned")
        recorded = by_year[baseline_year]
        year_end = max((m for m in marks if m.startswith(baseline_year)), default=None)
        derived = (marks[year_end] if year_end else start) / start - 1
        if abs(derived - _d(recorded)) > Decimal("1e-9"):
            raise Unreconciled(f"metrics.monthly_returns: {baseline_year} return {derived} "
                               f"does not match by_year {recorded}; months are misaligned")
    residual = _d(metrics["end_equity"]) - equity
    months[labels[-1]] += residual
    return Derived(months, MONTH_END, "metrics.monthly_returns x start_equity", "net_pnl",
                   _d(metrics["net_pnl"]),
                   notes={"terminal_residual_usd": str(residual),
                          "baseline_month": _shift(labels[0], -1)}).check()


def from_monthly_marks(metrics: Mapping) -> Derived:
    marks = metrics["monthly_marks"]
    keys = sorted(marks)
    if _d(marks[keys[0]]["start_equity"]) != _d(metrics["initial_cash"]):
        raise Unreconciled("metrics.monthly_marks: first month does not start at initial_cash")
    for previous, current in zip(keys, keys[1:]):
        if current != _shift(previous, 1) or \
                _d(marks[current]["start_equity"]) != _d(marks[previous]["end_equity"]):
            raise Unreconciled(f"metrics.monthly_marks: chain breaks at {current}")
    months = {k: _d(marks[k]["end_equity"]) - _d(marks[k]["start_equity"]) for k in keys}
    return Derived(months, MONTH_END, "metrics.monthly_marks", "pnl_after_fees",
                   _d(metrics["pnl_after_fees"]), _tolerance(metrics)).check()


def from_daily_equity(metrics: Mapping) -> Derived:
    rows = metrics["daily_exposure"]
    if not rows or _d(rows[0].get("owned_value_usd", "nan")) != 0:
        raise Unreconciled("metrics.daily_exposure: does not start flat")
    dates = [r["date"] for r in rows]
    if dates != sorted(set(dates)):
        raise Unreconciled("metrics.daily_exposure: dates are not strictly increasing")
    previous = _d(rows[0]["marked_equity_usd"])
    month_end = {}
    for row in rows:
        month_end[row["date"][:7]] = _d(row["marked_equity_usd"])
    months = {}
    for label in sorted(month_end):
        months[label], previous = month_end[label] - previous, month_end[label]
    ending = _d(metrics["ending_marked_equity_usd"])
    if previous != ending:
        raise Unreconciled("metrics.daily_exposure: last mark is not ending_marked_equity_usd")
    return Derived(months, MONTH_END, "metrics.daily_exposure.marked_equity_usd", "net_usd",
                   _d(metrics["net_usd"]), _tolerance(metrics),
                   notes={"start_equity_usd": str(_d(rows[0]["marked_equity_usd"]))}).check()


def from_fills(metrics: Mapping, fills: Sequence) -> Derived:
    """Round-trip cash flows from ledger fills, booked in the closing fill's month."""
    position, cash = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    months: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for fill in sorted(fills, key=lambda f: (f.fill_ts, f.id)):
        sign = 1 if fill.side == enums.Side.BUY else -1
        notional = fill.price * fill.size  # unrounded, as the replay booked it
        if fill.notional is not None and abs(fill.notional - notional) > Decimal("0.01"):
            raise Unreconciled(f"ledger fills: fill {fill.id} has a contract multiplier")
        key = fill.instrument_id
        position[key] += sign * fill.size
        cash[key] += -sign * notional - fill.fee
        if position[key] == 0:
            months[fill.fill_ts.astimezone(NEW_YORK).strftime("%Y-%m")] += cash.pop(key)
    if any(position[k] != 0 for k in position):
        raise Unreconciled("ledger fills: a position is still open at the end")
    return Derived(dict(months), EXIT_MONTH, "ledger fills by trial_id", "net_usd",
                   _d(metrics["net_usd"]), _tolerance(metrics),
                   notes={"fills": len(fills)}).check()


def derive(trial: Trial, fills: Sequence = ()) -> Derived | None:
    """The trial's derived series, None when it has no usable source.

    Raises :class:`Unreconciled` when a source exists but disagrees with the
    trial's recorded result."""
    metrics = trial.metrics or {}
    if isinstance(metrics.get("monthly_net_usd"), dict):
        return from_monthly_net(metrics)
    if isinstance(metrics.get("monthly_returns"), list):
        return from_monthly_returns(metrics, trial.data_end)
    if isinstance(metrics.get("monthly_marks"), dict):
        return from_monthly_marks(metrics)
    if isinstance(metrics.get("daily_exposure"), list):
        return from_daily_equity(metrics)
    if fills and "net_usd" in metrics:
        return from_fills(metrics, fills)
    return None


def candidates(session: Session, *, dataset_key: str | None = None,
               trial_ids: Iterable[int] = ()) -> list[Trial]:
    """Completed, non-final backtest training trials in a dataset split that
    carry neither the original nor a derived monthly series."""
    query = (select(Trial).where(
        Trial.mode == enums.Mode.BACKTEST, Trial.status == enums.TrialStatus.COMPLETE,
        Trial.final_holdout.is_(False), Trial.dataset_key.is_not(None),
        func.jsonb_exists(func.coalesce(Trial.metrics, text("'{}'::jsonb")), SERIES_KEY).is_(False),
        func.jsonb_exists(func.coalesce(Trial.metrics, text("'{}'::jsonb")), DERIVED_KEY).is_(False))
        .order_by(Trial.id))
    if dataset_key is not None:
        query = query.where(Trial.dataset_key == dataset_key)
    ids = list(trial_ids)
    if ids:
        query = query.where(Trial.id.in_(ids))
    return list(session.scalars(query))


def write(session: Session, trial_id: int, derived: Derived, derived_ts: datetime) -> None:
    """Add DERIVED_KEY to one eligible trial's metrics, leaving every other key as is."""
    result = session.execute(text(
        "UPDATE trials SET metrics = coalesce(metrics, '{}'::jsonb) "
        "|| jsonb_build_object(CAST(:key AS text), CAST(:payload AS jsonb)) "
        "WHERE id = :id AND mode = :mode AND status = :status AND final_holdout IS FALSE "
        "AND NOT jsonb_exists(coalesce(metrics, '{}'::jsonb), :series) "
        "AND NOT jsonb_exists(coalesce(metrics, '{}'::jsonb), :key)"),
        {"key": DERIVED_KEY, "payload": json.dumps(derived.payload(derived_ts)), "id": trial_id,
         "mode": enums.Mode.BACKTEST, "status": enums.TrialStatus.COMPLETE, "series": SERIES_KEY})
    if result.rowcount != 1:
        raise RuntimeError(f"trial {trial_id} is no longer eligible for a derived series")


def backfill(session: Session, *, commit: bool = False, dataset_key: str | None = None,
             trial_ids: Iterable[int] = ()) -> list[dict]:
    """Derive (and with ``commit`` write) series for every candidate trial."""
    now = datetime.now(UTC)
    rows = []
    for trial in candidates(session, dataset_key=dataset_key, trial_ids=trial_ids):
        fills = session.scalars(select(Fill).where(Fill.trial_id == trial.id)).all()
        row = {"trial_id": trial.id, "dataset_key": trial.dataset_key}
        try:
            derived = derive(trial, fills)
        except Unreconciled as exc:
            rows.append({**row, "status": "unreconciled", "detail": str(exc)})
            continue
        if derived is None:
            rows.append({**row, "status": "no_source"})
            continue
        rows.append({**row, "status": "written" if commit else "derivable",
                     "basis": derived.basis, "source": derived.source,
                     "months": len(derived.months), "total_usd": str(derived.total),
                     "difference_usd": str(derived.difference)})
        if commit:
            write(session, trial.id, derived, now)
    if commit:
        session.commit()
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    from tradingbot.db.session import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-key")
    parser.add_argument("--trial-id", type=int, action="append", default=[])
    parser.add_argument("--commit", action="store_true", help="write; the default is a dry run")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        rows = backfill(session, commit=args.commit, dataset_key=args.dataset_key,
                        trial_ids=args.trial_id)
    for row in rows:
        detail = row.get("detail") or (f"{row['basis']:<20} months={row['months']:>4} "
                                       f"total={Decimal(row['total_usd']):.6f} "
                                       f"diff={Decimal(row['difference_usd']):.1e}"
                                       if "basis" in row else "")
        print(f"{row['trial_id']:>6} {row['status']:<12} {row['dataset_key'][:40]:<40} {detail}")
    counts = defaultdict(int)
    for row in rows:
        counts[row["status"]] += 1
    print(("committed: " if args.commit else "dry run: ") +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
