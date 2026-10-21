"""Read-only report queries for the dashboard.

Pure query functions over the ledger/risk tables. They never write — the
dashboard is read-only (PRD §7). Return plain dicts/lists so the server (or a
test) can render them without touching the ORM.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..db import enums
from ..db.models import Fill, Incident, Instrument, Position, RiskHalt, Strategy, Trial, Venue
from ..ledger.report_stats import (
    empty_statistics, evidence_status, execution_statistics, execution_trips, fill_query, load_trial_statistics,
)
from ..ledger.stats import luck_probability

MODES = (enums.Mode.BACKTEST, enums.Mode.PAPER, enums.Mode.LIVE)


# Backtest fills (tens of thousands) are append-only research output; replaying
# them on every 30s refresh dominated the snapshot. Cache the exact result per
# fingerprint of the backtest fill set (count, max id, id sum) and recompute
# whenever a backtest adds or removes fills.
_BACKTEST_CACHE: dict = {}
_BACKTEST_LOCK = threading.Lock()


def _backtest_fingerprint(session):
    return tuple(session.execute(select(func.count(), func.max(Fill.id), func.sum(Fill.id)).where(
        Fill.mode == enums.Mode.BACKTEST)).one())


def _scoped_ledgers(session, modes):
    """Execution accounting per (strategy, mode); the backtest scope is cached."""
    modes = set(modes)
    if enums.Mode.BACKTEST not in modes:
        return _compute_ledgers(session, modes)
    result = _compute_ledgers(session, modes - {enums.Mode.BACKTEST}) if modes - {enums.Mode.BACKTEST} else {}
    with _BACKTEST_LOCK:
        key = _backtest_fingerprint(session)
        if _BACKTEST_CACHE.get("key") != key:
            _BACKTEST_CACHE.update(key=key, ledgers=_compute_ledgers(session, {enums.Mode.BACKTEST}))
        result.update(_BACKTEST_CACHE["ledgers"])
    return result


def _compute_ledgers(session, modes):
    """Batch the same execution accounting instead of querying every strategy."""
    grouped = defaultdict(list)
    for fill in session.execute(fill_query().where(Fill.mode.in_(modes))):
        grouped[(fill.strategy_id, fill.mode)].append(fill)
    multipliers = dict(session.execute(select(Instrument.id, Instrument.contract_multiplier).where(
        Instrument.id.in_({f.instrument_id for values in grouped.values() for f in values}))).all())
    result = {}
    for scope, fills in grouped.items():
        trips = execution_trips(fills, multipliers)
        fees = sum((f.fee or Decimal(0) for f in fills), Decimal(0))
        gross = sum((f.realized_pnl or Decimal(0) for f in fills), Decimal(0))
        result[scope] = {"fill_count": len(fills), "trade_count": len(trips), "pnl_after_fees": gross-fees,
                         "fees_total": fees, "luck_p_value": luck_probability([t.net_pnl for t in trips]),
                         "statistics": (empty_statistics("Separate backtest experiments; see individual trial tables")
                                        if scope[1] == enums.Mode.BACKTEST else execution_statistics(fills, trips))}
    return result


def _strategy_rows(session):
    """Display columns only: ``Strategy.config`` holds MB-scale research
    receipts, and decoding it for every strategy took seconds (tradingbot-myj)."""
    return session.execute(select(Strategy.id, Strategy.key, Strategy.name, Strategy.status,
                                  Strategy.allocation_usd).order_by(Strategy.id)).all()


def _empty_ledger():
    return {"fill_count": 0, "trade_count": 0, "pnl_after_fees": Decimal(0), "fees_total": Decimal(0),
            "luck_p_value": None, "statistics": empty_statistics()}


def leaderboard(session: Session, mode: str = enums.Mode.LIVE, *, _ledgers=None, _strategies=None) -> list[dict]:
    """One row per strategy for ``mode``: P&L after fees, trade count, luck odds
    (PRD §4). Strategies with no activity still appear (pipeline visibility)."""
    ledgers = _scoped_ledgers(session, (mode,)) if _ledgers is None else _ledgers
    rows: list[dict] = []
    strategies = _strategy_rows(session) if _strategies is None else _strategies
    positions = dict(session.execute(select(Position.strategy_id, func.count()).where(
        Position.mode == mode, Position.status == enums.PositionStatus.OPEN).group_by(Position.strategy_id)).all())
    for strat in strategies:
        report = ledgers.get((strat.id, mode), _empty_ledger())
        statistics = (empty_statistics("Separate backtest experiments; see the individual trial tables")
                      if mode == enums.Mode.BACKTEST else report["statistics"])
        rows.append(
            {
                "strategy_id": strat.id,
                "key": strat.key,
                "name": strat.name,
                "status": strat.status,
                "allocation_usd": strat.allocation_usd,
                "mode": mode,
                "trade_count": report["trade_count"],
                "fill_count": report["fill_count"],
                "pnl_after_fees": report["pnl_after_fees"],
                "fees_total": report["fees_total"],
                "luck_p_value": report["luck_p_value"],
                "open_positions": positions.get(strat.id, 0),
                "statistics": statistics,
            }
        )
    # Best P&L first, then by trade count.
    rows.sort(key=lambda r: (r["pnl_after_fees"], r["trade_count"]), reverse=True)
    return rows


def backtest_vs_live_gap(session: Session, *, _ledgers=None, _strategies=None) -> list[dict]:
    """Per strategy: P&L after fees and trade count in backtest vs live, plus the
    gap — the core check that live matches the backtest (PRD §4)."""
    ledgers = _scoped_ledgers(session, (enums.Mode.BACKTEST, enums.Mode.LIVE)) if _ledgers is None else _ledgers
    rows: list[dict] = []
    for strat in _strategy_rows(session) if _strategies is None else _strategies:
        bt = ledgers.get((strat.id, enums.Mode.BACKTEST), _empty_ledger())
        lv = ledgers.get((strat.id, enums.Mode.LIVE), _empty_ledger())
        if bt["fill_count"] == 0 and lv["fill_count"] == 0:
            continue
        rows.append(
            {
                "key": strat.key,
                "name": strat.name,
                "backtest_pnl_after_fees": bt["pnl_after_fees"],
                "backtest_trade_count": bt["trade_count"],
                "live_pnl_after_fees": lv["pnl_after_fees"],
                "live_trade_count": lv["trade_count"],
                "gap": lv["pnl_after_fees"] - bt["pnl_after_fees"],
            }
        )
    return rows


def recent_incidents(session: Session, limit: int = 50) -> list[dict]:
    """Kill-switch and incident log, newest first."""
    incidents = session.scalars(
        select(Incident).order_by(Incident.ts.desc()).limit(limit)
    ).all()
    return [
        {
            "ts": inc.ts,
            "severity": inc.severity,
            "category": inc.category,
            "strategy_id": inc.strategy_id,
            "mode": inc.mode,
            "message": inc.message,
            "resolved": inc.resolved_ts is not None,
        }
        for inc in incidents
    ]


def active_halts(session: Session) -> list[dict]:
    """Currently active risk halts (kill-switch state)."""
    halts = session.scalars(
        select(RiskHalt).where(RiskHalt.active.is_(True)).order_by(RiskHalt.triggered_ts.desc())
    ).all()
    return [
        {
            "scope": h.scope,
            "strategy_id": h.strategy_id,
            "mode": h.mode,
            "halt_date": h.halt_date,
            "reason": h.reason,
            "pnl_at_trigger": h.pnl_at_trigger,
            "triggered_ts": h.triggered_ts,
        }
        for h in halts
    ]


def _iso(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return value


def kill_switches(session: Session) -> list[dict]:
    """Persistent connector kill switches (e.g. ``alpaca_live_kill_switch_v1``),
    stored on ``Venue.metadata``. One row per switch ever set, engaged or not."""
    rows: list[dict] = []
    for venue in session.scalars(select(Venue).order_by(Venue.key)):
        for name, state in sorted((venue.metadata_ or {}).items()):
            if "kill_switch" not in name or not isinstance(state, dict):
                continue
            rows.append({
                "venue": venue.key,
                "switch": name,
                "active": bool(state.get("active")),
                "reason": state.get("reason"),
                "engaged_at": _iso(state.get("engaged_at")),
                "cleared_at": _iso(state.get("cleared_at")),
                "cleared_note": state.get("cleared_note"),
            })
    return rows


def pipeline_status(session: Session) -> dict:
    """Counts of strategies by status and trials by (mode, status)."""
    strat_counts = dict(
        session.execute(
            select(Strategy.status, func.count()).group_by(Strategy.status)
        ).all()
    )
    trial_counts = [
        {"mode": mode, "status": status, "count": count}
        for mode, status, count in session.execute(
            select(Trial.mode, Trial.status, func.count()).group_by(Trial.mode, Trial.status)
        ).all()
    ]
    return {
        "strategies_by_status": {
            s: int(strat_counts.get(s, 0)) for s in enums.StrategyStatus.ALL
        },
        "trials": trial_counts,
        "venues": session.scalar(select(func.count()).select_from(Venue)) or 0,
    }


def backtest_trials(session: Session, limit: int = 20, *, final_only: bool = False) -> list[dict]:
    """Recent completed backtest trials with P&L, max drawdown and the regimes
    they were measured over (PRD §4; tradingbot-l0v). Newest first."""
    query = select(Trial).where(Trial.mode == enums.Mode.BACKTEST)
    if final_only:
        query = query.where(Trial.final_holdout.is_(True))
    else:
        query = query.where(Trial.status == enums.TrialStatus.COMPLETE).limit(limit)
    trials = session.scalars(query.order_by(Trial.completed_ts.desc().nullslast(), Trial.id.desc())).all()
    # Only the evidence audit is read from config (see _strategy_rows).
    audit = func.coalesce(Strategy.config["evidence_audit"], cast(literal("{}"), JSONB))
    strategies = {s.id: s for s in session.execute(select(
        Strategy.id, Strategy.key, func.jsonb_build_object("evidence_audit", audit).label("config"),
    ).where(Strategy.id.in_({t.strategy_id for t in trials})))}
    statistics = load_trial_statistics(session, trials)
    rows: list[dict] = []
    for t in trials:
        params = t.params or {}
        metrics = t.metrics or {}
        regimes = metrics.get("by_regime") if isinstance(metrics, dict) else None
        rows.append(
            {
                "trial_id": t.id,
                "strategy": strategies[t.strategy_id].key,
                "variant": " ".join(
                    str(params[k]) for k in ("side_rule", "offset", "category") if k in params
                ) or "—",
                "trade_count": t.trade_count,
                "pnl_after_fees": t.pnl_after_fees,
                "max_drawdown": t.max_drawdown,
                "luck_p_value": float(t.luck_p_value) if t.luck_p_value is not None else None,
                "regimes": ", ".join(sorted(regimes)) if isinstance(regimes, dict) and regimes else "—",
                "partition": "Final holdout" if t.final_holdout else "Training / other",
                "statistics": statistics[t.id],
                "evidence": evidence_status(t, strategies[t.strategy_id]),
            }
        )
    return rows


def dashboard_snapshot(session: Session, *, mode: str = enums.Mode.LIVE) -> dict:
    """Everything the dashboard needs in one call."""
    ledgers = _scoped_ledgers(session, {mode, enums.Mode.BACKTEST, enums.Mode.LIVE})
    strategies = _strategy_rows(session)
    return {
        "generated_at": datetime.now().astimezone(),
        "mode": mode,
        "modes": list(MODES),
        "leaderboard": leaderboard(session, mode, _ledgers=ledgers, _strategies=strategies),
        "backtest_vs_live": backtest_vs_live_gap(session, _ledgers=ledgers, _strategies=strategies),
        "backtest_trials": backtest_trials(session),
        "final_holdouts": backtest_trials(session, final_only=True),
        "incidents": recent_incidents(session),
        "active_halts": active_halts(session),
        "kill_switches": kill_switches(session),
        "pipeline": pipeline_status(session),
    }
