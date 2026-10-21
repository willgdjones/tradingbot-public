"""The sole Jev entry point: reserve, call once, settle, then release a decision.

The $20 global UTC-calendar-month budget is not caller configurable. Postgres
serializes admissions; an uncertain charge retains its maximum reservation,
including in future months. No committed audit means no returned decision.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient

from tradingbot.config import get_settings
from tradingbot.db.models import Incident, JevBudgetControl, JevRequest
from tradingbot.db.session import SessionLocal

MONTHLY_CAP_USD = Decimal("20")
INPUT_PRICE_PER_MILLION = Decimal("0.042")
MODEL_ID = "jev-1.13.0"
# Verified https://docs.typesafe.ai/models on 2026-10-02. Output is free.
PRICING_VERSION = "2026-10-02/jev-1.13.0/input-0.042-per-M/output-free"
# Published 64k context; use 65,536 as a conservative interpretation of 'k'.
MAX_INPUT_TOKENS = 65_536
MAX_CALL_USD = INPUT_PRICE_PER_MILLION * MAX_INPUT_TOKENS / Decimal(1_000_000)
# https://docs.typesafe.ai/models (2026-10-05): "64k tokens per request; 32k
# tokens for state plus the longest question". Exceeding it is HTTP 400
# max_tokens_exceeded. Billed calls averaged 1.9 JSON bytes per token on
# 2026-10-05; estimating at 1.5 keeps the pre-flight check conservative.
MAX_STATE_QUESTION_TOKENS = 32_768
ESTIMATE_BYTES_PER_TOKEN = 1.5
TIMEOUT_SECONDS = 10.0
_LOCK_ID = 0x4A455642554447  # same transaction lock for all callers/months
_MODELS = {MODEL_ID, "jev-latest", "jev-preview"}
_LOG = logging.getLogger(__name__)
_QUESTION_TYPES = {"noul": Noul, "choice": Choice, "score": Score}


@dataclass(frozen=True)
class JevDecision:
    request_id: str
    model_id: str
    answers: dict[str, dict]
    cost_usd: Decimal
    latency_ms: int


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _contains_secret(value: Any, secret: str) -> bool:
    # Inspect decoded strings too: JSON escaping may hide a literal key from
    # a substring check on the serialized envelope.
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        return any(_contains_secret(k, secret) or _contains_secret(v, secret)
                   for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_secret(v, secret) for v in value)
    return False


def _sdk_client(key: str) -> TypeSafeClient:
    # SDK debug logs include bodies. Only our sanitized structured audit is used.
    logging.getLogger("typesafe_sdk").disabled = True
    return TypeSafeClient(api_key=key, model=MODEL_ID,
                          base_url="https://api.typesafe.ai",
                          retry=RetryPolicy(max_retries=0), timeout=TIMEOUT_SECONDS)


def _now(session: Session) -> datetime:
    return session.scalar(select(func.clock_timestamp())).astimezone(UTC)


def _lock(session: Session) -> JevBudgetControl:
    if session.get_bind().dialect.name != "postgresql":
        raise ValueError("Jev budgets require Postgres")
    # A snapshot taken before waiting for the advisory lock could otherwise
    # miss the preceding caller's commit under REPEATABLE READ.
    session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    session.execute(text("SET LOCAL lock_timeout = '5s'"))
    session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})
    control = session.get(JevBudgetControl, 1)
    if control is None:
        control = JevBudgetControl(id=1)
        session.add(control)
        session.flush()
    return control


def _incident(session: Session, code: str, request_id: str | None = None,
              error_class: str | None = None, provider: dict | None = None) -> None:
    # Never include exception text, SDK bodies, prompts, or credential values.
    # The bare exception class name is safe and is kept for diagnosis.
    details = {"provider": "jev", "code": code, "request_id": request_id}
    if error_class:
        details["error_class"] = error_class
    details.update(provider or {})
    session.add(Incident(severity="warning", category="api_error",
                         message="Jev returned no decision: " + code, details=details))


_ERROR_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _provider_detail(error: Exception, secret: str) -> dict:
    """HTTP status and the provider's machine ``error_type`` only, never body text."""
    status = getattr(error, "status", None)
    if type(status) is not int or not 400 <= status <= 599:
        return {}
    detail = {"http_status": status}
    body = getattr(error, "body", None)
    inner = body.get("detail") if isinstance(body, dict) else None
    kind = inner.get("error_type") if isinstance(inner, dict) else None
    if isinstance(kind, str) and _ERROR_TYPE.fullmatch(kind) and secret not in kind:
        detail["provider_error_type"] = kind
    return detail


