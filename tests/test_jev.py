"""Real isolated Postgres transactions, fake Jev: no network or paid calls."""
from __future__ import annotations

import copy
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from typesafe_sdk import TypeSafeClient

from tradingbot.ai import jev
from tradingbot.db.models import Incident, JevBudgetControl, JevRequest
from tradingbot.db.session import get_engine

SECRET = "fake-jev-key-must-never-be-logged"
QUESTIONS = {
    "gate": {"type": "noul", "instructions": "Does this signal meet the stated policy?"},
    "action": {"type": "choice", "instructions": "Long or flat?",
               "criteria": {"long": "Positive expected edge", "flat": "Otherwise"}},
    "quality": {"type": "score", "instructions": "Signal quality?",
                "criteria": ["weak", "strong"]},
}
BODY = {
    "model": jev.MODEL_ID, "usage": {"input_tokens": 340, "output_tokens": 50},
    "answers": {"gate": {"type": "noul", "noul": 0.8},
                "action": {"type": "choice", "choice": "long",
                           "probabilities": {"long": 0.8, "flat": 0.2}, "confidence": 0.4},
                "quality": {"type": "score", "score": 0.7, "legend": {"0": "weak", "1": "strong"},
                            "probabilities": {"0": 0.3, "1": 0.7}, "confidence": 0.2}},
}


class FakeClient:
    def __init__(self, body=None, error=None, entered=None, release=None):
        self.body = copy.deepcopy(BODY if body is None else body)
        self.error = error
        self.entered, self.release = entered, release
        self.calls = []
        self.closed = False

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        if self.entered:
            self.entered.set()
            assert self.release.wait(10)
        if self.error:
            raise self.error
        return SimpleNamespace(model_dump=lambda **_: self.body)

    def close(self):
        self.closed = True


@pytest.fixture
def sessions(monkeypatch):
    # Disposable schema, independent committed connections for real concurrency.
    schema = "test_jev_" + uuid.uuid4().hex
    base = get_engine()
    with base.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'CREATE TABLE "{schema}".incidents (LIKE public.incidents INCLUDING ALL)'))
    engine = create_engine(base.url, execution_options={"schema_translate_map": {None: schema}})
    JevBudgetControl.__table__.create(engine)
    JevRequest.__table__.create(engine)
    monkeypatch.setattr(jev, "get_settings", lambda: SimpleNamespace(typesafe_api_key=SecretStr(SECRET)))
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def client(sessions, fake=None):
    fake = fake or FakeClient()
    return jev.JevClient(session_factory=sessions, client_factory=lambda _: fake), fake


def decide(wrapper, **kwargs):
    return wrapper.decide(state={"symbol": "SPY", "signal": 1}, questions=QUESTIONS, **kwargs)


def rows(sessions):
    with sessions() as session:
        return list(session.scalars(select(JevRequest).order_by(JevRequest.started_ts)))


def seed_spend(sessions, cost, *, pending=False, month=None):
    now = datetime.now(UTC)
    month = month or now.date().replace(day=1)
    with sessions.begin() as session:
        session.add(JevRequest(id=str(uuid.uuid4()), started_ts=now, billing_month=month,
                              completed_ts=None if pending else now,
                              completed_month=None if pending else month,
                              questions={}, requested_model=jev.MODEL_ID,
                              status="pending" if pending else "ok",
                              reserved_usd=cost if pending else Decimal(0),
                              actual_usd=None if pending else cost,
                              input_price_per_million=jev.INPUT_PRICE_PER_MILLION,
                              pricing_version=jev.PRICING_VERSION, outcomes={}))


