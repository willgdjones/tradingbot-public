"""C01 — archived SPY monthly trend experiment; FAILED_AUDIT (tradingbot-bbw).

The CLI now exports stored evidence only, without price loading or simulation.
The original simulator below is retained for forensic/synthetic tests. It does
not satisfy the preregistered shared risk/ledger, settlement or dividend rules;
its existing numeric results must not be treated as a PRD section 4 pass.

Preregistration: docs/research/07-candidate-shortlist.md (common rules + C01).
Original experiment: three monthly trend lookbacks at 5/10 bp on archived Yahoo
SPY history, with one selected 10 bp final. The original implementation deviated
from that preregistration. See docs/research/11-c01-holdout-audit.md.

Legacy modelling assumptions (not a claim of preregistration fidelity):
  * Decide at a month's final session close using that month's adjusted close and
    the prior L-1 month-end adjusted closes; execute at the next month's first
    session open. Trade only on a signal transition (cash<->long); retain the
    position while the signal is unchanged (Faber long/cash; few round trips).
  * Target 95% of decision-time marked equity on entry; the 5% cash reserve is the
    difference. Raw open is the execution price; adverse slippage (5/10 bp) and the
    EquityFeeBook (2026-09-17 counterfactual) are charged per side. Fractional
    shares round down to 1e-6; sub-$1 orders are skipped and counted.
  * T+1 settlement modelled (sale proceeds settle next session); for a monthly
    single-asset rule it never binds, and any delay is reported.
  * Dividends: entitled when shares are held on the ex-date, credited as cash on a
    payment-date proxy (ex-date + 30 calendar days, next session; else at terminal).
  * Each partition starts flat, keeps its L-month warm-up inside the partition, and
    liquidates any standing position at the final session's open (reported apart).
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal as D
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import (
    HoldoutSplit, HoldoutViolation, claim_final, engine_for, strategy_identity)
from tradingbot.data.disk_budget import DiskBudget
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Strategy, Trial
from tradingbot.ledger.stats import luck_probability
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.strategy.spy_monthly_trend import SpyMonthlyTrend

DATASET_KEY = "sweep-c01-v1"
DATA_START = datetime(2006, 1, 1, tzinfo=UTC)
DATA_END = datetime(2026, 10, 1, tzinfo=UTC)
START_EQUITY = D("140")
CAP = D("0.95")
SHARE_PREC = D("0.000001")
MIN_ORDER_USD = D("1")
LOOKBACKS = (10, 8, 12)          # preregistered variant order
COST_CASES_BP = (5, 10)          # training sensitivity + selection (10 bp)
DIV_PAYMENT_LAG_DAYS = 30
ZERO = D(0)
STRATEGY_KEY = "sweep_c01_spy_monthly_trend"
AUDIT_FINDINGS = (
    "final_replay_preceded_durable_admission",
    "shared_risk_and_execution_ledger_bypassed",
    "dividend_entitlement_and_payment_proxy",
    "calendar_day_settlement_without_validated_calendar",
    "slot_cap_not_enforced_on_compounded_equity",
    "terminal_marks_and_benchmark_dividends_not_causal",
    "source_crosscheck_and_dependency_identity_incomplete",
    "previously_inspected_sample_and_deleted_prior_attempts",
)


def evidence_audit():
    return {"bead": "tradingbot-bbw", "status": "FAILED_AUDIT",
            "promotion_eligible": False, "replay_allowed": False,
            "findings": list(AUDIT_FINDINGS),
            "report": "docs/research/11-c01-holdout-audit.md"}


@dataclass
class Trade:
    date: date
    side: str
    shares: str
    price: str
    notional: str
    fee: str
    slippage: str
    reason: str


@dataclass
class PartitionResult:
    lookback: int
    slippage_bp: int
    start_equity: str
    end_equity: str
    net_pnl: str
    net_return: float
    gross_pnl: str
    fees_total: str
    slippage_total: str
    dividends_total: str
    max_drawdown_usd: str
    max_drawdown_frac: float
    turnover: float
    round_trips: int
    n_trades: int
    skipped_suborders: int
    cash_delay_events: int
    avg_exposure: float
    luck_p_value: float | None
    monthly_returns: list = field(default_factory=list)
    by_year: dict = field(default_factory=dict)
    by_regime: dict = field(default_factory=dict)
    benchmarks: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)
    n_sessions: int = 0
    n_month_decisions: int = 0


class C01Backtester:
    """Runtime identity holder (its source file is hashed into the holdout
    version) plus the partition simulator."""

    def __init__(self, strategy: SpyMonthlyTrend, slippage_bp: int):
        self.strategy = strategy
        self.slippage_bp = slippage_bp
        self.slip = D(slippage_bp) / D(10000)

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _group_months(bars):
        groups = defaultdict(list)
        for b in bars:
            groups[(b.date.year, b.date.month)].append(b)
        months = []
        for key in sorted(groups):
            sess = sorted(groups[key], key=lambda x: x.date)
            months.append(sess)
        return months

    def _floor_shares(self, dollars: D, price: D) -> D:
        if price <= 0:
            return ZERO
        return (dollars / price).quantize(SHARE_PREC, rounding=ROUND_DOWN)

    # -- core simulation ------------------------------------------------------
    def run(self, bars) -> PartitionResult:
        fee_book = EquityFeeBook()
        months = self._group_months(bars)
        cash = START_EQUITY            # settled cash
        pending = []                   # (settle_date, amount) unsettled proceeds
        div_sched = []                 # (pay_date, amount) owed dividends
        shares = ZERO
        prev_weight = ZERO
        fees_total = slippage_total = dividends_total = ZERO
        turnover_notional = ZERO
        trades: list[Trade] = []
        skipped = 0
        cash_delays = 0
        round_trips = 0
        open_cost_basis = None
        equity_curve: list[tuple[date, D]] = []
        exposure_accum = 0.0
        exposure_n = 0
        month_end_adj: list[D] = []
        pending_target: D | None = None
        decision_equity: D | None = None
        n_decisions = 0
        last_session_date = bars[-1].date

        def settle_and_pay(today: date):
            nonlocal cash, dividends_total
            keep = []
            for sd, amt in pending:
                (cash.__class__)  # noqa
                if sd <= today:
                    cash += amt
                else:
                    keep.append((sd, amt))
            pending[:] = keep
            keep2 = []
            for pd_, amt in div_sched:
                if pd_ <= today:
                    cash += amt; dividends_total += amt
                else:
                    keep2.append((pd_, amt))
            div_sched[:] = keep2

        for mi, sess in enumerate(months):
            is_last_month = (mi == len(months) - 1)
            first = sess[0]
            # --- execute the decision made at the previous month-end, at this
            #     month's first-session open (skip the very first month) ---
            if pending_target is not None and mi > 0:
                settle_and_pay(first.date)
                if pending_target != prev_weight:
                    if pending_target == ZERO and shares > 0:
                        price = first.open * (D(1) - self.slip)
                        notional = shares * price
                        fee, _ = fee_book.charge(day=first.date, side="sell",
                                                 price=price, size=shares)
                        slip_cost = shares * first.open * self.slip
                        pending.append((first.date + timedelta(days=1), notional - fee))
                        trades.append(Trade(first.date, "sell", str(shares), str(price),
                                            str(notional), str(fee), str(slip_cost),
                                            "signal->cash"))
                        fees_total += fee; slippage_total += slip_cost
                        turnover_notional += notional
                        if open_cost_basis is not None:
                            round_trips += 1; open_cost_basis = None
                        shares = ZERO
                    elif pending_target > ZERO and shares == 0:
                        price = first.open * (D(1) + self.slip)
                        invest = (decision_equity * pending_target)
                        # estimate fee on a provisional size, then cap by settled cash
                        prov = self._floor_shares(invest, price)
                        est_fee, _ = fee_book.charge(day=first.date, side="buy",
                                                     price=price, size=max(prov, SHARE_PREC),
                                                     commit=False)
                        spendable = cash - est_fee
                        if spendable < invest:
                            if spendable < cash - est_fee - D("0.01"):
                                cash_delays += 1
                        buy_dollars = min(invest, max(spendable, ZERO))
                        qty = self._floor_shares(buy_dollars, price)
                        notional = qty * price
                        if qty <= 0 or notional < MIN_ORDER_USD:
                            skipped += 1
                        else:
                            fee, _ = fee_book.charge(day=first.date, side="buy",
                                                     price=price, size=qty)
                            slip_cost = qty * first.open * self.slip
                            cash -= (notional + fee)
                            shares = qty
                            fees_total += fee; slippage_total += slip_cost
                            turnover_notional += notional
                            open_cost_basis = notional + fee
                            trades.append(Trade(first.date, "buy", str(qty), str(price),
                                                str(notional), str(fee), str(slip_cost),
                                                "cash->signal"))
                    prev_weight = pending_target

            # --- walk the month's sessions: settle, dividends, mark equity ---
            for b in sess:
                settle_and_pay(b.date)
                if b.dividend > 0 and shares > 0:
                    pay = b.date + timedelta(days=DIV_PAYMENT_LAG_DAYS)
                    div_sched.append((pay, shares * b.dividend))
                owed = sum((a for _, a in pending), ZERO) + sum((a for _, a in div_sched), ZERO)
                equity = shares * b.close + cash + owed
                equity_curve.append((b.date, equity))
                exp = float((shares * b.close) / equity) if equity > 0 else 0.0
                exposure_accum += exp; exposure_n += 1

            # --- decide at this month's end (final session close) ---
            month_end_adj.append(sess[-1].adj_close)
            if not is_last_month:
                pending_target = self.strategy.decide(month_end_adj, prev_weight)
                decision_equity = shares * sess[-1].close + cash + \
                    sum((a for _, a in pending), ZERO) + sum((a for _, a in div_sched), ZERO)
                n_decisions += 1

        # --- terminal liquidation at the final session's open (reported apart) ---
        term = bars[-1]
        settle_and_pay(term.date)
        if shares > 0:
            price = term.open * (D(1) - self.slip)
            notional = shares * price
            fee, _ = fee_book.charge(day=term.date, side="sell", price=price, size=shares)
            slip_cost = shares * term.open * self.slip
            cash += notional - fee
            fees_total += fee; slippage_total += slip_cost
            turnover_notional += notional
            if open_cost_basis is not None:
                round_trips += 1
            trades.append(Trade(term.date, "sell", str(shares), str(price), str(notional),
                                str(fee), str(slip_cost), "terminal_liquidation"))
            shares = ZERO
        # pay any still-scheduled dividends/pending at terminal
        for _, amt in pending:
            cash += amt
        for _, amt in div_sched:
            cash += amt; dividends_total += amt
        pending.clear(); div_sched.clear()

        end_equity = cash
        net_pnl = end_equity - START_EQUITY
        gross_pnl = net_pnl + fees_total + slippage_total
        max_dd, max_dd_frac = _drawdown(equity_curve)
        monthly_returns = _monthly_returns(equity_curve)
        by_year = _period_returns(equity_curve, lambda d: str(d.year))
        by_regime = _period_returns(equity_curve, _regime_bucket)
        benchmarks = _benchmarks(bars)
        return PartitionResult(
            lookback=self.strategy.lookback_months, slippage_bp=self.slippage_bp,
            start_equity=str(START_EQUITY), end_equity=str(end_equity),
            net_pnl=str(net_pnl), net_return=float(net_pnl / START_EQUITY),
            gross_pnl=str(gross_pnl), fees_total=str(fees_total),
            slippage_total=str(slippage_total), dividends_total=str(dividends_total),
            max_drawdown_usd=str(max_dd), max_drawdown_frac=max_dd_frac,
            turnover=float(turnover_notional / START_EQUITY),
            round_trips=round_trips, n_trades=len(trades), skipped_suborders=skipped,
            cash_delay_events=cash_delays,
            avg_exposure=(exposure_accum / exposure_n) if exposure_n else 0.0,
            luck_p_value=luck_probability(monthly_returns) if len(monthly_returns) >= 2 else None,
            monthly_returns=[float(x) for x in monthly_returns],
            by_year=by_year, by_regime=by_regime, benchmarks=benchmarks,
            trades=[t.__dict__ for t in trades],
            n_sessions=len(equity_curve), n_month_decisions=n_decisions)


# --- metric helpers -----------------------------------------------------------
def _drawdown(curve):
    peak = None; worst = ZERO; worst_frac = 0.0
    for _, eq in curve:
        if peak is None or eq > peak:
            peak = eq
        drop = peak - eq
        if drop > worst:
            worst = drop
        if peak and peak > 0:
            frac = float(drop / peak)
            worst_frac = max(worst_frac, frac)
    return worst, worst_frac


def _monthly_returns(curve):
    by_month = {}
    for d, eq in curve:
        by_month[(d.year, d.month)] = eq  # last (month-end) equity
    keys = sorted(by_month)
    rets = []
    for prev, cur in zip(keys, keys[1:]):
        p = by_month[prev]
        if p and p > 0:
            rets.append((by_month[cur] - p) / p)
    return rets


def _period_returns(curve, bucket):
    first = {}; last = {}
    for d, eq in curve:
        b = bucket(d)
        if b not in first:
            first[b] = eq
        last[b] = eq
    out = {}
    for b in first:
        p = first[b]
        out[b] = float((last[b] - p) / p) if p and p > 0 else None
    return out


def _regime_bucket(d: date) -> str:
    y = d.year
    if y <= 2009:
        return "2006-2009"
    if y <= 2019:
        return "2010-2019"
    if y <= 2021:
        return "2020-2021"
    if y == 2022:
        return "2022"
    return "2023-2026"


def _benchmarks(bars):
    """Diagnostic, same replay observations: SPY buy&hold (full $140 at first open,
    dividends to cash, marked to last close) and flat cash. Not promotable."""
    first, last = bars[0], bars[-1]
    shares = (START_EQUITY / first.open)
    div_cash = sum((shares * b.dividend for b in bars if b.dividend > 0), ZERO)
    bh_end = shares * last.close + div_cash
    peak = None; worst = 0.0
    for b in bars:
        eq = shares * b.close + div_cash
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            worst = max(worst, float((peak - eq) / peak))
    return {
        "spy_buy_hold": {"end_equity": str(bh_end),
                          "net_return": float((bh_end - START_EQUITY) / START_EQUITY),
                          "max_drawdown_frac": worst},
        "cash": {"end_equity": str(START_EQUITY), "net_return": 0.0},
    }


# --- partitioning -------------------------------------------------------------
def split_bars(bars, split: HoldoutSplit, *, final_holdout: bool):
    """A session belongs to the holdout iff its close is at/after holdout_start.
    The cutoff is a morning UTC time, so every afternoon-ET close on/after that
    date is holdout; the split is therefore by date at the cutoff day."""
    cutoff = split.holdout_start.date()
    if final_holdout:
        return [b for b in bars if b.date >= cutoff]
    return [b for b in bars if b.date < cutoff]


# --- durable final admission and stored evidence ------------------------------
def stored_final(trial):
    """Render ledger facts, never recompute or infer missing executions."""
    if trial is None or trial.mode != "backtest" or not trial.final_holdout:
        raise HoldoutViolation("A recorded final-holdout trial is required")
    return {"trial_id": trial.id, "strategy_id": trial.strategy_id,
            "strategy_version": trial.strategy_version, "dataset_key": trial.dataset_key,
            "status": trial.status, "git_commit": trial.git_commit,
            "params": deepcopy(trial.params), "result": deepcopy(trial.metrics),
            "source": "stored_trial", "replayed": False,
            "trades_available": "trades" in (trial.metrics or {}),
            "evidence_audit": evidence_audit()}


def family_final(session, strategy_row_id, dataset_key):
    rows = list(session.scalars(select(Trial).where(
        Trial.strategy_id == strategy_row_id, Trial.dataset_key == dataset_key,
        Trial.mode == "backtest", Trial.final_holdout).order_by(Trial.id)))
    if len(rows) > 1:
        raise HoldoutViolation("Multiple consumed family finals: render an explicit stored trial ID")
    return rows[0] if rows else None


def replay_final_once(session, *, strategy_row_id, split, strategy, feed_factory, commit):
    """Admission must commit BEFORE the lazy feed or simulator is called.

    A previously consumed candidate/dataset stays consumed even if this repair
    changes source hashes. Failed/interrupted attempts are returned as stored
    evidence, never retried. The CLI does not call this primitive while C01's
    execution/data audit is failed; tests use synthetic, uniquely named data.
    """
    prior = family_final(session, strategy_row_id, split.dataset_key)
    if prior is not None:
        return stored_final(prior)
    version, frozen = strategy_identity(strategy, C01Backtester, {"slippage_bp": 10},
                                        execution_types=(EquityFeeBook,))
    params = {"partition": "final_holdout", "lookback_months": strategy.lookback_months,
              "slippage_bp": 10, "target_weight": str(strategy.target),
              "_holdout": split.metadata(), "_frozen": frozen}
    try:
        trial_id = claim_final(session, split=split, strategy_id=strategy_row_id,
            version=version, params=params,
            notes="C01 legacy diagnostic; durable admission before lazy feed. Not promotion evidence.")
    except HoldoutViolation:
        # Another worker may have won admission. No feed has been touched.
        session.rollback()
        prior = session.scalar(select(Trial).where(Trial.strategy_version == version, Trial.final_holdout))
        if prior is None:
            raise
        return stored_final(prior)
    try:
        trial = session.get(Trial, trial_id)
        trial.git_commit, trial.code_version = commit, "c01-audited-admission-v1"
        session.commit()
        result = C01Backtester(strategy, 10).run(feed_factory())
        # Preserve trades on new synthetic receipts too; dates are JSON values.
        metrics = json.loads(json.dumps(result.__dict__, default=str, allow_nan=False))
        trial = session.get(Trial, trial_id)
        trial.status, trial.completed_ts = "complete", datetime.now(UTC)
        trial.pnl = trial.pnl_after_fees = D(result.net_pnl)
        trial.fees_total, trial.trade_count = D(result.fees_total), result.n_trades
        trial.max_drawdown = D(result.max_drawdown_usd)
        trial.luck_p_value = None if result.luck_p_value is None else D(str(round(result.luck_p_value, 6)))
        trial.metrics = metrics
        session.commit()
        return {**stored_final(trial), "replayed": True}
    except BaseException as exc:
        session.rollback()
        # Caller rollback must not turn a consumed failed attempt into a retry.
        with Session(engine_for(session)) as audit, audit.begin():
            failed = audit.get(Trial, trial_id)
            failed.status, failed.completed_ts = "failed", datetime.now(UTC)
            failed.notes = (failed.notes or "") + "\nReplay failed: " + type(exc).__name__
        raise


def export_stored(session, trial_id=None):
    row = session.scalar(select(Strategy).where(Strategy.key == STRATEGY_KEY))
    if row is None:
        raise HoldoutViolation("C01 audit failed; no stored experiment to export")
    trial = (session.get(Trial, trial_id) if trial_id is not None else
             family_final(session, row.id, DATASET_KEY))
    if trial is None or trial.strategy_id != row.id or trial.dataset_key != DATASET_KEY:
        raise HoldoutViolation("C01 audit failed; select its existing stored final, never a new replay")
    return {"candidate": "C01", "strategy_status": row.status,
            "holdout": stored_final(trial), "evidence_audit": evidence_audit(),
            "verdict": {"outcome": "FAILED_AUDIT", "promotion_eligible": False,
                        "note": "Stored legacy metrics retained; original PRD section 4 pass withdrawn."}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stored-trial-id", type=int,
                    help="Read an existing C01 final from the ledger; never replay prices")
    ap.add_argument("--out", type=Path, help="Optional new stored-evidence JSON export")
    # Old invocations must fail closed rather than silently run another version.
    ap.add_argument("--capture", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--no-ledger", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-holdout", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.capture is not None or args.no_ledger or args.no_holdout:
        ap.error("C01 failed its evidence audit: replay is disabled; export a stored trial instead")
    with Session(local_engine()) as session:
        artifact = export_stored(session, args.stored_trial_id)
    if args.out is not None:
        DiskBudget(Path("data")).check_free()
        # Preserve the original full results/trade archive and all prior exports.
        with args.out.open("x") as handle:
            json.dump(artifact, handle, indent=2, default=str, allow_nan=False)
            handle.write("\n")
    print(json.dumps({"trial_id": artifact["holdout"]["trial_id"],
                      "status": artifact["holdout"]["status"],
                      "verdict": artifact["verdict"], "replayed": False}, indent=2))


def _verdict(train_res: PartitionResult, hold_res: PartitionResult) -> dict:
    train_pos = D(train_res.net_pnl) > 0
    hold_pos = D(hold_res.net_pnl) > 0
    return {
        "outcome": "FAILED_AUDIT", "promotion_eligible": False,
        "training_net_pnl": train_res.net_pnl, "holdout_net_pnl": hold_res.net_pnl,
        "both_partitions_positive": bool(train_pos and hold_pos),
        "holdout_vs_spy_buy_hold": {
            "strategy_net_return": hold_res.net_return,
            "spy_buy_hold_net_return": hold_res.benchmarks["spy_buy_hold"]["net_return"],
            "strategy_max_dd_frac": hold_res.max_drawdown_frac,
            "spy_buy_hold_max_dd_frac": hold_res.benchmarks["spy_buy_hold"]["max_drawdown_frac"]},
        "note": "Legacy unvalidated model output; positive arithmetic is not a PRD section 4 pass.",
    }


if __name__ == "__main__":
    main()
