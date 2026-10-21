"""Ntm's idle flag is insufficient evidence that a pane can receive a prompt."""
import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def nudge(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "ops"))
    module = importlib.import_module("nudge")
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "LOG", tmp_path / "logs/nudge.log")
    return module


def setup_commands(monkeypatch, nudge, snapshots, *, has_work=True):
    commands = []
    snapshots = iter(snapshots)

    def run(command, **kwargs):
        commands.append(command)
        if command[:2] in (["tmux", "respawn-pane"], ["tmux", "send-keys"]):
            output = ""
        elif command[0] == "tmux":
            output = next(snapshots)
        elif command[:2] == ("ntm", "--robot-activity=tradingbot"):
            output = json.dumps({"success": True, "agents": [
                {"pane_idx": i, "agent_type": "codex", "state": "WAITING", "safe_to_dispatch": True}
                for i in (1, 2, 3)
            ]})
        elif command[0] == "br":
            if isinstance(has_work, dict):
                output = has_work["ready" if command[1] == "ready" else "in_progress"]
            else:
                output = '[{"id":"tradingbot-test"}]' if has_work else "[]"
        else:
            assert command[0] == "ntm"
            output = ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(nudge.subprocess, "run", run)
    return commands


def test_idle_shells_recover_but_only_healthy_worker_gets_prompt(monkeypatch, nudge):
    panes = "0\t%18\tzsh\n1\t%19\tzsh\n2\t%20\tnode\n3\t%21\tzsh\n"
    commands = setup_commands(monkeypatch, nudge, [panes] * 3)
    nudge.main()
    respawned = [c[c.index("-t") + 1] for c in commands if c[:2] == ["tmux", "respawn-pane"]]
    assert respawned == ["%19", "%21"]
    ntm = [c for c in commands if c[0] == "ntm"]
    sends = [c for c in ntm if c[1] == "send"]
    assert len(sends) == 1 and sends[0][3] == "--pane=0.2"


def test_recovers_even_when_no_beads_are_ready(monkeypatch, nudge):
    panes = "1\t%19\tzsh\n"
    commands = setup_commands(monkeypatch, nudge, [panes] * 2, has_work=False)
    nudge.main()
    assert any(c[:2] == ["tmux", "respawn-pane"] for c in commands)
    assert not any(c[1] == "send" for c in commands)


@pytest.mark.parametrize("ready, in_progress, sent", [
    ('[{"id":"a","labels":["blocked:owner-input"]}]', '{"issues":[]}', False),
    ('[{"id":"a","assignee":"coordinator"}]', '{"issues":[]}', False),
    ('[{"id":"a","labels":["blocked:owner-input"]},{"id":"b","labels":["research"]}]', '{"issues":[]}', True),
    ('[{"id":"a","labels":["blocked:owner-input"]}]', '{"issues":[{"id":"c"}]}', True),
])
def test_only_claimable_or_claimed_work_triggers_a_nudge(monkeypatch, nudge, ready, in_progress, sent):
    panes = "0\t%18\tzsh\n1\t%19\tnode\n"
    commands = setup_commands(monkeypatch, nudge, [panes] * 3,
                              has_work={"ready": ready, "in_progress": in_progress})
    nudge.main()
    assert any(c[1] == "send" for c in commands if c[0] == "ntm") is sent


def test_cli_exiting_during_queries_does_not_receive_shell_prompt(monkeypatch, nudge):
    commands = setup_commands(monkeypatch, nudge, ["1\t%19\tnode\n", "1\t%19\tzsh\n"])
    nudge.main()
    assert not any(c[1] == "send" for c in commands)


def test_unreadable_tmux_state_prevents_dispatch(monkeypatch, nudge):
    commands = setup_commands(monkeypatch, nudge, ["broken"])
    nudge.main()
    assert all(c[0] == "tmux" for c in commands)