def test_exact_usage_audit_alias_pin_and_outcome(sessions):
    wrapper, fake = client(sessions)
    result = decide(wrapper, model="jev-latest", correlation_id="trial:42/event:1")
    assert result.cost_usd == Decimal("0.00001428")
    assert result.model_id == jev.MODEL_ID
    row, = rows(sessions)
    assert row.id == result.request_id and row.status == "ok"
    assert row.correlation_id == "trial:42/event:1"
    assert row.requested_model == "jev-latest" and row.model_id == jev.MODEL_ID
    assert len(row.state_hash) == 64 and "state" not in row.questions
    assert row.questions == QUESTIONS and row.answers == BODY["answers"]
    assert row.input_tokens == 340 and row.output_tokens == 50
    assert row.actual_usd == result.cost_usd and row.reserved_usd == 0
    assert row.latency_ms >= 0 and row.pricing_version == jev.PRICING_VERSION
    call, = fake.calls
    assert call["model"] == jev.MODEL_ID and call["retry"].max_retries == 0
    assert call["timeout"] == jev.TIMEOUT_SECONDS and fake.closed
    observed = datetime.now(UTC)
    assert wrapper.record_outcome(result.request_id, "gate", True, observed_at=observed)
    assert wrapper.record_outcome(result.request_id, "gate", True, observed_at=observed)
    assert not wrapper.record_outcome(result.request_id, "gate", False, observed_at=observed)
    assert not wrapper.record_outcome(result.request_id, "action", "other", observed_at=observed)
    assert not wrapper.record_outcome(result.request_id, "quality", True, observed_at=observed)
    assert not wrapper.record_outcome(result.request_id, "gate", True,
                                      observed_at=observed + timedelta(days=1))
    assert wrapper.record_outcome(result.request_id, "action", "flat", observed_at=observed)
    assert wrapper.record_outcome(result.request_id, "quality", 0, observed_at=observed)
    assert rows(sessions)[0].outcomes["gate"]["value"] is True


def test_cap_blocks_without_call_and_persists_incident(sessions):
    seed_spend(sessions, jev.MONTHLY_CAP_USD - jev.MAX_CALL_USD + Decimal("0.000000001"))
    wrapper, fake = client(sessions)
    assert decide(wrapper) is None and fake.calls == []
    refused = rows(sessions)[-1]
    assert refused.status == "refused" and refused.error_code == "monthly_cap"
    assert refused.questions == QUESTIONS and refused.reserved_usd == 0
    with sessions() as session:
        incident = session.scalar(select(Incident))
        assert incident.details["code"] == "monthly_cap"


def test_concurrent_last_reservation_is_shared_between_clients(sessions):
    seed_spend(sessions, jev.MONTHLY_CAP_USD - jev.MAX_CALL_USD)
    entered, release = Event(), Event()
    first, _ = client(sessions, FakeClient(entered=entered, release=release))
    second, second_fake = client(sessions)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(decide, first)
        try:
            assert entered.wait(10)
            # The first request is committed, but has not settled yet.
            assert decide(second) is None
            assert not second_fake.calls
        finally:
            release.set()
        assert future.result(timeout=10) is not None
    assert {r.status for r in rows(sessions)} == {"ok", "refused"}


def test_timeout_and_restart_retain_reservation_and_no_secret(sessions, caplog):
    seed_spend(sessions, jev.MONTHLY_CAP_USD - jev.MAX_CALL_USD)
    wrapper, fake = client(sessions, FakeClient(error=TimeoutError(SECRET)))
    with caplog.at_level(logging.DEBUG):
        assert decide(wrapper) is None
        restarted, later = client(sessions)
        assert decide(restarted) is None
    failed = next(r for r in rows(sessions) if r.status == "uncertain")
    assert failed.reserved_usd == jev.MAX_CALL_USD and failed.actual_usd is None
    assert fake.closed and len(fake.calls) == 1 and not later.calls
    assert SECRET not in caplog.text
    with sessions() as session:
        assert SECRET not in json.dumps([i.details for i in session.scalars(select(Incident))])


def test_pending_crash_survives_month_rollover(sessions):
    prior = (datetime.now(UTC).date().replace(day=1) - timedelta(days=1)).replace(day=1)
    seed_spend(sessions, jev.MONTHLY_CAP_USD, pending=True, month=prior)
    wrapper, fake = client(sessions)
    assert decide(wrapper) is None and not fake.calls


def test_old_settled_spend_does_not_consume_new_month(sessions):
    prior = (datetime.now(UTC).date().replace(day=1) - timedelta(days=1)).replace(day=1)
    seed_spend(sessions, jev.MONTHLY_CAP_USD, month=prior)
    wrapper, fake = client(sessions)
    assert decide(wrapper) is not None and len(fake.calls) == 1


