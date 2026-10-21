"""Disposable-schema Postgres; no provider calls (bead tradingbot-gdc)."""
from datetime import UTC, datetime
from decimal import Decimal as D
import importlib.util
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from tradingbot.ai import jev
from tradingbot.db.models import Incident, JevBudgetControl, JevRequest
from tradingbot.db.session import get_engine

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("resolve_jev_uncertain", ROOT / "ops/resolve_jev_uncertain.py")
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)
EVIDENCE = "TypeSafe billing dashboard checked by owner: no charge for these"


@pytest.fixture
def sessions():
    schema = "test_jevres_" + uuid.uuid4().hex
    base = get_engine()
    with base.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'CREATE TABLE "{schema}".incidents (LIKE public.incidents INCLUDING ALL)'))
    engine = create_engine(base.url, execution_options={"schema_translate_map": {None: schema}})
    JevBudgetControl.__table__.create(engine)
    JevRequest.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def add(sessions, *, status="uncertain", completed=True, actual=None, reserved=jev.MAX_CALL_USD):
    now = datetime.now(UTC)
    request_id = str(uuid.uuid4())
    with sessions.begin() as session:
        session.add(JevRequest(id=request_id, started_ts=now, billing_month=now.date().replace(day=1),
            completed_ts=now if completed else None, completed_month=now.date().replace(day=1) if completed else None,
            correlation_id="paper-trial:1:turn-1-batch-0", questions={}, requested_model="jev-latest",
            status=status, error_code="provider_error" if status == "uncertain" else None, actual_usd=actual,
            reserved_usd=reserved, input_price_per_million=jev.INPUT_PRICE_PER_MILLION,
            pricing_version=jev.PRICING_VERSION, outcomes={}))
    return request_id


def test_resolution_releases_reservation_and_records_evidence(sessions):
    first, second = add(sessions), add(sessions)
    with sessions.begin() as session:
        released = resolver.resolve(session, [first, second], actual_usd=D(0), evidence=EVIDENCE)
    assert released == 2*jev.MAX_CALL_USD
    with sessions() as session:
        for request_id in (first, second):
            row = session.get(JevRequest, request_id)
            assert (row.status, row.actual_usd, row.reserved_usd) == ("error", D(0), D(0))
        assert session.scalar(select(func.sum(JevRequest.reserved_usd))) == 0
        incident, = session.scalars(select(Incident))
    assert incident.details["request_ids"] == [first, second] and incident.details["evidence"] == EVIDENCE
    with sessions() as session:
        assert resolver.uncertain(session) == []


@pytest.mark.parametrize("case", ["ok_row", "in_flight", "short_evidence", "above_reservation", "duplicate"])
def test_refuses_anything_but_evidenced_completed_uncertain_requests(sessions, case):
    target = {"ok_row": lambda: add(sessions, status="ok", actual=D("0.001"), reserved=D(0)),
              "in_flight": lambda: add(sessions, status="pending", completed=False)}.get(case, lambda: add(sessions))()
    ids = [target, target] if case == "duplicate" else [target]
    actual = jev.MAX_CALL_USD + D("0.000001") if case == "above_reservation" else D(0)
    evidence = "dashboard" if case == "short_evidence" else EVIDENCE
    with sessions() as session, pytest.raises(ValueError):
        resolver.resolve(session, ids, actual_usd=actual, evidence=evidence)
    with sessions() as session:
        assert session.get(JevRequest, target).status in {"uncertain", "ok", "pending"}
        assert not list(session.scalars(select(Incident)))


def test_cli_dry_run_writes_nothing_and_commit_persists(sessions, monkeypatch, capsys):
    request_id = add(sessions)
    monkeypatch.setattr(resolver, "SessionLocal", sessions)
    args = ["--resolve", "--actual-usd", "0", "--evidence", EVIDENCE, "--request-id", request_id]
    assert resolver.main(args) == 0 and "dry run" in capsys.readouterr().out
    with sessions() as session:
        assert session.get(JevRequest, request_id).status == "uncertain"
    assert resolver.main(args + ["--commit"]) == 0
    with sessions() as session:
        assert session.get(JevRequest, request_id).status == "error"
    assert resolver.main([]) == 0 and "0 uncertain" in capsys.readouterr().out
