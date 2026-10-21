#!/bin/bash
# Ensure every long-running service is running in the tmux session.
#
# Why tmux and not launchd: macOS TCC blocks launchd-spawned uv/Python from
# reading ~/Documents, even with Full Disk Access on /bin/bash. Processes
# spawned by the tmux server inherit the terminal's access. The launchd
# watchdog calls this script every minute to recreate anything missing.
#
# A service counts as running if any pane in the session was started with its
# script. New services get their OWN window ("svc-<name>"), so the session
# never runs out of room to split (the old single "services" window filled up
# and silently failed to restart the Jev runner on 2026-10-05).
#
# To add a service: add one `ensure` line below.
source "$(dirname "$0")/env.sh"
# Services live in their own session so they don't depend on the ntm agent
# session (which died with the tmux server on 2026-10-08 and was not rebuilt).
SESSION=tradingbot-svc

# Only create the session when a tmux server already exists (started from a
# terminal). A server started by launchd would inherit launchd's TCC context
# and Python could not read ~/Documents.
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux ls >/dev/null 2>&1 || { echo "$(ts) no tmux server; cannot start services from launchd" >> "$LOGS/services.log"; exit 0; }
  tmux new-session -d -s "$SESSION" -n svc-placeholder -c "$REPO" "sleep 86400" || exit 0
  echo "- $(ts) services session '$SESSION' was missing and was recreated" >> "$LOGS/INCIDENTS.md"
fi

running() {  # true if any pane in the session was started with this script
  tmux list-panes -s -t "$SESSION" -F '#{pane_start_command}' | grep -qF "$1"
}

ensure() {  # ensure <name> <script> [logfile]
  local name="$1" script="$2" log="${3:-}"
  running "$script" && return 0
  local cmd="while true; do bash $script"
  [ -n "$log" ] && cmd="$cmd >> $log 2>&1"
  cmd="$cmd; echo \"\$(date) $name exited \$?\" >> logs/services.log; sleep 60; done"
  tmux kill-window -t "$SESSION:svc-$name" 2>/dev/null  # stale window with a dead loop
  if tmux new-window -d -t "$SESSION" -n "svc-$name" -c "$REPO" "$cmd"; then
    echo "$(ts) started service $name" >> "$LOGS/services.log"
  else
    echo "$(ts) FAILED to start service $name" >> "$LOGS/services.log"
    echo "- $(ts) services.sh could not start $name" >> "$LOGS/INCIDENTS.md"
  fi
}

ensure tom-paper     ops/alpaca_tom_paper.sh
ensure scheduler     ops/scheduler.sh
ensure iex-intraday  ops/iex_intraday.sh   logs/iex-intraday.log
ensure event-feeds   ops/event_feeds.sh    logs/event-feeds.log
ensure jev-intraday  ops/jev_intraday.sh   logs/jev-intraday.log
ensure ai1-gate      ops/ai1_gate.sh       logs/ai1-gate.log
ensure ai2-basket    ops/ai2_basket.sh     logs/ai2-basket.log
ensure c05-paper     ops/c05_paper.sh      logs/c05-paper.log
ensure ibs-live      ops/ibs_live.sh       logs/ibs-live.log
