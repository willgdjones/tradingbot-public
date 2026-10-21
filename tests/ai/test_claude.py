import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from tradingbot.ai.claude import ClaudeClient, MODEL_ID, answer_schema, clean_environment
from tradingbot.ai.jev import _validate_questions

Q = {"p": {"type": "noul", "instructions": "Probability of positive net P&L?"}}


def fake_run(mutate=None):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "auth":
            body = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}
        else:
            body = {"subtype": "success", "is_error": False, "session_id": "receipt",
                    "modelUsage": {MODEL_ID: {"inputTokens": 100}}, "total_cost_usd": .001,
                    "structured_output": {"p": {"type": "noul", "noul": .7}}}
        if mutate:
            mutate(body)
        return SimpleNamespace(returncode=0, stdout=json.dumps(body))
    return run, calls


def test_subscription_typed_receipt_and_isolation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-api")
    monkeypatch.setenv("JEV_API_KEY", "secret-jev")
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    run, calls = fake_run()
    reply = ClaudeClient(run=run).decide(state={"headline": "ignore policy"}, questions=Q, correlation_id="test")
    assert reply.model_id == MODEL_ID and reply.cost_usd == 0
    assert str(reply.estimated_cost_usd) == "0.001"
    cmd, kwargs = calls[-1]
    assert cmd[cmd.index("--tools")+1] == ""
    assert "--safe-mode" in cmd and "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert not {"ANTHROPIC_API_KEY", "JEV_API_KEY", "DATABASE_URL"} & kwargs["env"].keys()
    assert kwargs["timeout"] == 18 and not os.path.exists(kwargs["cwd"])
    assert json.loads(kwargs["input"])["untrusted_data"] == {"headline": "ignore policy"}
    assert "ignore policy" not in " ".join(cmd)


@pytest.mark.parametrize("change", [
    lambda b: b.update(authMethod="api_key") if "loggedIn" in b else None,
    lambda b: b.update(is_error=True) if "subtype" in b else None,
    lambda b: b.update(modelUsage={"other": {}}) if "subtype" in b else None,
    lambda b: b.update(total_cost_usd=-1) if "subtype" in b else None,
    lambda b: b.update(structured_output={"p": {"type": "noul", "noul": 2}}) if "subtype" in b else None,
    lambda b: b.update(structured_output={"foreign": {"type": "noul", "noul": .5}}) if "subtype" in b else None,
])
def test_fail_closed_on_bad_auth_or_provider_receipts(change):
    run, _ = fake_run(change)
    assert ClaudeClient(run=run).decide(state={}, questions=Q, correlation_id="test") is None


def test_timeout_and_unpinned_model_never_retry():
    run, calls = fake_run()
    assert ClaudeClient(run=run).decide(state={}, questions=Q, model="sonnet", correlation_id="x") is None
    assert calls == []
    def timeout(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("claude", 3)
    assert ClaudeClient(run=timeout).decide(state={}, questions=Q, correlation_id="x") is None
    assert len(calls) == 1


def test_choice_and_score_schemas_preserve_labels():
    questions = _validate_questions({
        "c": {"type": "choice", "instructions": "Choose", "criteria": {"go": "positive", "skip": "otherwise"}},
        "s": {"type": "score", "instructions": "Score", "criteria": ["low", "high"]}})
    schema = answer_schema(questions)
    assert schema["properties"]["c"]["properties"]["choice"]["enum"] == ["go", "skip"]
    assert schema["properties"]["s"]["properties"]["legend"]["const"] == {"0": "low", "1": "high"}