def test_call_spanning_months_counts_actual_in_both(sessions, monkeypatch):
    before = datetime(2030, 1, 31, 23, 59, 59, tzinfo=UTC)
    after = before + timedelta(seconds=2)
    clock = iter([before, after])
    monkeypatch.setattr(jev, "_now", lambda _: next(clock))
    wrapper, _ = client(sessions)
    assert decide(wrapper) is not None
    row, = rows(sessions)
    assert row.billing_month == before.date().replace(day=1)
    assert row.completed_month == after.date().replace(day=1)
    # Only the actual charge is needed to deny another maximum reservation.
    seed_spend(sessions, jev.MONTHLY_CAP_USD - jev.MAX_CALL_USD, month=row.completed_month)
    monkeypatch.setattr(jev, "_now", lambda _: after)
    next_client, fake = client(sessions)
    assert decide(next_client) is None and not fake.calls


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": None, "output_tokens": 1},
    {"input_tokens": True, "output_tokens": 1}, {"input_tokens": 1.0, "output_tokens": 1},
    {"input_tokens": -1, "output_tokens": 1}, {"input_tokens": 1, "output_tokens": -1}])
def test_untrusted_usage_keeps_maximum_reservation(sessions, usage):
    body = copy.deepcopy(BODY)
    body["usage"] = usage
    wrapper, _ = client(sessions, FakeClient(body))
    assert decide(wrapper) is None
    row, = rows(sessions)
    assert row.status == "uncertain" and row.reserved_usd == jev.MAX_CALL_USD
    assert row.actual_usd is None and row.error_code == "invalid_usage"


@pytest.mark.parametrize("alter", [
    lambda b: b["answers"].pop("gate"),
    lambda b: b["answers"]["gate"].update(noul=2),
    lambda b: b["answers"]["gate"].update(noul=True),
    lambda b: b["answers"]["action"].update(confidence=-1),
    lambda b: b["answers"]["action"].update(choice="flat"),
    lambda b: b["answers"]["action"]["probabilities"].update(long=0.5),
    lambda b: b["answers"]["quality"].update(score=0.1),
    lambda b: b["answers"]["quality"].update(legend={"0": "changed", "1": "strong"}),
])
def test_invalid_answers_are_charged_but_no_decision(sessions, alter):
    body = copy.deepcopy(BODY)
    alter(body)
    wrapper, _ = client(sessions, FakeClient(body))
    assert decide(wrapper) is None
    row, = rows(sessions)
    assert row.status == "error" and row.reserved_usd == 0
    assert row.actual_usd == Decimal("0.00001428") and row.error_code == "invalid_answers"


def test_two_decimal_rounded_score_is_accepted(sessions):
    # Observed live 2026-10-05: Jev rounds to 2 dp, so the score (0.44) is not
    # the exact probability-weighted mean (0.45) of the rounded probabilities.
    questions = {"quality": {"type": "score", "instructions": "Signal quality?",
                             "criteria": ["weak", "fair", "strong", "overwhelming"]}}
    body = copy.deepcopy(BODY)
    body["answers"] = {"quality": {
        "type": "score", "score": 0.44, "confidence": 0.56,
        "legend": {"0": "weak", "1": "fair", "2": "strong", "3": "overwhelming"},
        "probabilities": {"0": 0.65, "1": 0.26, "2": 0.08, "3": 0.01}}}
    wrapper, _ = client(sessions, FakeClient(body))
    decision = wrapper.decide(state={"symbol": "SPY"}, questions=questions)
    assert decision is not None and decision.answers["quality"]["score"] == 0.44
    body["answers"]["quality"]["score"] = 0.6  # beyond rounding: still rejected
    wrapper, _ = client(sessions, FakeClient(body))
    assert wrapper.decide(state={"symbol": "SPY"}, questions=questions) is None


def test_provider_error_records_exception_class_only(sessions):
    wrapper, _ = client(sessions, FakeClient(error=TimeoutError(SECRET)))
    assert decide(wrapper) is None
    with sessions() as session:
        details, = [i.details for i in session.scalars(select(Incident))]
    assert details["code"] == "provider_error" and details["error_class"] == "TimeoutError"
    assert SECRET not in json.dumps(details)


