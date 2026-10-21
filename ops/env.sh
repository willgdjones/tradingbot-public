# Shared environment for launchd-run ops scripts (launchd gives a bare PATH).
REPO="$HOME/Documents/tradingbot"
export PATH="/usr/local/opt/postgresql@18/bin:$HOME/.local/bin:$HOME/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin"
# Homebrew PG18+TimescaleDB runs on 5433; Postgres.app (unrelated) owns 5432.
export PGPORT=5433 PGHOST=localhost
LOGS="$REPO/logs"
mkdir -p "$LOGS"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