def estimated_tokens(state: Any, questions: dict) -> tuple[int, int]:
    """Conservative (state + longest question, whole request) input-token estimates.

    ``questions`` must be in wire form (``_validate_questions`` output).
    """
    state_bytes = len(_json(state).encode())
    sizes = [len(_json(q).encode()) for q in questions.values()]
    return (math.ceil((state_bytes + max(sizes, default=0)) / ESTIMATE_BYTES_PER_TOKEN),
            math.ceil((state_bytes + sum(sizes)) / ESTIMATE_BYTES_PER_TOKEN))


def within_token_limits(state: Any, questions: dict) -> bool:
    longest, whole = estimated_tokens(state, questions)
    return longest <= MAX_STATE_QUESTION_TOKENS and whole <= MAX_INPUT_TOKENS


def _validate_questions(questions: Any) -> dict:
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 128:
        raise ValueError("Invalid questions")
    result = {}
    for name, question in questions.items():
        if not isinstance(name, str) or not 1 <= len(name) <= 128:
            raise ValueError("Invalid question name")
        if not isinstance(question, dict) or question.get("type") not in _QUESTION_TYPES:
            raise ValueError("Invalid question type")
        value = _QUESTION_TYPES[question["type"]].model_validate(question).model_dump(mode="json")
        if not value.get("instructions"):
            raise ValueError("Missing instructions")
        if value["type"] == "choice" and not 2 <= len(value["criteria"]) <= 255:
            raise ValueError("Invalid choice criteria")
        if value["type"] == "score" and not 2 <= len(value["criteria"]) <= 10:
            raise ValueError("Invalid score criteria")
        result[name] = value
    return result


_HALF_CENT = 0.005  # maximum error of one value rounded to 2 dp


