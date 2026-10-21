"""Prove a T+1 counterfactual from consistent native settlement observations.

No weekday or exchange-session approximation is permitted. Each native T+N
observation constrains exactly N eligible settlement dates in (trade, settle],
and its observed settlement date is eligible. Only logically forced dates are
used; contradictory observations and ambiguous next dates fail closed.

SEC transition evidence:
https://www.sec.gov/newsroom/press-releases/2017-163 (2017-09-05 T+3 -> T+2)
https://www.sec.gov/exams/educationhelpguidesfaqs/t1-faq (2024-05-28 T+2 -> T+1)
The source must represent standard-cycle transactions, not bespoke agreements.
This is a derived research calendar, never evidence of actual account funding.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class PublishedSettlementCalendar:
    """Source-bound schedule, separate from settlement completion/broker credit.

    The evidence file enumerates every year's primary holiday notices and
    reconciles exceptional closures. Loading it is NOT strategy admission.
    Never extrapolate this finite calendar or use its dates as proof that an
    account has been credited. The optional cash convention below deliberately
    waits until the next regular session after completed settlement.
    """

    start: date
    end: date
    eligible: tuple[date, ...]
    rollovers: tuple[tuple[date, date], ...]

    @classmethod
    def from_evidence(cls, path: Path) -> "PublishedSettlementCalendar":
        evidence = json.loads(path.read_text())
        claimed_hash = evidence.pop("sha256")
        body = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(body).hexdigest() != claimed_hash:
            raise ValueError("settlement evidence hash mismatch")
        if evidence["status"] != "SCHEDULE_RECONCILED_NOT_STRATEGY_ADMISSION":
            raise ValueError("unreconciled settlement evidence")
        start = date.fromisoformat(evidence["coverage_start"])
        end = date.fromisoformat(evidence["coverage_end_inclusive"])
        if start > end or [r["year"] for r in evidence["years"]] != list(range(start.year, end.year + 1)):
            raise ValueError("missing annual settlement coverage")
        sources = [source for year in evidence["years"] for source in year["sources"]]
        if any(not year["sources"] for year in evidence["years"]):
            raise ValueError("missing annual source evidence")
        sources += evidence.get("auxiliary_sources", [])
        source_names = {source["name"] for source in sources}
        for source in sources:
            if len(source["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["sha256"]):
                raise ValueError("invalid primary source hash")
        closed = set()
        for row in evidence["closed_weekdays"]:
            day = date.fromisoformat(row["date"])
            if (not start <= day <= end or day.weekday() > 4 or day in closed
                    or not row["sources"] or not set(row["sources"]) <= source_names):
                raise ValueError("invalid holiday closure evidence")
            closed.add(day)
        eligible = tuple(start + timedelta(days=i) for i in range((end - start).days + 1)
                         if (start + timedelta(days=i)).weekday() < 5
                         and start + timedelta(days=i) not in closed)
        digest = hashlib.sha256(("\n".join(map(str, eligible)) + "\n").encode()).hexdigest()
        if digest != evidence["eligibility_sha256"] or len(eligible) != evidence["scheduled_eligible_day_count"]:
            raise ValueError("settlement schedule digest mismatch")
        rollovers = []
        for row in evidence["operational_rollovers"]:
            scheduled, completed = date.fromisoformat(row["scheduled_date"]), date.fromisoformat(row["completion_date"])
            if (scheduled not in eligible or completed not in eligible or completed <= scheduled
                    or scheduled in dict(rollovers) or not row.get("source", {}).get("sha256")):
                raise ValueError("invalid settlement completion evidence")
            rollovers.append((scheduled, completed))
        return cls(start, end, eligible, tuple(rollovers))

    def dates_after(self, trade: date) -> tuple[date, date]:
        """Return (scheduled T+1 date, documented completion date)."""
        index = bisect_right(self.eligible, trade)
        if not self.start <= trade < self.end or index == len(self.eligible):
            raise ValueError("trade outside finite settlement evidence")
        scheduled = self.eligible[index]
        return scheduled, dict(self.rollovers).get(scheduled, scheduled)

    def conservative_cash_release(self, trade: date, regular_opens: list[datetime]) -> datetime:
        """Proposed replay convention; NOT observed Alpaca account availability.

        Caller must supply its validated regular-session opens, with the next
        session included. This convention needs dataset preregistration before
        strategy use. A known central settlement rollover is never skipped.
        """
        if not regular_opens or any(t.tzinfo is None or t.utcoffset() is None for t in regular_opens):
            raise ValueError("missing timezone-aware regular-session opens")
        if regular_opens != sorted(set(regular_opens)):
            raise ValueError("regular-session opens must be unique and ordered")
        _, completed = self.dates_after(trade)
        for opened in regular_opens:
            if completed < opened.astimezone(ZoneInfo("America/New_York")).date() <= self.end:
                return opened
        raise ValueError("missing session after settlement completion")


def native_cycle(trade_date: date) -> int:
    if trade_date < date(2000,1,1):
        raise ValueError('calendar precedes supported year-2000 research coverage')
    if trade_date < date(2017,9,5):
        return 3
    return 2 if trade_date < date(2024,5,28) else 1


def reconstruct_t1(native: dict[date, date], required: list[date]) -> dict[date, date]:
    """Return only proven unique next eligible dates, validating ALL inputs.

    Simple constraint propagation can leave mathematically solvable cases
    unresolved; that is a conservative refusal, never an invented cash date.
    Padding source coverage on both sides can resolve boundary ambiguity.
    """
    if not native or not required or any(day not in native for day in required):
        raise ValueError('missing native calendar coverage')
    known = {settle:1 for settle in native.values()}
    equations = []
    for trade, settle in sorted(native.items()):
        days = (settle - trade).days
        cycle = native_cycle(trade)
        if not cycle <= days <= 31:
            raise ValueError(f'inconsistent native calendar: {trade} -> {settle} cannot contain {cycle} settlement days')
        dates = tuple(trade + timedelta(days=i) for i in range(1,days+1))
        equations.append((trade, settle, dates, cycle))
    changed = True
    while changed:
        changed = False
        for trade, settle, dates, cycle in equations:
            remaining = cycle - sum(known.get(d, 0) for d in dates)
            unknown = [d for d in dates if d not in known]
            if remaining < 0 or remaining > len(unknown):
                raise ValueError(f'inconsistent native calendar constraints: {trade} -> {settle}, T+{cycle}')
            if unknown and remaining in {0,len(unknown)}:
                known.update({d:int(remaining>0) for d in unknown})
                changed = True
    result = {}
    for trade in required:
        for i in range(1,(native[trade]-trade).days+1):
            day = trade + timedelta(days=i)
            if day not in known:
                raise ValueError(f'ambiguous T+1 date after {trade}: eligibility of {day} is unproved')
            if known[day]:
                result[trade] = day
                break
        if trade not in result:
            raise ValueError(f'no proven T+1 settlement after {trade}')
    return result
