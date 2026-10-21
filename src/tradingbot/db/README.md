# `tradingbot.db` — schema, migrations, sessions

Postgres 18 + TimescaleDB (Homebrew, **port 5433**, database `tradingbot`). The
connection URL lives in `.env` as `DATABASE_URL`; it is loaded via
`tradingbot.config` and never hard-coded or logged.

## Layout

| File | Purpose |
|---|---|
| `base.py` | `Base` (declarative), metadata naming convention, `TimestampMixin` |
| `enums.py` | Controlled vocabularies (stored as `VARCHAR` + `CHECK`, not native enums) |
| `models.py` | **All ORM models — the single source of truth for the schema** |
| `session.py` | `get_engine()`, `SessionLocal()`, `session_scope()` |
| `seed.py` | Idempotent reference data: venues + the 8 PRD §5 strategies |
| `migrations/` | Alembic environment and versioned migrations |

## Tables

Reference: `venues`, `markets`, `instruments`.
Market data (**TimescaleDB hypertables on `time`**): `quotes` (top-of-book),
`trades` (public tape — the paper engine fills a resting maker order only when a
later `trade` goes *through* its price).
Strategy/experiment: `strategies`, `trials` (the trials ledger — every variant
tried, including failures).
Ledger: `orders`, `fills` (each fill snapshots `usd_gbp_rate` for tax, PRD §10),
`positions` (materialised per `(strategy, mode, instrument)`; the risk engine
reads this for the $25 per-market cap).
Risk/ops: `incidents` (kill-switch + incident log), `risk_halts` (persistent
kill state), `fx_rates`.

### Conventions

- **One code path for backtest/paper/live**: `orders`, `fills`, `positions`,
  `trials` carry a `mode` column (`backtest` | `paper` | `live`) rather than
  living in separate tables.
- **Money is `NUMERIC`, never float.** `PRICE` = `NUMERIC(18,8)`,
  `SIZE` = `NUMERIC(28,10)`, USD `MONEY` = `NUMERIC(18,6)`.
- **Hypertables carry no FK on `instrument_id`** (indexed instead) to keep
  high-volume ingestion cheap. Application code is responsible for referential
  integrity there. Default TimescaleDB time indexes are disabled; the PK
  `(time, id)` and the `(instrument_id, time)` index cover queries.

## Common commands

```bash
# Apply / roll back
uv run alembic upgrade head
uv run alembic downgrade -1

# Create a new migration after editing models.py, then review it by hand
uv run alembic revision --autogenerate -m "describe change"

# Confirm models match the live DB (CI-friendly; exits non-zero on drift)
uv run alembic check

# Seed reference data (safe to re-run)
uv run python -m tradingbot.db.seed
```

## For agents building on this

`Base.metadata` is authoritative. Change the schema **only** through a reviewed
Alembic migration (`alembic revision --autogenerate`, then edit + `alembic check`
until clean). Coordinate before altering `fills`, `positions`, or `risk_halts` —
the ledger (tradingbot-845) and risk engine (tradingbot-s94) depend on their
shapes.
