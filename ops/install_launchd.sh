#!/bin/bash
# (Re)install the tradingbot LaunchAgents from ops/launchd/.
set -euo pipefail
cd "$(dirname "$0")/launchd"
mkdir -p "$HOME/Documents/tradingbot/logs"
for p in com.tradingbot.*.plist; do
  label="${p%.plist}"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  cp "$p" "$HOME/Library/LaunchAgents/$p"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$p"
  echo "loaded $label"
done