@pytest.mark.parametrize("change,code", [
    ({"model": "jev-new-unreviewed"}, "unexpected_model"),
    ({"usage": {"input_tokens": jev.MAX_INPUT_TOKENS + 1, "output_tokens": 1}}, "token_bound_exceeded"),
    ({"usage": {"input_tokens": 2**63 - 1, "output_tokens": 1}}, "token_bound_exceeded"),
])
def test_provider_contract_change_halts_future_calls(sessions, change, code):
    body = copy.deepcopy(BODY)
    body.update(change)
    wrapper, _ = client(sessions, FakeClient(body))
    assert decide(wrapper) is None
    restarted, fake = client(sessions)
    assert decide(restarted) is None and not fake.calls
    with sessions() as session:
        assert session.get(JevBudgetControl, 1).halt_reason == code
    first = rows(sessions)[0]
    assert first.answers == BODY["answers"]
    assert first.model_id == body["model"]


def test_storage_failure_before_call_never_calls_provider(sessions):
    def broken():
        raise RuntimeError(SECRET)
    fake = FakeClient()
    wrapper = jev.JevClient(session_factory=broken, client_factory=lambda _: fake)
    assert decide(wrapper) is None and not fake.calls


def test_existing_inflight_call_cannot_release_decision_after_contract_halt(sessions):
    entered, release = Event(), Event()
    first, _ = client(sessions, FakeClient(entered=entered, release=release))
    wrong_model = copy.deepcopy(BODY)
    wrong_model["model"] = "unexpected"
    second, _ = client(sessions, FakeClient(wrong_model))
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(decide, first)
        try:
            assert entered.wait(10)
            assert decide(second) is None
        finally:
            release.set()
        assert future.result(timeout=10) is None
    codes = {r.error_code for r in rows(sessions)}
    assert codes == {"unexpected_model", "provider_contract_halted"}


def test_settlement_failure_leaves_committed_reservation(sessions, monkeypatch):
    original = jev._lock
    calls = 0
    def fail_second(session):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError(SECRET)
        return original(session)
    monkeypatch.setattr(jev, "_lock", fail_second)
    wrapper, fake = client(sessions)
    assert decide(wrapper) is None and len(fake.calls) == 1
    row, = rows(sessions)
    assert row.status == "pending" and row.reserved_usd == jev.MAX_CALL_USD


@pytest.mark.parametrize("secret", [SECRET, 'fake-key-"quoted"', "fake-key-\\escaped"])
def test_secret_in_request_is_never_sent_or_audited(sessions, caplog, monkeypatch, secret):
    monkeypatch.setattr(jev, "get_settings", lambda: SimpleNamespace(typesafe_api_key=SecretStr(secret)))
    wrapper, fake = client(sessions)
    assert wrapper.decide(state={"oops": secret}, questions=QUESTIONS) is None
    assert wrapper.decide(state="ok", questions={"x": {"type": "noul", "instructions": secret}}) is None
    assert not fake.calls and not rows(sessions) and secret not in caplog.text


@pytest.mark.parametrize("secret", [SECRET, 'fake-key-"quoted"'])
def test_secret_in_response_or_exception_is_not_persisted(sessions, caplog, monkeypatch, secret):
    monkeypatch.setattr(jev, "get_settings", lambda: SimpleNamespace(typesafe_api_key=SecretStr(secret)))
    body = copy.deepcopy(BODY)
    body["extra"] = secret
    wrapper, _ = client(sessions, FakeClient(body))
    assert decide(wrapper) is None
    assert rows(sessions)[0].answers is None and secret not in caplog.text


def test_missing_key_and_invalid_request_are_fail_closed(sessions, monkeypatch):
    wrapper, fake = client(sessions)
    for kwargs in ({"state": 42, "questions": QUESTIONS},
                   {"state": "ok", "questions": {}},
                   {"state": "ok", "questions": QUESTIONS, "model": "unreviewed"},
                   {"state": float("nan"), "questions": QUESTIONS}):
        assert wrapper.decide(**kwargs) is None
    monkeypatch.setattr(jev, "get_settings", lambda: SimpleNamespace(typesafe_api_key=None))
    assert decide(wrapper) is None and not fake.calls


