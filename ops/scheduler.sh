#!/bin/bash
# Runs once a minute inside the tmux services window (see services.sh).
#  - every 10 minutes: nudge idle agents (ops/nudge.py)
#  - weekly page, once per ISO week: from Friday 14:00 local (17:00 ET), or on
#    Saturday/Sunday if Friday was missed (laptop asleep, services down)
source "$(dirname "$0")/env.sh"
cd "$REPO"
STATE="$LOGS/.scheduler"
mkdir -p "$STATE"

min=$(date +%M)
if (( 10#$min % 10 == 0 )); then
  python3 ops/nudge.py
fi

week=$(date +%G-W%V)
dow=$(date +%u)
if { [ "$dow" = "5" ] && [ "$(date +%H)" -ge 14 ]; } || [ "$dow" -ge 6 ]; then
  # A failed deploy retries once per hour, not every minute: each attempt is a
  # full build + Cloudflare deploy, and each failure writes an incident line.
  attempt="$STATE/weekly-$week-failed-$(date +%Y%m%d%H)"
  if [ ! -e "$STATE/weekly-$week" ] && [ ! -e "$attempt" ]; then
    if "$REPO/ops/with-secrets" uv run python ops/weekly_report.py --deploy >> "$LOGS/weekly.log" 2>&1; then
      touch "$STATE/weekly-$week"
      echo "$(ts) weekly page deployed for $week" >> "$LOGS/weekly.log"
    else
      touch "$attempt"
      echo "$(ts) weekly deploy FAILED for $week (retrying hourly)" >> "$LOGS/INCIDENTS.md"
    fi
  fi
fi