def _probability(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid probability")
    return float(value)


def _validate_answers(answers: Any, questions: dict) -> dict:
    if not isinstance(answers, dict) or answers.keys() != questions.keys():
        raise ValueError("Answers do not match questions")
    for name, answer in answers.items():
        question = questions[name]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ValueError("Wrong answer type")
        kind = answer["type"]
        if kind == "noul":
            _probability(answer.get("noul"))
            continue
        _probability(answer.get("confidence"))
        probabilities = answer.get("probabilities")
        expected = (set(question["criteria"]) if kind == "choice" else
                    {str(i) for i in range(len(question["criteria"]))})
        if not isinstance(probabilities, dict) or set(probabilities) != expected:
            raise ValueError("Incomplete probabilities")
        values = [_probability(p) for p in probabilities.values()]
        # Jev reports probabilities (and score) rounded to 2 dp, so derived
        # identities can only hold to that rounding, not to float precision.
        if not math.isclose(sum(values), 1.0, abs_tol=_HALF_CENT * len(values) + 1e-9, rel_tol=0):
            raise ValueError("Probabilities do not sum to one")
        if kind == "choice":
            choice = answer.get("choice")
            if choice not in expected or probabilities[choice] < max(values) - 1e-6:
                raise ValueError("Invalid choice")
        else:
            score = answer.get("score")
            weighted = sum(int(k) * p for k, p in probabilities.items())
            tolerance = _HALF_CENT * (1 + sum(range(len(expected)))) + 1e-9
            if (type(score) not in (int, float) or not math.isfinite(score)
                    or not math.isclose(score, weighted, abs_tol=tolerance, rel_tol=0)):
                raise ValueError("Invalid score")
            legend = answer.get("legend")
            if legend != {str(i): v for i, v in enumerate(question["criteria"])}:
                raise ValueError("Wrong score legend")
    return answers


class JevClient:
    """Synchronous fail-closed provider wrapper, with injectable test dependencies.

    ``None`` always means no trade. ``correlation_id`` should identify the trial
    and observation so stored probabilities can be joined to realized outcomes.
    Aliases are accepted but resolved locally to the reviewed versioned model.
    """

    def __init__(self, *, session_factory: Callable[[], Session] = SessionLocal,
                 client_factory: Callable[[str], Any] = _sdk_client):
        self._sessions = session_factory
        self._clients = client_factory

    def _failure(self, code: str) -> None:
        _LOG.warning("Jev returned no decision: %s", code)
        try:
            with self._sessions() as session, session.begin():
                _incident(session, code)
        except Exception:
            _LOG.error("Jev incident persistence failed; no decision")

    def _admit(self, *, state_hash: str, questions: dict, model: str,
               correlation_id: str | None) -> str | None:
        with self._sessions() as session, session.begin():
            control = _lock(session)
            now = _now(session)
            month = now.date().replace(day=1)
            # Calls crossing a UTC month boundary count in every spanned month.
            actual = session.scalar(select(func.coalesce(func.sum(JevRequest.actual_usd), 0)).where(
                JevRequest.billing_month <= month, JevRequest.completed_month >= month))
            # Carry unresolved charges across month boundaries, including crashes.
            outstanding = session.scalar(select(func.coalesce(func.sum(JevRequest.reserved_usd), 0)))
            code = ("provider_contract_halted" if control.halt_reason else
                    "monthly_cap" if actual + outstanding + MAX_CALL_USD > MONTHLY_CAP_USD else None)
            request_id = str(uuid.uuid4())
            session.add(JevRequest(
                id=request_id, started_ts=now, billing_month=month,
                correlation_id=correlation_id, state_hash=state_hash, questions=questions,
                requested_model=model, status="refused" if code else "pending",
                error_code=code, input_price_per_million=INPUT_PRICE_PER_MILLION,
                pricing_version=PRICING_VERSION, reserved_usd=Decimal(0) if code else MAX_CALL_USD,
                outcomes={},
            ))
            if code:
                _incident(session, code, request_id)
                _LOG.warning("Jev returned no decision: %s", code)
                return None
        return request_id  # reservation committed before any HTTP attempt

    def _settle(self, request_id: str, *, body: dict | None, questions: dict,
                latency_ms: int, error_code: str | None,
                error_class: str | None = None, provider: dict | None = None) -> JevDecision | None:
        result = None
        with self._sessions() as session, session.begin():
            control = _lock(session)
            row = session.get(JevRequest, request_id)
            if row is None or row.status != "pending":
                raise ValueError("Missing pending reservation")
            row.completed_ts = _now(session)
            row.completed_month = row.completed_ts.date().replace(day=1)
            row.latency_ms = latency_ms
            code = error_code or ("provider_contract_halted" if control.halt_reason else None)
            if body is not None:
                model = body.get("model")
                usage = body.get("usage")
                if isinstance(model, str) and len(model) <= 60:
                    row.model_id = model
                if model != MODEL_ID:
                    code = "unexpected_model"
                    control.halt_reason = code
                else:
                    if (not isinstance(usage, dict)
                            or type(usage.get("input_tokens")) is not int
                            or type(usage.get("output_tokens")) is not int
                            or not 0 <= usage["input_tokens"] < 2**63
                            or not 0 <= usage["output_tokens"] < 2**63):
                        code = "invalid_usage"
                    else:
                        row.input_tokens = usage["input_tokens"]
                        row.output_tokens = usage["output_tokens"]
                        cost = INPUT_PRICE_PER_MILLION * row.input_tokens / Decimal(1_000_000)
                        # Preserve the circuit breaker even for a nonsensical
                        # provider count larger than the NUMERIC audit column.
                        if cost < Decimal("100000000"):
                            row.actual_usd = cost
                            row.reserved_usd = Decimal(0)
                        if row.input_tokens > MAX_INPUT_TOKENS:
                            code = "token_bound_exceeded"
                            control.halt_reason = code
                try:
                    # Preserve JSON-safe malformed answers for diagnosis, while
                    # only status='ok' rows are eligible for calibration labels.
                    if isinstance(body.get("answers"), dict):
                        row.answers = body["answers"]
                    _validate_answers(body.get("answers"), questions)
                except Exception:
                    code = code or "invalid_answers"
            row.error_code = code
            row.status = "ok" if code is None else ("uncertain" if row.actual_usd is None else "error")
            if code:
                _incident(session, code, request_id, error_class, provider)
                _LOG.warning("Jev returned no decision: %s", code)
            else:
                result = JevDecision(request_id=request_id, model_id=row.model_id,
                                     answers=row.answers, cost_usd=row.actual_usd,
                                     latency_ms=latency_ms)
        return result  # audit/spend committed before decision escapes

    def decide(self, *, state: Any, questions: dict, model: str = MODEL_ID,
               correlation_id: str | None = None) -> JevDecision | None:
        try:
            settings = get_settings()
            key = settings.typesafe_api_key
            if key is None or not key.get_secret_value().strip():
                self._failure("missing_key")
                return None
            secret = key.get_secret_value().strip()
            # Copy inputs before hashing/sending: a caller cannot mutate the audit.
            state_json = _json(state)
            if not isinstance(state, (str, dict, list)):
                raise ValueError("Invalid state")
            normalized = _validate_questions(questions)
            if model not in _MODELS:
                raise ValueError("Unreviewed model")
            if correlation_id is not None and (not isinstance(correlation_id, str)
                                               or not 1 <= len(correlation_id) <= 256):
                raise ValueError("Invalid correlation id")
            payload = {"state": state, "questions": normalized, "correlation_id": correlation_id}
            envelope = _json(payload)
            if _contains_secret(payload, secret) or len(envelope.encode()) > 262_144:
                raise ValueError("Unsafe or oversized request")
            state_copy = json.loads(state_json)
        except Exception:
            self._failure("invalid_request")
            return None
        if not within_token_limits(state_copy, normalized):
            # The provider would refuse it (HTTP 400 max_tokens_exceeded) after
            # we committed a reservation. Callers must scope or split the state.
            self._failure("oversized_request")
            return None
        try:
            request_id = self._admit(state_hash=hashlib.sha256(state_json.encode()).hexdigest(),
                                     questions=normalized, model=model, correlation_id=correlation_id)
        except Exception:
            self._failure("admission_storage_error")
            return None
        if request_id is None:
            return None
        started = time.monotonic()
        body = None
        code = None
        error_class = None
        provider = None
        client = None
        try:
            client = self._clients(secret)
            response = client.system_one(state=state_copy, questions=normalized, model=MODEL_ID,
                                         retry=RetryPolicy(max_retries=0), timeout=TIMEOUT_SECONDS)
            raw = response.model_dump(mode="json")
            encoded = _json(raw)
            if _contains_secret(raw, secret) or len(encoded.encode()) > 1_048_576 or not isinstance(raw, dict):
                raise ValueError("Unsafe response")
            body = json.loads(encoded)
        except Exception as exc:
            # Timeouts/SDK validation errors may follow a charged request. Keep
            # the full reservation; do not log exception text or raw HTTP data.
            code = "provider_error"
            error_class = type(exc).__qualname__[:80]
            provider = _provider_detail(exc, secret)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    code = code or "provider_close_error"
        latency = max(0, round((time.monotonic() - started) * 1000))
        try:
            return self._settle(request_id, body=body, questions=normalized,
                                latency_ms=latency, error_code=code, error_class=error_class,
                                provider=provider)
        except Exception:
            # A rollback preserves the committed maximum reservation.
            self._failure("settlement_storage_error")
            return None

    def record_outcome(self, request_id: str, question_id: str, outcome: Any,
                       *, observed_at: datetime) -> bool:
        """Attach one immutable realized label for later Brier/reliability work.

        Noul labels are bools, Choice labels are criterion names, and Score
        labels are integer level indices. Repeating the identical label/time
        is idempotent. This method cannot alter predictions or spend.
        """
        try:
            if observed_at.tzinfo is None:
                raise ValueError("Naive outcome time")
            with self._sessions() as session, session.begin():
                row = session.scalar(select(JevRequest).where(JevRequest.id == request_id).with_for_update())
                if row is None or row.status != "ok" or question_id not in row.questions:
                    return False
                if not row.completed_ts <= observed_at <= _now(session):
                    return False
                question = row.questions[question_id]
                kind = question["type"]
                if not ((kind == "noul" and type(outcome) is bool)
                        or (kind == "choice" and isinstance(outcome, str) and outcome in question["criteria"])
                        or (kind == "score" and type(outcome) is int and 0 <= outcome < len(question["criteria"]))):
                    return False
                label = {"value": outcome, "observed_at": observed_at.astimezone(UTC).isoformat()}
                if question_id in row.outcomes:
                    return row.outcomes[question_id] == label
                row.outcomes = {**row.outcomes, question_id: label}
            return True
        except Exception:
            self._failure("outcome_storage_error")
            return False
