"""Read-only, descriptive performance statistics with explicit sample scopes.

No result is written back to a trial, and no statistic is a promotion gate.
Marked returns are used only for named, understood research receipt schemas;
execution P&L is never silently relabelled as a periodic return series.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
from statistics import mean, stdev
from zoneinfo import ZoneInfo

from sqlalchemy import select

from tradingbot.db.models import Fill, Instrument
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import max_drawdown

ZERO = Decimal(0)
NEW_YORK = ZoneInfo("America/New_York")
DAILY_SCHEMAS = {"c05-amendment21-v1", "c04-readmission-v2"}
MONTHLY_SCHEMAS = {"c08-amendment21-v1"}
NOTICE = ("Informational only; PRD §4 promotion rules are unchanged. Sharpe uses sample standard deviation "
          "and a stated 0% cash benchmark. OOS t is a descriptive IID statistic, not a dependence-adjusted "
          "test or an untouched-evidence claim. Missing or undefined values remain unmeasured.")


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def sample_ratios(values, periods_per_year):
    """Ex-post Sharpe and zero-mean t; undefined variance stays null, not infinity."""
    numbers = [number(v) for v in values]
    if len(numbers) < 2 or any(v is None for v in numbers):
        return None, None
    try:
        xs = [float(v) for v in numbers]
        if not all(math.isfinite(v) for v in xs):
            return None, None
        deviation = stdev(xs)
        if not deviation or not math.isfinite(deviation):
            return None, None
        ratio = mean(xs) / deviation
        sharpe, t_value = ratio * math.sqrt(periods_per_year), ratio * math.sqrt(len(xs))
        return (sharpe, t_value) if math.isfinite(sharpe) and math.isfinite(t_value) else (None, None)
    except (ArithmeticError, ValueError):
        return None, None


def empty_statistics(reason="No recorded marked-return series"):
    return {"sharpe": None, "sharpe_samples": 0, "sharpe_basis": reason,
            "max_drawdown": None, "drawdown_basis": "Unmeasured",
            "hit_rate": None, "hit_rate_samples": 0, "hit_rate_basis": "No completed execution round trips",
            "oos_t_stat": None, "oos_samples": 0,
            "oos_basis": "OOS t is shown only for a completed recorded final holdout"}


def execution_trips(fills, multipliers):
    grouped = defaultdict(list)
    for fill in fills:
        grouped[fill.instrument_id].append(fill)
    trips = []
    for iid, values in grouped.items():
        events = [FillEvent(f.side, f.price, f.size, f.fee or ZERO, f.fill_ts)
                  for f in sorted(values, key=lambda f: (f.fill_ts, f.id))]
        trips.extend(iter_round_trips(events, multipliers[iid]))
    return sorted(trips, key=lambda t: t.exit_ts)


def execution_statistics(fills, trips):
    """Scope both inputs explicitly (all-time dashboard or this week's report)."""
    result = empty_statistics()
    if trips:
        result.update(hit_rate=sum(t.net_pnl > 0 for t in trips) / len(trips),
                      hit_rate_samples=len(trips),
                      hit_rate_basis=f"{len(trips)} completed execution round trips, net of fees; nontrade income excluded")
    if fills:
        # Simultaneous events are one observation, not an arbitrary ID ordering.
        cashflows = defaultdict(lambda: ZERO)
        for f in fills:
            cashflows[f.fill_ts] += (f.realized_pnl or ZERO) - (f.fee or ZERO)
        result.update(max_drawdown=max_drawdown([cashflows[t] for t in sorted(cashflows)]),
                      drawdown_basis="Realized ledger drawdown in this scope, including open-entry fees; unrealized marks excluded")
    return result


def evidence_status(trial, strategy):
    audit = (strategy.config or {}).get("evidence_audit", {})
    if audit.get("promotion_eligible") is False or audit.get("status") == "FAILED_AUDIT":
        return "FAILED AUDIT — not promotion evidence"
    metrics = trial.metrics or {}
    if metrics.get("audit_result"):
        return str(metrics["audit_result"])
    if trial.status != "complete":
        return trial.status
    if metrics.get("nonexecution_diagnostic"):
        return "Nonexecution diagnostic — not execution evidence"
    if metrics.get("promotion_eligible") is False:
        return "Research only — " + str(metrics.get("promotion_reason", "fidelity review incomplete"))
    return "Recorded final holdout; review gates" if trial.final_holdout else "Research result"


def _day(value):
    return value.astimezone(NEW_YORK).date() if isinstance(value, datetime) else date.fromisoformat(value)


def _final_interval(trial):
    return (trial.mode == "backtest" and trial.final_holdout and trial.holdout_start is not None
            and trial.data_start is not None and trial.data_end is not None
            and trial.holdout_start <= trial.data_start <= trial.data_end)


def _execution_oos(trial, fills, trips, result):
    """Legacy equity trials retain fills but no periodic marked series in the DB.

    A t of their net execution P&L is a different, explicitly named sample.
    Require flat inventory and reconciliation, rather than omit open fees/income.
    """
    if (trial.code_version != "equity-research-v1" or not _final_interval(trial)
            or len(trips) < 2 or len(trips) != trial.trade_count
            or any(not trial.data_start <= f.fill_ts <= trial.data_end for f in fills)):
        return
    owned = defaultdict(lambda: ZERO)
    for f in fills:
        owned[f.instrument_id] += f.size * (1 if f.side == "buy" else -1)
    net = sum((t.net_pnl for t in trips), ZERO)
    cash = sum(((f.realized_pnl or ZERO) - (f.fee or ZERO) for f in fills), ZERO)
    recorded = number(trial.pnl_after_fees)
    tolerance = Decimal("0.000001") * max(1, len(fills))
    if any(owned.values()) or recorded is None or abs(net-cash) > tolerance or abs(net-recorded) > tolerance:
        return
    _, t_value = sample_ratios([t.net_pnl for t in trips], 1)
    result.update(oos_t_stat=t_value, oos_samples=len(trips),
        oos_basis=f"Recorded final holdout; {len(trips)} reconciled complete execution round trips, net USD after fees; descriptive IID t, not marked returns")


def _marked_series(trial):
    """Return only known stored schemas; never open artifacts or replay a strategy."""
    m, params = trial.metrics or {}, trial.params or {}
    if m.get("complete_execution") is not True or not trial.data_start or not trial.data_end:
        raise ValueError("Complete dated marked-return receipt unavailable")
    start, end = _day(trial.data_start), _day(trial.data_end)
    if trial.code_version in DAILY_SCHEMAS:
        rows = m.get("daily_exposure", [])
        days = [_day(r["date"]) for r in rows]
        equities = [number(r["marked_equity_usd"]) for r in rows]
        if (len(rows) < 3 or days != sorted(set(days)) or any(not start <= d <= end for d in days)
                or any(v is None or v <= 0 for v in equities)):
            raise ValueError("Invalid or insufficient dated daily equity receipt")
        values = [float(current / previous - 1) for previous, current in zip(equities, equities[1:])]
        return values, 252, "daily marked equity returns; first recorded close is the baseline", days[0]
    if trial.code_version in MONTHLY_SCHEMAS:
        monthly = m.get("monthly_marked_net_usd", {})
        equity = number(params.get("slot_usd"))
        if not monthly or equity is None or equity <= 0:
            raise ValueError("Monthly equity baseline unavailable")
        first, last = start.strftime("%Y-%m"), end.strftime("%Y-%m")
        keys, expected = sorted(monthly), []
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            expected.append(f"{year:04}-{month:02}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        if keys != expected:
            raise ValueError("Monthly equity receipt has gaps or falls outside the trial")
        values = []
        for key in keys:
            pnl = number(monthly[key])
            if pnl is None or equity + pnl <= 0:
                raise ValueError("Invalid monthly marked P&L")
            # Boundary months may be partial; retain their equity effects but
            # never annualize them as full-month observations.
            if first < key < last:
                values.append(float(pnl / equity))
            equity += pnl
        ending = number(m.get("ending_marked_equity_usd"))
        tolerance = number(m.get("cash_reconciliation_tolerance_usd")) or Decimal("0.000001")
        if ending is None or tolerance < 0 or abs(equity - ending) > tolerance:
            raise ValueError("Monthly equity does not reconcile with its recorded ending value")
        return values, 12, "monthly marked equity returns; both boundary months excluded", start
    raise ValueError("No supported marked-return receipt; execution P&L is not a return series")


def trial_statistics(trial, fills, multipliers):
    result = empty_statistics("No supported marked-return receipt")
    if trial.status != "complete":
        return empty_statistics("Trial is not complete; partial results are not statistics")
    if any(f.mode != trial.mode or f.strategy_id != trial.strategy_id for f in fills):
        return empty_statistics("Execution mode/strategy differs from the trial")
    trips = execution_trips(fills, multipliers)
    result.update(execution_statistics(fills, trips))
    result["max_drawdown"] = number(trial.max_drawdown)
    metrics = trial.metrics or {}
    marked = any(k in metrics for k in ("max_marked_drawdown", "max_marked_drawdown_usd", "marked_drawdown"))
    result["drawdown_basis"] = "Recorded marked drawdown, USD" if marked else "Recorded trial drawdown, USD; runner basis retained"
    if not trips:
        rate = number(trial.win_rate if trial.win_rate is not None else metrics.get("win_rate"))
        if rate is not None and 0 <= rate <= 1 and trial.trade_count:
            result.update(hit_rate=float(rate), hit_rate_samples=trial.trade_count,
                          hit_rate_basis="Recorded runner win rate and trade-count definition")
    try:
        values, annual, basis, first_day = _marked_series(trial)
        sharpe, t_value = sample_ratios(values, annual)
        result.update(sharpe=sharpe, sharpe_samples=len(values),
                      sharpe_basis=f"{basis}; n={len(values)}, annualized ×√{annual}, 0% cash benchmark")
        if sharpe is None:
            result["sharpe_basis"] += "; undefined variance or insufficient finite samples"
        if _final_interval(trial) and first_day >= _day(trial.holdout_start):
            result.update(oos_t_stat=t_value, oos_samples=len(values),
                          oos_basis=f"Recorded final holdout; same {len(values)} marked returns, descriptive IID t (serial dependence unadjusted)")
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        result["sharpe_basis"] = str(exc)
        # A pre-existing scalar is shown verbatim, never assigned a new frequency.
        stored = number(trial.sharpe)
        if stored is not None:
            result.update(sharpe=float(stored), sharpe_basis="Recorded runner Sharpe; frequency/benchmark not recorded here")
        _execution_oos(trial, fills, trips, result)
    return result


def load_trial_statistics(session, trials):
    trials = list(trials)
    if not trials:
        return {}
    fills = list(session.execute(fill_query().where(Fill.trial_id.in_([t.id for t in trials]))))
    multipliers = dict(session.execute(select(Instrument.id, Instrument.contract_multiplier).where(
        Instrument.id.in_({f.instrument_id for f in fills}))).all())
    grouped = defaultdict(list)
    for fill in fills:
        grouped[fill.trial_id].append(fill)
    return {t.id: trial_statistics(t, grouped[t.id], multipliers) for t in trials}


def fill_query():
    """Only fields used in statistics, excluding large execution metadata."""
    return select(Fill.id, Fill.strategy_id, Fill.trial_id, Fill.instrument_id, Fill.mode,
                  Fill.side, Fill.price, Fill.size, Fill.fee, Fill.fill_ts, Fill.realized_pnl)


def scope_text(stats):
    return " · ".join(f"{label}: {stats[key]}" for label, key in (
        ("Sharpe", "sharpe_basis"), ("DD", "drawdown_basis"),
        ("Hit", "hit_rate_basis"), ("OOS t", "oos_basis")))
