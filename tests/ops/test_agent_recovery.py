"""Exited CLI recovery must never restart a healthy worker or a service pane."""
import fcntl
import importlib
import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEALTHY = "0\t%18\tzsh\n1\t%19\t2.1.289\n2\t%20\tnode\n3\t%21\tnode\n"
DEAD = "0\t%18\tzsh\n1\t%19\tzsh\n2\t%20\tnode\n3\t%21\tzsh\n"


@pytest.fixture
def recovery(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "ops"))
    return importlib.import_module("agent_recovery")


def stub_commands(monkeypatch, recovery, snapshots, *, result=0):
    commands = []
    snapshots = iter(snapshots)

    def run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["tmux", "list-panes"]:
            value = next(snapshots)
            if isinstance(value, Exception):
                raise value
            return subprocess.CompletedProcess(command, 0, value, "")
        if command[:2] == ["tmux", "send-keys"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command[:3] == ["tmux", "respawn-pane", "-k"]
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(command, result, "", "")

    monkeypatch.setattr(recovery.subprocess, "run", run)
    return commands


def respawns(commands):
    return [c for c in commands if c[:2] == ["tmux", "respawn-pane"]]


def targets(commands):
    return [c[c.index("-t") + 1] for c in respawns(commands)]


def test_only_shell_workers_respawn_by_unique_id_and_hourly(monkeypatch, tmp_path, recovery):
    clock = [10000.0]
    monkeypatch.setattr(recovery.time, "time", lambda: clock[0])
    commands = stub_commands(monkeypatch, recovery, [DEAD] * 6)
    workers = recovery.recover_exited_agents(tmp_path)
    assert set(workers) == {1, 2, 3}  # the user's shell is excluded
    assert workers[1].exited  # a freshly restarted worker is not ready for a nudge yet
    assert targets(commands) == ["%19", "%21"]
    # Never the gmail account (default config dir): each pane has a pinned one.
    typed = [c[-2] for c in commands if c[:2] == ["tmux", "send-keys"]]
    assert ".claude-account-1" in typed[0] and ".claude-account-2" in typed[1]
    incident = (tmp_path / "logs/INCIDENTS.md").read_text()
    assert "0.1/%19 (zsh)" in incident and "0.3/%21 (zsh)" in incident
    assert "%18" not in incident and "%20" not in incident

    clock[0] += 3599
    recovery.recover_exited_agents(tmp_path)
    assert len(respawns(commands)) == 2
    assert (tmp_path / "logs/INCIDENTS.md").read_text() == incident
    clock[0] += 1
    recovery.recover_exited_agents(tmp_path)
    assert len(respawns(commands)) == 4
    clock[0] -= 7200  # a backwards wall-clock jump cannot bypass the throttle
    recovery.recover_exited_agents(tmp_path)
    assert len(respawns(commands)) == 4


@pytest.mark.parametrize("result", [1, FileNotFoundError(), subprocess.TimeoutExpired("ntm", 45)])
def test_failed_attempts_are_also_throttled(monkeypatch, tmp_path, recovery, result):
    commands = stub_commands(monkeypatch, recovery, [DEAD] * 3, result=result)
    recovery.recover_exited_agents(tmp_path)
    recovery.recover_exited_agents(tmp_path)
    assert len(respawns(commands)) == 2  # one round (both dead panes), then throttled
    assert "failed" in (tmp_path / "logs/INCIDENTS.md").read_text()


def test_healthy_workers_ignore_user_shell(monkeypatch, tmp_path, recovery):
    commands = stub_commands(monkeypatch, recovery, [HEALTHY])
    assert len(recovery.recover_exited_agents(tmp_path)) == 3
    assert not respawns(commands)
    assert not (tmp_path / "logs/INCIDENTS.md").exists()


@pytest.mark.parametrize("latest", [HEALTHY, DEAD.replace("%19", "%99").replace("%21", "%98")])
def test_recheck_does_not_restart_recovered_or_replaced_workers(monkeypatch, tmp_path, recovery, latest):
    commands = stub_commands(monkeypatch, recovery, [DEAD, latest])
    recovery.recover_exited_agents(tmp_path)
    assert not respawns(commands)


@pytest.mark.parametrize("snapshot", [
    subprocess.CalledProcessError(1, "tmux"),
    subprocess.TimeoutExpired("tmux", 10),
    "not a pane snapshot",
])
def test_unavailable_snapshot_does_not_respawn(monkeypatch, tmp_path, recovery, snapshot):
    commands = stub_commands(monkeypatch, recovery, [snapshot])
    assert recovery.recover_exited_agents(tmp_path) is None
    assert not respawns(commands)
    assert "cannot inspect" in (tmp_path / "logs/watchdog.log").read_text()


def test_concurrent_watchdog_and_nudger_share_lock(monkeypatch, tmp_path, recovery):
    logs = tmp_path / "logs"
    logs.mkdir()
    commands = stub_commands(monkeypatch, recovery, [DEAD])
    with (logs / ".agent-recovery.lock").open("a") as other_caller:
        fcntl.flock(other_caller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recovery.recover_exited_agents(tmp_path)
    assert not respawns(commands)


def test_corrupt_state_delays_retry_instead_of_looping(monkeypatch, tmp_path, recovery):
    logs = tmp_path / "logs"
    logs.mkdir()
    state = logs / ".agent-recovery.json"
    state.write_text("broken")
    commands = stub_commands(monkeypatch, recovery, [DEAD, DEAD])
    recovery.recover_exited_agents(tmp_path)
    recovery.recover_exited_agents(tmp_path)
    assert not respawns(commands)
    assert json.loads(state.read_text())["last_attempt"] > 0
    assert (logs / "INCIDENTS.md").read_text().count("invalid recovery state") == 1


def test_state_must_be_durable_before_respawning(monkeypatch, tmp_path, recovery):
    commands = stub_commands(monkeypatch, recovery, [DEAD, DEAD])

    def fail_save(*args):
        raise OSError("disk full")

    monkeypatch.setattr(recovery, "save_attempt", fail_save)
    recovery.recover_exited_agents(tmp_path)
    assert not respawns(commands)
    assert "state unavailable" in (tmp_path / "logs/INCIDENTS.md").read_text()


def test_watchdog_runs_recovery_with_scheduler_down(tmp_path):
    """Run the real shell entrypoint and helper against fake local CLI executables."""
    ops, logs, binaries = (tmp_path / name for name in ("ops", "logs", "bin"))
    for path in (ops, logs, binaries):
        path.mkdir()
    for name in ("watchdog.sh", "agent_recovery.py"):
        shutil.copy(ROOT / "ops" / name, ops / name)
    quote = shlex.quote
    (ops / "env.sh").write_text(
        f'REPO={quote(str(tmp_path))}\nLOGS={quote(str(logs))}\n'
        f'export PATH={quote(str(binaries))}:"$PATH"\nts() {{ date; }}\n'
    )
    (ops / "services.sh").write_text("exit 0\n")
    for name, body in {
        "pg_isready": "exit 0",
        "tmux": (
            'case "$*" in\n'
            '  send-keys*) ;;\n'
            '  respawn-pane*) printf \'%s\\n\' "$4" >> ' + quote(str(logs / 'respawns')) + ' ;;\n'
            '  *tradingbot:0*) cat <<\'PANES\'\n' + DEAD + "PANES\n;;\n"
            "esac\nexit 0"
        ),
    }.items():
        executable = binaries / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    for _ in range(2):
        subprocess.run(["bash", str(ops / "watchdog.sh")], check=True, timeout=10)
    assert (logs / "respawns").read_text().splitlines() == ["%19", "%21"]
    assert "exited worker panes" in (logs / "INCIDENTS.md").read_text()
