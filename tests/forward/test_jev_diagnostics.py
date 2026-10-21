"""Failure provenance without secrets, retried turns, or altered controls."""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from forward.test_jev_intraday import FixtureStrategy, setup, turn  # noqa: F401
from tradingbot.db.models import Incident
from tradingbot.forward.jev_intraday import ROOT, failure_details


PRIVATE_MESSAGE = "test-only-secret: credential, HTTP body and financial account details"


def raising_frame(*args, **kwargs):
    raise ValueError(PRIVATE_MESSAGE)


def expected_failure(stage, **extra):
    return {"stage": stage, "exception_type": "ValueError",
            "file": str(Path(__file__).relative_to(ROOT)),
            "line": raising_frame.__code__.co_firstlineno + 1, **extra}


@pytest.mark.parametrize("stage, method", [
    ("view", "view"), ("plan", "plan"), ("costs", "_costs"),
    ("decide", "_model_choices"), ("execute", "execute"),
])
def test_failed_turn_retains_stage_and_innermost_frame_without_retry(setup, monkeypatch, stage, method):
    session, runner, api, model, _, trial, _ = setup
    target = FixtureStrategy if stage == "plan" else runner
    monkeypatch.setattr(target, method, raising_frame)
    completed, recorded = turn(setup)
    assert not completed and recorded.payload["status"] == "error"
    assert recorded.payload["error"] == "ValueError"
    assert recorded.payload["failure"] == expected_failure(stage, variant="real")
    incident = session.scalar(select(Incident).where(
        Incident.strategy_id == trial.strategy_id, Incident.message == "Jev intraday: turn_failed"))
    assert incident.details == {"trial_id": trial.id, "failure": recorded.payload["failure"]}
    assert PRIVATE_MESSAGE not in json.dumps([recorded.payload, incident.details])
    assert not api.submissions
    assert len(model.calls) == int(stage == "execute")

    # The durable claim still forbids replay, even after the transient fault ends.
    monkeypatch.undo()
    before = json.dumps(recorded.payload, sort_keys=True)
    assert not turn(setup)[0]
    assert json.dumps(recorded.payload, sort_keys=True) == before
    assert not api.submissions and len(model.calls) == int(stage == "execute")


@pytest.mark.parametrize("stage", ["view", "execute"])
def test_virtual_failure_provenance_stays_with_controls(setup, monkeypatch, stage):
    session, runner, api, model, _, trial, _ = setup
    if stage == "view":
        original = runner.view

        def virtual_view(participant, *args):
            if runner.state(participant)["virtual"]:
                return raising_frame()
            return original(participant, *args)

        monkeypatch.setattr(runner, "view", virtual_view)
    else:
        monkeypatch.setattr(runner, "_virtual_execute", raising_frame)
    completed, recorded = turn(setup)
    assert completed and recorded.payload["status"] == "complete"
    assert "failure" not in recorded.payload
    assert not runner.state(trial)["integrity_errors"]
    assert len(api.submissions) == len(model.calls) == 1
    failures = (recorded.payload["virtual_failures"] if stage == "view" else
                [e["result"]["failure"] for e in recorded.payload["executions"] if e["variant"] != "real"])
    assert failures == [expected_failure(stage, variant=k) for k in ("random", "ungated")]
    incidents = list(session.scalars(select(Incident).where(
        Incident.strategy_id != trial.strategy_id, Incident.message.like("Jev intraday: virtual_%"))))
    assert len(incidents) == 2
    assert [i.details["failure"] for i in sorted(incidents, key=lambda i: i.id)] == failures
    assert PRIVATE_MESSAGE not in json.dumps([recorded.payload, [i.details for i in incidents]])


def test_caught_execution_failure_keeps_reservation_and_redacts_text(setup, monkeypatch):
    _, runner, api, model, _, trial, _ = setup
    monkeypatch.setattr(runner.connector, "submit_limit", raising_frame)
    completed, recorded = turn(setup)
    assert completed  # Existing held-execution behavior is unchanged.
    actual = next(e for e in recorded.payload["executions"] if e["variant"] == "real")
    assert actual["result"] == {"held": "ValueError", "failure": expected_failure("execute")}
    assert runner.state(trial)["entries"]["2026-09-30"]["SPY"]
    assert not api.submissions and len(model.calls) == 1
    assert PRIVATE_MESSAGE not in json.dumps(recorded.payload)


def test_missing_traceback_has_explicit_unknown_source():
    assert failure_details(ValueError(PRIVATE_MESSAGE), "view") == {
        "stage": "view", "exception_type": "ValueError", "file": None, "line": None,
    }


def test_external_frame_omits_parent_directory_and_exception_text():
    namespace = {"PRIVATE_MESSAGE": PRIVATE_MESSAGE}
    try:
        exec(compile("raise ValueError(PRIVATE_MESSAGE)", "/private/account-directory/vendor.py", "exec"), namespace)
    except ValueError as error:
        assert failure_details(error, "view") == {
            "stage": "view", "exception_type": "ValueError", "file": "vendor.py", "line": 1,
        }
