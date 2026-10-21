#!/usr/bin/env python3
"""Keep the ntm swarm busy. Runs every 10 minutes via the scheduler.

For each agent pane that ntm reports as idle and safe to dispatch, send one
standing prompt telling it to finish its claimed bead or take the next one
from `br ready`. It only nudges when there is open work. This replaces
`ntm assign --watch`, which kept failing to dispatch to idle panes.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from agent_recovery import recover_exited_agents, worker_snapshot

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "logs" / "nudge.log"
SESSION = "tradingbot"
PROMPT = (
    "NUDGE (coordinator, automatic): you are idle. Re-read AGENTS.md 'Current priorities' if you haven't "
    "recently. If you have a claimed in-progress bead, continue it to completion. Otherwise claim the "
    "highest-priority bead from `br ready` that nobody else holds (skip ones labelled blocked:* or "
    "assigned to coordinator), and work it end to end: reserve paths via Agent Mail, commit small, "
    "push, log in CHANGELOG, then close the bead with a note. Don't wait to be asked."
)


def run(*cmd: str) -> str:
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=120).stdout


def log(msg: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def _issues(raw: str) -> list[dict]:
    """``br`` prints a bare list (ready) or ``{"issues": [...]}`` (list)."""
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    data = data.get("issues", []) if isinstance(data, dict) else data
    return [i for i in data if isinstance(i, dict) and i.get("id")]


def _claimable(issue: dict) -> bool:
    """The same skips the prompt tells agents to apply; otherwise an owner-blocked
    queue gets every pane nudged every cycle with nothing to take."""
    labels = issue.get("labels") or []
    return (not any(str(label).startswith("blocked:") for label in labels)
            and issue.get("assignee") != "coordinator")


def main() -> None:
    workers = recover_exited_agents(REPO)
    if workers is None:
        return
    try:
        activity = json.loads(run("ntm", f"--robot-activity={SESSION}"))
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        log("could not read ntm activity")
        return
    if not activity.get("success"):
        log("ntm activity unsuccessful (session down?)")
        return

    ready = _issues(run("br", "ready", "--json"))
    in_progress = _issues(run("br", "list", "--status", "in_progress", "--json"))
    if not in_progress and not any(_claimable(issue) for issue in ready):
        return

    for agent in activity.get("agents", []):
        if agent.get("agent_type") not in ("claude", "codex"):
            continue
        idle = agent.get("state") == "WAITING" or agent.get("observation_state") == "idle"
        if not idle or not agent.get("safe_to_dispatch"):
            continue
        pane = str(agent["pane_idx"])
        worker = workers.get(int(pane))
        if worker is None or worker.exited:
            continue
        # Check again immediately before sending; the CLI may have exited while
        # ntm/beads were queried. Do not type the standing prompt into a shell.
        current = worker_snapshot(REPO)
        if current is None or current.get(int(pane)) != worker:
            continue
        out = subprocess.run(
            ["ntm", "send", SESSION, f"--pane=0.{pane}", PROMPT],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        log(f"nudged pane {pane} ({agent['agent_type']}): rc={out.returncode}")


if __name__ == "__main__":
    os.environ.setdefault("NO_COLOR", "1")
    main()
