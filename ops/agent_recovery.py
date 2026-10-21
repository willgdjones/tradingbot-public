#!/usr/bin/env python3
"""Recover exited ntm workers, shared by the watchdog and the nudger.

Inspect window 0 directly: ntm can report an exited agent's shell as idle.
Use unique pane IDs when respawning; numeric indices also match services in
other windows. A locked, durable timestamp limits all recovery attempts
(including failed ones) to one per hour across both callers.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SESSION = "tradingbot"
WORKERS = {1, 2, 3}
SHELLS = {"zsh", "bash", "sh", "dash", "fish", "ksh", "csh", "tcsh"}
COOLDOWN = 3600
# Owner, 2026-10-15: never run agents on the the owner's personal account Claude
# subscription. Each worker pane gets a fixed account (Claude config dir).
ACCOUNTS = {
    1: "~/.claude-account-1",     # account 1
    2: "~/.claude-account-2",   # account 2
    3: "~/.claude-account-2",
}
MODEL = "claude-opus-5-5"


def agent_command(index: int) -> str:
    """Typed into a fresh interactive shell, like ntm does. Launching via
    `zsh -c '...'` instead makes tmux report the pane as `zsh` while Claude
    runs, so recovery killed healthy agents hourly (2026-10-15 to 10-17)."""
    config = os.path.expanduser(ACCOUNTS[index])
    return f"export CLAUDE_CONFIG_DIR={config}; claude --dangerously-skip-permissions --model {MODEL}"


@dataclass(frozen=True)
class Worker:
    pane_id: str
    command: str

    @property
    def exited(self) -> bool:
        return Path(self.command).name.lstrip("-") in SHELLS


def log(repo: Path, message: str, *, incident: bool = False) -> None:
    logs = repo / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{stamp} agent-recovery: {message}\n"
    with (logs / "watchdog.log").open("a") as f:
        f.write(line)
    if incident:
        with (logs / "INCIDENTS.md").open("a") as f:
            f.write(f"- {line}")


def worker_snapshot(repo: Path = REPO) -> dict[int, Worker] | None:
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-t", f"{SESSION}:0", "-F",
             "#{pane_index}\t#{pane_id}\t#{pane_current_command}"],
            cwd=repo, capture_output=True, text=True, timeout=10, check=True,
        )
        workers = {}
        for line in out.stdout.splitlines():
            index, pane_id, command = line.split("\t", 2)
            index = int(index)
            if index in WORKERS:
                if not pane_id.startswith("%") or not pane_id[1:].isdigit() or not command:
                    raise ValueError("invalid worker pane")
                workers[index] = Worker(pane_id, command)
        return workers
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log(repo, f"cannot inspect worker panes ({type(exc).__name__}); skipping recovery/dispatch")
        return None


def recover_exited_agents(repo: Path = REPO) -> dict[int, Worker] | None:
    """Return the pre-recovery snapshot; never dispatch to a freshly booting CLI."""
    workers = worker_snapshot(repo)
    if not workers or not any(w.exited for w in workers.values()):
        return workers

    logs = repo / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        with (logs / ".agent-recovery.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return workers

            state_path = logs / ".agent-recovery.json"
            now = time.time()
            try:
                state = json.loads(state_path.read_text())
                last_attempt = float(state["last_attempt"])
                if not math.isfinite(last_attempt):
                    raise ValueError("nonfinite timestamp")
            except FileNotFoundError:
                last_attempt = None
            except (ValueError, TypeError, KeyError):
                # Unknown attempt history: restore the throttle before retrying.
                save_attempt(state_path, now)
                log(repo, "invalid recovery state; delaying respawn for one hour", incident=True)
                return workers
            if last_attempt is not None and now - last_attempt < COOLDOWN:
                return workers

            # A worker may have restarted since the first snapshot or lock acquisition.
            current = worker_snapshot(repo)
            dead = {
                i: w for i, w in (current or {}).items()
                if w.exited and workers.get(i) == w
            }
            if not dead:
                return workers
            pane_ids = ",".join(w.pane_id for _, w in sorted(dead.items()))
            panes = ", ".join(f"0.{i}/{w.pane_id} ({w.command})" for i, w in sorted(dead.items()))
            # Persist before the subprocess: crashes and timeouts must not create a loop.
            save_attempt(state_path, now)
            log(repo, f"exited worker panes {panes}; respawning on their pinned accounts", incident=True)
            # tmux respawn-pane, not `ntm respawn`: ntm relaunches with the
            # default config dir, which is the gmail account.
            for i, w in sorted(dead.items()):
                try:
                    result = subprocess.run(
                        # An explicit shell: with no command, tmux reruns the pane's old one.
                        ["tmux", "respawn-pane", "-k", "-t", w.pane_id, "-c", str(repo), "zsh -l"],
                        cwd=repo, capture_output=True, text=True, timeout=45,
                    )
                    if not result.returncode:
                        time.sleep(1)  # let the shell print its prompt first
                        result = subprocess.run(
                            ["tmux", "send-keys", "-t", w.pane_id, agent_command(i), "Enter"],
                            cwd=repo, capture_output=True, text=True, timeout=45,
                        )
                except (OSError, subprocess.SubprocessError) as exc:
                    log(repo, f"respawn of 0.{i} failed ({type(exc).__name__}); retry in one hour", incident=True)
                    continue
                if result.returncode:
                    log(repo, f"respawn of 0.{i} failed rc={result.returncode}; retry in one hour", incident=True)
                else:
                    log(repo, f"respawned 0.{i} on {ACCOUNTS[i]}; next inspection verifies liveness")
    except OSError as exc:
        log(repo, f"recovery state unavailable ({type(exc).__name__}); skipping respawn", incident=True)
    return workers


def save_attempt(path: Path, now: float) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as f:
        json.dump({"last_attempt": now}, f)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


if __name__ == "__main__":
    recover_exited_agents()
