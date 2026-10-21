#!/bin/bash
# IBS QQQ v1 on real money (tradingbot-752). Dry run until ALPACA_LIVE_KEY/SECRET
# resolve in 1Password; while dry, the runner exits outside the order window so
# this restart re-reads the secrets and it goes live by itself.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
exec "$REPO/ops/with-secrets" uv run python -m tradingbot.live.ibs_qqq run
