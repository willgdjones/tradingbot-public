#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$REPO"
exec uv run python ops/weekly_report.py --deploy
