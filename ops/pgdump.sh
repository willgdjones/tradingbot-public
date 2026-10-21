#!/bin/bash
# Nightly backup of the tradingbot DB's IRREPLACEABLE data. Keeps the newest 4 dumps.
# Excluded (owner, 2026-10-07): row data of `trades`, the historical public
# Kalshi/Polymarket trade tape (~2.8 GB) that can be re-downloaded with the
# capture tools. Its schema is still dumped. Everything else is kept: ledger,
# trials, holdout spends, Jev logs, and live-recorded snapshots/quotes/events.
# At ~2.2 GB each, 14 dumps (~31 GB) pushed free disk under the IEX recorder's
# 30 GB floor and stopped it (2026-10-07); raise this only with more free disk.
source "$(dirname "$0")/env.sh"
set -euo pipefail
mkdir -p "$REPO/backups"
out="$REPO/backups/tradingbot-$(date +%Y%m%d-%H%M%S).dump"
pg_dump -Fc tradingbot -f "$out" \
  --exclude-table-data=public.trades \
  --exclude-table-data='_timescaledb_internal._hyper_10_*'
echo "$(ts) wrote $out" >> "$LOGS/pgdump.log"
ls -1t "$REPO"/backups/tradingbot-*.dump | tail -n +5 | xargs -r rm -f
