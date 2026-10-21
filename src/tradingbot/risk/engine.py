"""The risk engine: absolute veto over every order (PRD §6).

Enforces the five hard limits — per-strategy −40% kill, −$50 global daily halt,
$25 per-market position cap, 30-second stale-data halt, and 5-errors/minute API
halt. The limits are hard-coded constants (:mod:`tradingbot.risk.limits`); this
engine never edits them. Tripped halts are persisted (``risk_halts``) and logged
(``incidents``) so a permanent per-strategy kill and the daily halt survive a
restart.

Two entry points:

* :meth:`RiskEngine.evaluate_order` — the fast pre-trade gate the execution layer
  MUST call and obey before placing any order.
* :meth:`RiskEngine.refresh_halts` — periodic re-evaluation of P&L that trips the
  daily halt and per-strategy kills (call it from the trading loop / dashboard).

Days are bounded in UTC.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import enums
from ..db.models import Fill, Incident, Instrument, Position, Quote, RiskHalt, Strategy, Trade, Venue
from ..ledger.ledger import Ledger
from . import limits

ZERO = Decimal(0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Outcome of a pre-trade check. ``allowed`` is the absolute verdict."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    max_size: Decimal | None = None  # largest size that would pass the position cap


class RiskEngine:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.ledger = Ledger(session, auto_fee=False)
        self._api_errors: deque[datetime] = deque()
        self._multipliers: dict[int, Decimal] = {}

    # -- helpers ------------------------------------------------------------
    def _multiplier(self, instrument_id: int) -> Decimal:
        m = self._multipliers.get(instrument_id)
        if m is None:
            m = self.session.scalar(
                select(Instrument.contract_multiplier).where(Instrument.id == instrument_id)
            )
            m = m if m is not None else Decimal(1)
            self._multipliers[instrument_id] = m
        return m

    def position_cap_usd(self, strategy_id: int, instrument_id: int) -> Decimal:
        """§6 cap for this strategy in this market: $25 on prediction markets,
        the strategy's allocation elsewhere (see ``limits.position_cap_usd``)."""
        venue_kind = self.session.scalar(
            select(Venue.kind).join(Instrument, Instrument.venue_id == Venue.id)
            .where(Instrument.id == instrument_id)
        )
        allocation = self.session.scalar(
            select(Strategy.allocation_usd).where(Strategy.id == strategy_id)
        )
        return limits.position_cap_usd(venue_kind, allocation)

    # -- individual checks --------------------------------------------------
    def is_strategy_killed(self, strategy_id: int | None) -> bool:
        if strategy_id is None:
            return False
        status = self.session.scalar(
            select(Strategy.status).where(Strategy.id == strategy_id)
        )
        return status == enums.StrategyStatus.KILLED

    def daily_halt_active(self, mode: str, day: date | None = None) -> bool:
        day = day or _utcnow().date()
        row = self.session.scalar(
            select(RiskHalt.id).where(
                RiskHalt.scope == enums.HaltScope.GLOBAL_DAILY,
                RiskHalt.active.is_(True),
                RiskHalt.halt_date == day,
                RiskHalt.mode == mode,
            )
        )
        return row is not None

    def api_error_rate_exceeded(self, now: datetime | None = None) -> bool:
        now = now or _utcnow()
        self._prune_api_errors(now)
        return len(self._api_errors) >= limits.API_ERROR_MAX_PER_MINUTE

    def is_globally_halted(self, mode: str, now: datetime | None = None) -> bool:
        now = (now or _utcnow()).astimezone(timezone.utc)
        return self.daily_halt_active(mode, now.date()) or self.api_error_rate_exceeded(now)

    def stale_data_check(
        self, instrument_id: int, now: datetime | None = None
    ) -> tuple[bool, float | None]:
        """Return (fresh?, age_seconds). Missing data counts as stale."""
        now = now or _utcnow()
        latest_q = self.session.scalar(
            select(func.max(Quote.time)).where(Quote.instrument_id == instrument_id)
        )
        latest_t = self.session.scalar(
            select(func.max(Trade.time)).where(Trade.instrument_id == instrument_id)
        )
        candidates = [t for t in (latest_q, latest_t) if t is not None]
        if not candidates:
            return False, None
        age = (now - max(candidates)).total_seconds()
        return age <= limits.STALE_DATA_MAX_SECONDS, age

    def position_cap_check(
        self,
        *,
        strategy_id: int,
        mode: str,
        instrument_id: int,
        side: str,
        size: Decimal,
        price: Decimal,
    ) -> tuple[bool, Decimal | None]:
        """Check the §6 per-market cap. Returns (ok, max_additional_size).

        Reducing or closing a position is always allowed. Increasing is allowed
        only while the resulting notional stays within the cap ($25 on
        prediction markets, the strategy's allocation elsewhere).
        """
        multiplier = self._multiplier(instrument_id)
        unit_cost = price * multiplier
        pos = self.ledger.get_position(strategy_id, mode, instrument_id)
        current_qty = (pos.quantity if pos else None) or ZERO
        signed = size if side == enums.Side.BUY else -size
        projected_qty = current_qty + signed

        if abs(projected_qty) <= abs(current_qty):
            return True, None  # reducing/closing never breaches the cap

        if unit_cost <= 0:
            return False, ZERO
        cap = self.position_cap_usd(strategy_id, instrument_id)
        max_total_qty = cap / unit_cost
        max_additional = max_total_qty - abs(current_qty)
        if max_additional < 0:
            max_additional = ZERO
        projected_notional = abs(projected_qty) * unit_cost
        ok = projected_notional <= cap
        return ok, max_additional

    # -- the pre-trade gate -------------------------------------------------
    def evaluate_order(
        self,
        *,
        instrument_id: int,
        mode: str,
        side: str,
        size: Decimal,
        price: Decimal,
        strategy_id: int | None = None,
        now: datetime | None = None,
    ) -> RiskDecision:
        """Absolute pre-trade veto. Callers MUST NOT place an order this rejects."""
        now = (now or _utcnow()).astimezone(timezone.utc)
        reasons: list[str] = []
        max_size: Decimal | None = None

        if self.is_strategy_killed(strategy_id):
            reasons.append("strategy permanently killed (−40% of allocation, PRD §6)")
        if self.daily_halt_active(mode, now.date()):
            reasons.append("global daily halt active (−$50, PRD §6)")
        if self.api_error_rate_exceeded(now):
            reasons.append(
                f"API error halt (>={limits.API_ERROR_MAX_PER_MINUTE}/min, PRD §6)"
            )

        fresh, age = self.stale_data_check(instrument_id, now)
        if not fresh:
            age_str = "no data" if age is None else f"{age:.0f}s old"
            reasons.append(f"stale market data ({age_str} > {limits.STALE_DATA_MAX_SECONDS}s)")

        if strategy_id is not None:
            ok_cap, max_size = self.position_cap_check(
                strategy_id=strategy_id, mode=mode, instrument_id=instrument_id,
                side=side, size=size, price=price,
            )
            if not ok_cap:
                cap = self.position_cap_usd(strategy_id, instrument_id)
                reasons.append(
                    f"per-market position cap ${cap} (max additional size {max_size})"
                )

        return RiskDecision(allowed=not reasons, reasons=reasons, max_size=max_size)

    # -- P&L for the triggers ----------------------------------------------
    def _open_unrealized(
        self, *, mode: str, strategy_id: int | None, marks: dict[int, Decimal], opened_since: datetime | None
    ) -> Decimal:
        stmt = select(Position).where(
            Position.status == enums.PositionStatus.OPEN, Position.mode == mode
        )
        if strategy_id is not None:
            stmt = stmt.where(Position.strategy_id == strategy_id)
        if opened_since is not None:
            stmt = stmt.where(Position.opened_ts >= opened_since)
        total = ZERO
        for pos in self.session.scalars(stmt):
            mark = marks.get(pos.instrument_id)
            if mark is None or pos.quantity in (None, ZERO) or pos.avg_price is None:
                continue
            total += (mark - pos.avg_price) * pos.quantity * self._multiplier(pos.instrument_id)
        return total

    def daily_pnl(
        self,
        mode: str,
        day: date | None = None,
        marks: dict[int, Decimal] | None = None,
        *,
        now: datetime | None = None,
    ) -> Decimal:
        """Change in marked equity since UTC midnight, including carried risk.

        Cash flows plus closing inventory value minus opening inventory value
        avoids booking an overnight gain/loss again when its position is sold.
        Opening quantity is reconstructed from the materialized ledger holding
        and today's executions; no broker/startup reconciliation is performed.
        ``now`` bounds observations/fills for a runtime's current event.
        """
        day = day or (now or _utcnow()).astimezone(timezone.utc).date()
        start, end = _day_bounds(day)
        cutoff = min(end, now + timedelta(microseconds=1)) if now is not None else end
        if cutoff <= start:
            return ZERO
        quantities: dict[int, Decimal] = {}
        fallback: dict[int, Decimal] = {}
        for pos in self.session.scalars(select(Position).where(Position.mode == mode)):
            iid = pos.instrument_id
            quantities[iid] = quantities.get(iid, ZERO) + pos.quantity
            if pos.quantity and pos.avg_price is not None:
                fallback[iid] = pos.avg_price
        # The ledger permits unattributed fills and materializes positions only
        # for attributed strategies. They still belong in the global cash/equity
        # calculation; otherwise an unattributed purchase looks like a loss.
        signed_qty = case((Fill.side == enums.Side.BUY, Fill.size), else_=-Fill.size)
        for iid, quantity in self.session.execute(select(Fill.instrument_id, func.sum(signed_qty)).where(
                Fill.mode == mode, Fill.strategy_id.is_(None)).group_by(Fill.instrument_id)):
            quantities[iid] = quantities.get(iid, ZERO) + quantity
        changes: dict[int, Decimal] = {}
        cash = ZERO
        # Reverse later fills too, so requesting a past day does not use today's
        # quantity as that day's closing holding. Prices remain bounded below.
        for fill in self.session.scalars(select(Fill).where(Fill.mode == mode, Fill.fill_ts >= start)):
            iid = fill.instrument_id
            signed = fill.size if fill.side == enums.Side.BUY else -fill.size
            if fill.fill_ts >= cutoff:
                quantities[iid] = quantities.get(iid, ZERO) - signed
                continue
            changes[iid] = changes.get(iid, ZERO) + signed
            cash -= signed * fill.price * self._multiplier(iid) + fill.fee
        total = cash
        for iid in quantities.keys() | changes.keys():
            closing = quantities.get(iid, ZERO)
            opening = closing - changes.get(iid, ZERO)
            if not closing and not opening:
                continue
            previous = self._daily_mark(iid, mode, start)
            current = (marks or {}).get(iid)
            if current is None:
                current = self._daily_mark(iid, mode, cutoff)
            # A valid ledger normally has a fill before an opening holding.
            # Imported position-only books may instead have only average cost.
            if previous is None:
                previous = fallback.get(iid)
            if current is None:
                current = previous if previous is not None else fallback.get(iid)
            if (opening and previous is None) or (closing and current is None):
                raise ValueError("Missing reference mark for daily portfolio P&L")
            total += (closing * (current or ZERO) - opening * (previous or ZERO)) * self._multiplier(iid)
        return total

    def _daily_mark(self, instrument_id: int, mode: str, before: datetime) -> Decimal | None:
        """Latest observed mark strictly before a boundary, never a future price.

        Prefer a quote on timestamp ties, then tape, then our execution. An old
        execution is a last-known reference when no intervening feed exists;
        this cannot infer an unobserved overnight price. Order freshness is
        still separately enforced at the unchanged 30-second threshold.
        """
        quote_price = func.coalesce(Quote.mid, Quote.last, (Quote.bid + Quote.ask) / 2, Quote.bid, Quote.ask)
        candidates = []
        for model, when, value, priority in ((Quote, Quote.time, quote_price, 2),
                                           (Trade, Trade.time, Trade.price, 1),
                                           (Fill, Fill.fill_ts, Fill.price, 0)):
            stmt = select(when, value).where(model.instrument_id == instrument_id, when < before, value.is_not(None))
            if model is Fill:
                stmt = stmt.where(Fill.mode == mode)
            row = self.session.execute(stmt.order_by(when.desc(), model.id.desc()).limit(1)).first()
            if row is not None:
                candidates.append((row[0], priority, row[1]))
        return max(candidates)[2] if candidates else None

    def strategy_pnl(
        self,
        strategy_id: int,
        mode: str,
        marks: dict[int, Decimal] | None = None,
    ) -> Decimal:
        """A strategy's total P&L after fees (all-time), plus open unrealized if
        ``marks`` given — the figure compared against the −40% kill threshold."""
        realized = self.ledger.realized_after_fees(strategy_id=strategy_id, mode=mode)
        if marks:
            realized += self._open_unrealized(
                mode=mode, strategy_id=strategy_id, marks=marks, opened_since=None
            )
        return realized

    # -- triggers (persist + log) ------------------------------------------
    def trigger_daily_halt(
        self, mode: str, pnl: Decimal, now: datetime | None = None
    ) -> RiskHalt | None:
        now = (now or _utcnow()).astimezone(timezone.utc)
        if self.daily_halt_active(mode, now.date()):
            return None
        halt = RiskHalt(
            scope=enums.HaltScope.GLOBAL_DAILY,
            mode=mode,
            halt_date=now.date(),
            reason=f"Daily P&L {pnl} <= {limits.GLOBAL_DAILY_HALT_USD} (PRD §6)",
            pnl_at_trigger=pnl,
            triggered_ts=now,
            active=True,
        )
        self.session.add(halt)
        self._log_incident(
            severity=enums.Severity.CRITICAL,
            category=enums.IncidentCategory.DAILY_HALT,
            mode=mode,
            message=f"Global daily halt: {mode} P&L {pnl} <= {limits.GLOBAL_DAILY_HALT_USD}",
            details={"pnl": str(pnl), "limit": str(limits.GLOBAL_DAILY_HALT_USD)},
            ts=now,
        )
        self.session.flush()
        return halt

    def kill_strategy(
        self, strategy_id: int, mode: str, pnl: Decimal, now: datetime | None = None
    ) -> RiskHalt | None:
        now = now or _utcnow()
        strategy = self.session.get(Strategy, strategy_id)
        if strategy is None or strategy.status == enums.StrategyStatus.KILLED:
            return None
        strategy.status = enums.StrategyStatus.KILLED
        halt = RiskHalt(
            scope=enums.HaltScope.STRATEGY,
            strategy_id=strategy_id,
            mode=mode,
            reason=(
                f"Strategy P&L {pnl} <= −{limits.PER_STRATEGY_KILL_FRACTION} × "
                f"allocation {strategy.allocation_usd} (PRD §6)"
            ),
            pnl_at_trigger=pnl,
            triggered_ts=now,
            active=True,
        )
        self.session.add(halt)
        self._log_incident(
            severity=enums.Severity.CRITICAL,
            category=enums.IncidentCategory.STRATEGY_KILL,
            strategy_id=strategy_id,
            mode=mode,
            message=f"Strategy {strategy.key} killed: P&L {pnl}, allocation {strategy.allocation_usd}",
            details={"pnl": str(pnl), "allocation": str(strategy.allocation_usd)},
            ts=now,
        )
        self.session.flush()
        return halt

    def refresh_halts(
        self,
        mode: str,
        marks: dict[int, Decimal] | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Recompute P&L and trip the daily halt / per-strategy kills as needed.

        Returns human-readable descriptions of anything tripped this call.
        """
        now = (now or _utcnow()).astimezone(timezone.utc)
        triggered: list[str] = []

        daily = self.daily_pnl(mode, now.date(), marks, now=now)
        if daily <= limits.GLOBAL_DAILY_HALT_USD and self.trigger_daily_halt(mode, daily, now):
            triggered.append(f"global daily halt ({mode} P&L {daily})")

        strategies = self.session.scalars(
            select(Strategy).where(
                Strategy.allocation_usd > 0,
                Strategy.status != enums.StrategyStatus.KILLED,
            )
        ).all()
        for strat in strategies:
            threshold = -(limits.PER_STRATEGY_KILL_FRACTION * strat.allocation_usd)
            spnl = self.strategy_pnl(strat.id, mode, marks)
            if spnl <= threshold and self.kill_strategy(strat.id, mode, spnl, now):
                triggered.append(f"kill {strat.key} (P&L {spnl} <= {threshold})")

        return triggered

    # -- API error tracking -------------------------------------------------
    def record_api_error(self, now: datetime | None = None) -> None:
        now = now or _utcnow()
        was_exceeded = self.api_error_rate_exceeded(now)
        self._api_errors.append(now)
        if not was_exceeded and self.api_error_rate_exceeded(now):
            self._log_incident(
                severity=enums.Severity.CRITICAL,
                category=enums.IncidentCategory.API_ERROR,
                message=(
                    f"API error halt: {len(self._api_errors)} errors within "
                    f"{limits.API_ERROR_WINDOW_SECONDS}s"
                ),
                ts=now,
            )
            self.session.flush()

    def _prune_api_errors(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=limits.API_ERROR_WINDOW_SECONDS)
        while self._api_errors and self._api_errors[0] < cutoff:
            self._api_errors.popleft()

    # -- incidents ----------------------------------------------------------
    def log_incident(
        self,
        *,
        severity: str,
        category: str,
        message: str,
        strategy_id: int | None = None,
        instrument_id: int | None = None,
        mode: str | None = None,
        details: dict | None = None,
        ts: datetime | None = None,
    ) -> Incident:
        """Public incident logger (kill-switch and incident log, PRD §7)."""
        return self._log_incident(
            severity=severity, category=category, message=message,
            strategy_id=strategy_id, instrument_id=instrument_id, mode=mode,
            details=details, ts=ts,
        )

    def _log_incident(
        self,
        *,
        severity: str,
        category: str,
        message: str,
        strategy_id: int | None = None,
        instrument_id: int | None = None,
        mode: str | None = None,
        details: dict | None = None,
        ts: datetime | None = None,
    ) -> Incident:
        incident = Incident(
            severity=severity,
            category=category,
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            mode=mode,
            message=message,
            details=details,
        )
        if ts is not None:
            incident.ts = ts
        self.session.add(incident)
        return incident
