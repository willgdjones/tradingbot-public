#!/bin/bash
# Runs every 60s via launchd. Checks host health; logs only problems.
# When the bot runner exists (paper engine), add its liveness check + restart here.
source "$(dirname "$0")/env.sh"
LOG="$LOGS/watchdog.log"

if ! pg_isready -q; then
  echo "$(ts) postgres down, restarting" >> "$LOG"
  brew services restart postgresql@18 >> "$LOG" 2>&1
fi

if ! tmux has-session -t tradingbot 2>/dev/null; then
  # Not auto-respawned: relaunching agents is an owner/daily-session decision.
  echo "$(ts) ntm session 'tradingbot' not running" >> "$LOG"
fi

# Recover exited agent CLIs even if the scheduler/nudger is not running.
# The shared helper locks/throttles attempts and targets unique worker pane IDs.
if tmux has-session -t tradingbot 2>/dev/null; then
  python3 "$(dirname "$0")/agent_recovery.py" >> "$LOG" 2>&1
fi

# Resume services frozen by a stray SIGSTOP; a frozen service is a broken feed.
if tmux has-session -t tradingbot 2>/dev/null; then
  roots=$(tmux list-panes -t tradingbot:services -F '#{pane_pid}' 2>/dev/null)
  if [ -n "$roots" ]; then
    resumed=$(bash "$(dirname "$0")/resume_stopped.sh" $roots)
    if [ -n "$resumed" ]; then
      n=$(printf '%s\n' "$resumed" | wc -l | tr -d ' ')
      printf '%s resumed %s stopped service process(es):\n%s\n' "$(ts)" "$n" "$resumed" >> "$LOG"
      echo "- $(ts) watchdog: $n service process(es) found stopped (state T) and resumed; see logs/watchdog.log" >> "$LOGS/INCIDENTS.md"
    fi
  fi
fi

# Recreate the tmux services window (TOM paper runner + scheduler) if missing.
bash "$(dirname "$0")/services.sh"
