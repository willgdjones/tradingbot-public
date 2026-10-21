#!/usr/bin/env python3
"""List or resolve uncertain Jev charges using external billing evidence (bead gdc).

An uncertain request (no usage reported, e.g. HTTP 400) keeps its maximum
reservation forever, and while any remains, account_costs() reports it as an
unknown charge that blocks every AI paper arm's qualification. Only TypeSafe
billing evidence that the owner checked (dashboard, invoice or support reply)
may settle one. The request's actual charge becomes that amount, its
reservation is released, and an incident records the evidence. Without
--commit nothing is written.

    uv run python ops/resolve_jev_uncertain.py                        # list
    uv run python ops/resolve_jev_uncertain.py --resolve --actual-usd 0 \\
        --evidence "TypeSafe dashboard, checked by owner 2026-10-07: no 10-05 charges for these" \\
        --request-id <id> [...] [--commit]
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from tradingbot.ai import jev
from tradingbot.db.models import Incident, JevRequest
from tradingbot.db.session import SessionLocal

MIN_EVIDENCE_CHARS = 20


def uncertain(session):
    return list(session.scalars(select(JevRequest).where(
        JevRequest.status == "uncertain").order_by(JevRequest.started_ts, JevRequest.id)))


def resolve(session, request_ids, *, actual_usd, evidence):
    """Settle the named uncertain requests at ``actual_usd`` each; caller commits.

    Must start its transaction: the budget lock sets the isolation level.
    """
    evidence = (evidence or "").strip()
    if len(evidence) < MIN_EVIDENCE_CHARS:
        raise ValueError("Name the billing evidence (source, who checked it and when)")
    if not request_ids or len(set(request_ids)) != len(request_ids):
        raise ValueError("Name each request exactly once")
    if not isinstance(actual_usd, Decimal) or not actual_usd.is_finite() or actual_usd < 0:
        raise ValueError("Actual charge must be a finite non-negative Decimal")
    jev._lock(session)  # serialize with JevClient admission and settlement
    released = Decimal(0)
    for request_id in request_ids:
        row = session.get(JevRequest, request_id, populate_existing=True)
        if (row is None or row.status != "uncertain" or row.actual_usd is not None
                or row.completed_ts is None or row.reserved_usd <= 0):
            raise ValueError(f"Not a completed uncertain request: {request_id}")
        if actual_usd > row.reserved_usd:
            raise ValueError("Actual charge exceeds the reservation; the cap audit needs review")
        released += row.reserved_usd
        row.actual_usd, row.reserved_usd, row.status = actual_usd, Decimal(0), "error"
    session.add(Incident(severity="info", category="api_error",
        message="Jev uncertain charges resolved from billing evidence",
        details={"provider": "jev", "request_ids": list(request_ids), "actual_usd_each": str(actual_usd),
                 "released_reservation_usd": str(released), "evidence": evidence}))
    session.flush()
    return released


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument("--request-id", action="append", default=[])
    parser.add_argument("--actual-usd")
    parser.add_argument("--evidence")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        if not args.resolve:
            rows = uncertain(session)
            for row in rows:
                print(f"{row.id}  {row.started_ts:%Y-%m-%d %H:%M:%S%z}  {row.error_code or '-':16} "
                      f"reserved={row.reserved_usd:.6f}  {row.correlation_id or ''}")
            print(f"{len(rows)} uncertain, {sum((r.reserved_usd for r in rows), Decimal(0)):.6f} USD reserved")
            return 0
        try:
            actual = Decimal(args.actual_usd or "")
        except InvalidOperation:
            parser.error("--actual-usd must be a decimal amount")
        released = resolve(session, args.request_id, actual_usd=actual, evidence=args.evidence)
        if args.commit:
            session.commit()
        else:
            session.rollback()
        print(f"{'resolved' if args.commit else 'dry run, rolled back'}: {len(args.request_id)} requests, "
              f"{released:.6f} USD reservation released, actual {actual} USD each")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
