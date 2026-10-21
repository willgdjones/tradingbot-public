#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
exec "$REPO/ops/with-secrets" uv run python -m tradingbot.forward.jev_intraday
