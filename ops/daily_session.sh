#!/bin/bash
# Daily autonomous Claude session (PRD §8). Runs headless in the repo.
source "$(dirname "$0")/env.sh"
cd "$REPO"
LOG="$LOGS/daily-$(date +%Y-%m-%d).log"
echo "$(ts) daily session start" >> "$LOG"
CLAUDE_CONFIG_DIR="$HOME/.claude-account-2" "$REPO/ops/with-secrets" claude -p --dangerously-skip-permissions "$(cat ops/daily_prompt.md)" >> "$LOG" 2>&1
echo "$(ts) daily session end (exit $?)" >> "$LOG"
# Surface incidents only (PRD §8: report to owner only on incidents).
if [ -s "$LOGS/INCIDENTS.md" ] && [ "$LOGS/INCIDENTS.md" -nt "$LOGS/.incidents_seen" ]; then
  osascript -e 'display notification "New incident logged — see logs/INCIDENTS.md" with title "Trading bot"'
  touch "$LOGS/.incidents_seen"
fi