@pytest.mark.parametrize("http_status", [200, 429, 500])
def test_real_sdk_wire_contract_and_retries_disabled(sessions, monkeypatch, http_status):
    seen = []
    def transport(request):
        seen.append(request)
        return httpx2.Response(http_status, json=BODY if http_status == 200 else {"error": SECRET})
    def factory(**kwargs):
        assert kwargs["retry"].max_retries == 0 and kwargs["model"] == jev.MODEL_ID
        assert kwargs["base_url"] == "https://api.typesafe.ai"
        return TypeSafeClient(**kwargs, transport=httpx2.MockTransport(transport))
    monkeypatch.setattr(jev, "TypeSafeClient", factory)
    wrapper = jev.JevClient(session_factory=sessions)
    result = decide(wrapper)
    assert (result is not None) == (http_status == 200)
    assert len(seen) == 1 and str(seen[0].url) == "https://api.typesafe.ai/v1/systemone"
    assert json.loads(seen[0].content)["model"] == jev.MODEL_ID


@pytest.mark.parametrize("state,questions", [
    # state + longest question beyond 32k tokens (2026-10-05: 76 KB states).
    ({"blob": "9" * 50_000}, QUESTIONS),
    # each question fits with the state, but the whole request exceeds 64k.
    ({"blob": "9" * 30_000}, {f"q{i}": {"type": "noul", "instructions": "x" * 600} for i in range(110)}),
])
def test_oversized_request_fails_closed_before_reservation(sessions, state, questions):
    wrapper, fake = client(sessions)
    assert wrapper.decide(state=state, questions=questions) is None
    assert not fake.calls and not rows(sessions)
    with sessions() as session:
        details, = [i.details for i in session.scalars(select(Incident))]
    assert details["code"] == "oversized_request"


def test_token_estimate_is_conservative_against_billed_calls():
    # A billed 2026-10-05 J2 call: 57,506 B state + 7,171 B questions = 33,979 tokens.
    state = {"blob": "9" * 57_490}
    questions = {f"q{i}": {"type": "noul", "instructions": "x" * 1_180} for i in range(6)}
    longest, whole = jev.estimated_tokens(state, questions)
    assert whole > 33_979 and longest > (57_506 + 1_195) / 1.9
    assert jev.within_token_limits({"symbol": "SPY"}, QUESTIONS)


PLAIN_SECRET = "fake_jev_key_must_never_be_logged"  # would otherwise pass the error_type pattern


@pytest.mark.parametrize("body,expected", [
    ({"detail": {"error_type": "max_tokens_exceeded"}}, {"http_status": 400, "provider_error_type": "max_tokens_exceeded"}),
    ({"detail": {"error_type": PLAIN_SECRET}}, {"http_status": 400}),
    ({"detail": {"error_type": "Free text: " + "x" * 80}}, {"http_status": 400}),
    ({"detail": [{"loc": ["body", "state"], "msg": SECRET, "type": "x"}]}, {"http_status": 400}),
])
def test_provider_http_error_records_status_and_machine_type_only(sessions, monkeypatch, body, expected):
    monkeypatch.setattr(jev, "get_settings", lambda: SimpleNamespace(typesafe_api_key=SecretStr(PLAIN_SECRET)))
    def factory(**kwargs):
        transport = httpx2.MockTransport(lambda request: httpx2.Response(400, json=body))
        return TypeSafeClient(**kwargs, transport=transport)
    monkeypatch.setattr(jev, "TypeSafeClient", factory)
    assert decide(jev.JevClient(session_factory=sessions)) is None
    with sessions() as session:
        details, = [i.details for i in session.scalars(select(Incident))]
    assert details["code"] == "provider_error" and details["error_class"] == "TypeSafeBadRequestError"
    assert {k: details[k] for k in details if k in ("http_status", "provider_error_type")} == expected
    assert SECRET not in json.dumps(details) and PLAIN_SECRET not in json.dumps(details)


def test_only_wrapper_imports_provider_in_production_code():
    root = Path(__file__).parents[1] / "src" / "tradingbot"
    for path in root.rglob("*.py"):
        if path != root / "ai" / "jev.py":
            assert "typesafe_sdk" not in path.read_text()
