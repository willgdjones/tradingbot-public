#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
# This is a paper trial identifier, never a credential or broker account ID.
read -r TOM_PAPER_TRIAL < "$REPO/data/forward/turn_of_month.trial"
[[ "$TOM_PAPER_TRIAL" =~ ^[1-9][0-9]*$ ]] || exit 2
exec "$REPO/ops/with-secrets" uv run python -m tradingbot.forward.turn_of_month run --trial-id "$TOM_PAPER_TRIAL"
