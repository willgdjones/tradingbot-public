"""Shared Alpaca paper fee/model-cost overlay and complete-portfolio guard.

This layer preserves the connector's dated T+1 cash policy and all PRD limits.
It neither initializes a cash book nor enables/replaces a venue-wide guard.
Runners must use ``paper-trial:<trial id>:<decision id>`` as Jev correlation IDs.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D, ROUND_DOWN
import re

from sqlalchemy import select

from tradingbot.connectors.alpaca_paper import (
    NAME as CONNECTOR, PaperGuardContext, PaperGuardResult,
)
from tradingbot.connectors.cash import NEW_YORK, amount, timestamp
from tradingbot.db.models import Fill, Instrument, JevRequest, Quote, Strategy, Trial
from tradingbot.forward.paper_evidence import fresh_marks, required_instrument_ids
from tradingbot.research.equity_fees import EquityFeeBook

NAME = "ai_paper_costs_v1"
ZERO = D(0)
_CORRELATION = re.compile(r"paper-trial:([1-9][0-9]*):(.{1,128})\Z")
# A concurrent cohort can commit a fill or Jev receipt microseconds-to-seconds after
# this as-of-`now` account view opens (the 10:15/10:30 ET quarter-hour overlap: C05's
# 11 Oct 6-7 holds each followed a J Jev call by ~0-1 s). Such a row is not part of
# THIS view; it is counted on the next read. A timestamp beyond this tolerance is a
# genuine inconsistency and still raises (hwm).
RECEIPT_CLOCK_TOLERANCE = timedelta(seconds=1)


@dataclass
class AccountCosts:
    """Additional debits beyond actual fees already booked in the ledger."""

    total: D = ZERO
    daily: D = ZERO
    by_strategy: dict[int, D] = field(default_factory=dict)
    by_trial: dict[int, D] = field(default_factory=dict)
    fee_by_fill: dict[int, D] = field(default_factory=dict)
    model_by_request: dict[str, D] = field(default_factory=dict)
    unknown_request_ids: tuple[str, ...] = ()


def account_costs(session, venue_id: int, now: datetime) -> AccountCosts:
    """Read the full account, including completed/failed trials and reservations.

    EquityFeeBook rounds fees cumulatively for the whole account each exchange
    day, in actual fill timestamp/id order. Jev reservations are cash/risk debits
    until settled, even if a caller died before saving its own trial metrics.
    No trial-derived cost total is added again to these provider/ledger sources.
    """
    now = timestamp(now).astimezone(UTC)
    strategies = {s.id: s for s in session.scalars(select(Strategy).where(Strategy.venue_id == venue_id))}
    trials = {t.id: t for t in session.scalars(select(Trial).where(
        Trial.strategy_id.in_(strategies), Trial.mode == "paper"))}
    by_strategy, by_trial = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    result, fees = AccountCosts(), EquityFeeBook()

    def debit(cost, sid, tid, at, *, uncertain=False):
        result.total += cost
        by_strategy[sid] += cost
        by_trial[tid] += cost
        # An unresolved charge could settle today; conservatively retain it in
        # the daily risk debit as well as the lifetime cash/strategy debit.
        if timestamp(at).astimezone(UTC).date() == now.date() or uncertain:
            result.daily += cost

    fee_days = defaultdict(list)
    fills = session.scalars(select(Fill).join(Instrument).where(
        Instrument.venue_id == venue_id, Fill.mode == "paper").order_by(Fill.fill_ts, Fill.id))
    for fill in fills:
        if (fill.strategy_id not in strategies or fill.trial_id not in trials
                or trials[fill.trial_id].strategy_id != fill.strategy_id
                or fill.fill_ts > now + RECEIPT_CLOCK_TOLERANCE
                or (fill.metadata_ or {}).get("connector") != CONNECTOR):
            raise ValueError("Unattributed, unmanaged or future paper fill")
        if fill.fill_ts > now:
            continue  # boundary-race fill, just after this view; counted on the next read
        modeled, _ = fees.charge(day=fill.fill_ts.astimezone(NEW_YORK).date(), side=fill.side,
                                 price=fill.price, size=fill.size)
        fee_days[fill.fill_ts.astimezone(NEW_YORK).date()].append((fill, modeled, amount(fill.fee or ZERO)))
    for daily_rows in fee_days.values():
        # Actual charges can arrive on a different fill than modeled rounding.
        # Reconcile at account/day level so a prior real fee is not charged a
        # second time later. Attribute any residual pro rata to positive gaps.
        modeled_total = sum((model for _, model, _ in daily_rows), ZERO)
        actual_total = sum((actual for _, _, actual in daily_rows), ZERO)
        remainder = max(ZERO, modeled_total - actual_total)
        gaps = [(fill, max(ZERO, model - actual)) for fill, model, actual in daily_rows]
        remaining_gap = sum((gap for _, gap in gaps), ZERO)
        for fill, gap in gaps:
            extra = ZERO if not gap else ((remainder * gap / remaining_gap).quantize(
                D(".000000000001"), rounding=ROUND_DOWN) if gap < remaining_gap else remainder)
            remaining_gap -= gap
            remainder -= extra
            result.fee_by_fill[fill.id] = extra
            debit(extra, fill.strategy_id, fill.trial_id, fill.fill_ts)

    unknown = []
    requests = session.scalars(select(JevRequest).where(
        JevRequest.correlation_id.startswith("paper-trial:")).order_by(JevRequest.started_ts, JevRequest.id))
    for request in requests:
        match = _CORRELATION.fullmatch(request.correlation_id)
        if match is None:
            raise ValueError("Malformed paper provider attribution")
        tid = int(match[1])
        trial = session.get(Trial, tid)
        if trial is None or trial.mode != "paper":
            raise ValueError("Provider request has no paper trial")
        if trial.id not in trials:
            # It belongs to another venue, not this cash book.
            continue
        if (request.started_ts > now + RECEIPT_CLOCK_TOLERANCE
                or (request.completed_ts and request.completed_ts > now + RECEIPT_CLOCK_TOLERANCE)):
            raise ValueError("Future provider receipt in current account view")
        if request.started_ts > now or (request.completed_ts and request.completed_ts > now):
            continue  # concurrency boundary, just after this view; counted on the next read
        reserved = amount(request.reserved_usd)
        actual = amount(request.actual_usd) if request.actual_usd is not None else ZERO
        uncertain = request.actual_usd is None and request.status != "refused"
        if (request.status == "refused" and (actual or reserved)
                or uncertain and reserved <= ZERO
                or request.actual_usd is not None and reserved != ZERO):
            raise ValueError("Inconsistent provider spend reservation")
        cost = actual + reserved
        if uncertain:
            unknown.append(request.id)
        result.model_by_request[request.id] = cost
        debit(cost, trial.strategy_id, tid, request.started_ts, uncertain=uncertain)
    result.by_strategy, result.by_trial = dict(by_strategy), dict(by_trial)
    result.unknown_request_ids = tuple(unknown)
    return result


class AIPaperCostGuard:
    """Capture before submit/known-intent refresh; callback performs no HTTP.

    A stronger, already-enabled account evidence guard is never silently
    bypassed. This guard does not change ``venue.metadata.guard_required``.
    """

    def __init__(self):
        self.quotes = None
        self.market_session = None
        self.valid_until = None

    def capture(self, connector, *, additional=(), valid_until=None):
        self.quotes = None
        self.valid_until = timestamp(valid_until) if valid_until is not None else None
        now = timestamp(connector.now())
        venue = connector._venue()
        needed = required_instrument_ids(connector.session, additional)
        instruments = list(connector.session.scalars(select(Instrument).where(Instrument.id.in_(needed))))
        if len(instruments) != len(needed) or any(i.venue_id != venue.id or i.instrument_type != "equity" for i in instruments):
            raise ValueError("All paper exposure must have supported Alpaca marks")
        market = connector._calendar(now.astimezone(NEW_YORK).date())
        if not market.is_open(now):
            raise ValueError("Account cost guard requires a regular session")
        quotes = {}
        batch = (connector._call(connector.api.quotes, [i.symbol for i in instruments])
                 if instruments and callable(getattr(connector.api, "quotes", None)) else None)
        for instrument in instruments:
            row = batch[instrument.symbol] if batch is not None else connector._call(connector.api.quote, instrument.symbol)
            quotes[instrument.id] = row
        fresh_marks(connector.session, quotes, connector.now(), market, additional)
        for iid, quote in quotes.items():
            connector.session.add(Quote(instrument_id=iid, time=timestamp(quote["t"]),
                                        bid=D(str(quote["bp"])), ask=D(str(quote["ap"])),
                                        metadata_={"connector": NAME, "feed": "iex", "kind": "live_quote"}))
        connector.session.commit()
        self.quotes, self.market_session = quotes, market

    def __call__(self, connector, context: PaperGuardContext) -> PaperGuardResult:
        required_guard = connector._book(context.venue).get("guard_required")
        if required_guard not in (None, NAME):
            raise ValueError("Preserve the account's existing evidence guard")
        if self.quotes is None or self.market_session is None:
            raise ValueError("Capture current account quotes before execution")
        now = timestamp(context.now)
        if self.valid_until is not None and now >= self.valid_until:
            raise ValueError("Frozen decision deadline expired")
        quotes = dict(self.quotes)
        additional = ()
        if context.instrument_id is not None:
            additional = (context.instrument_id,)
        if context.quote is not None:
            q = context.quote
            quotes[q.instrument_id] = {"t": q.time, "bp": str(q.bid), "ap": str(q.ask)}
        marks = fresh_marks(connector.session, quotes, now, self.market_session, additional)
        costs = account_costs(connector.session, context.venue.id, now)
        active = connector._orders(context.venue.id, active=True)
        pending_fee = sum((D(".01") for o in active if o.side == "buy"), ZERO)
        cash = connector._balance(context.venue, now).available - costs.total - pending_fee
        strategy_cash = None
        if context.strategy_id is not None:
            strategy = connector.session.get(Strategy, context.strategy_id, populate_existing=True)
            if strategy is None:
                raise ValueError("Missing strategy allocation")
            held = sum((p.cost_basis or ZERO for p in connector.ledger.open_positions(
                strategy_id=strategy.id, mode="paper")), ZERO)
            reserved = sum(((o.size - o.filled_size) * o.limit_price + D(".01")
                            for o in active if o.strategy_id == strategy.id and o.side == "buy"), ZERO)
            strategy_cash = (strategy.allocation_usd + connector.ledger.realized_after_fees(
                strategy_id=strategy.id, mode="paper") - held - reserved
                - costs.by_strategy.get(strategy.id, ZERO))
            if context.side == "buy":
                # A fee cushion for this yet-unreserved new order.
                cash -= D(".01")
                strategy_cash -= D(".01")
        return PaperGuardResult(
            cash_available=max(ZERO, cash), strategy_cash=max(ZERO, strategy_cash) if strategy_cash is not None else None,
            marks=marks, strategy_pnl_offsets={sid: -cost for sid, cost in costs.by_strategy.items()},
            daily_pnl_offset=-costs.daily, valid_until=self.valid_until,
            details={"policy": NAME, "additional_cost_usd": str(costs.total),
                     "unknown_provider_request_ids": list(costs.unknown_request_ids)},
        )
