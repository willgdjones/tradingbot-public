# Shared IEX intraday observations

`tradingbot-yma`, 2026-10-02. Data infrastructure for the owner-approved J1–J4
universe; no strategy outcome, model call, account funding or order is involved.

Use the existing paper credentials and official Alpaca SDK with **IEX explicitly
selected**, raw one-minute prices, no paid-feed fallback. The 40 symbols are the
20 ETFs and 20 stocks listed in the bead. Poll bounded batches during the broker's
regular calendar, including early closes. Persist bars and their revisions with
both event time and local receipt time in TimescaleDB. Previously captured
versions remain available for point-in-time reconstruction.

Store quote event time independently of receipt time. Re-reading an unchanged
old quote must never refresh its risk timestamp. Completed bars are features,
not fresh quotes or maker-fill evidence. Missing, malformed, crossed, future or
stale quotes remain unavailable to execution under the existing 30-second rule.

Build immutable 15-minute snapshots from completed intervals and versions known
strictly before their recorded decision time. Retain missing-minute coverage;
never forward-fill missing bars. A restart may capture historical warm-up bars
with **current receipt times**, but cannot manufacture an earlier decision or
rewrite an existing snapshot. Consumers must still obtain fresh execution quotes
and apply the unchanged risk engine.

Bound polling windows, page counts and response sizes. Deduplicate unchanged
observations; retain changed revisions. Check total database size and free disk
before writes, stop before the existing 20 GB data/30 GB free-space limits, and
do not delete evidence automatically. Persist recorder health independently of
quote freshness. Run the recorder as a service in the existing tmux services
window; no restart or modification of the TOM trial is needed.

API contracts checked 2026-10-02: [historical bars](https://docs.alpaca.markets/us/reference/stockbars)
paginate across symbols and use inclusive bounds; [real-time data](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
documents minute-start timestamps and late bar revisions. Monid discovery offered
paid quote endpoints only; none were used. The implementation and synthetic
checks will establish the concrete storage and consumer interface before launch.

## Shipped interface and validation

`src/tradingbot/data/iex_intraday.py` polls the explicit IEX REST endpoints every
15 seconds. It captures raw minute bars once per minute with a three-minute
revision overlap, and the current regular session as warm-up after startup.
Pagination is bounded to four pages / 15,600 bars. Quote capture is batched for
all 40 symbols; source timestamps and raw round-lot sizes are retained. The
standard risk tape gets actual exchange timestamps, never heartbeat timestamps.
Missing/invalid/stale quotes are excluded per symbol and reported in health.

Additive migration `iex40data` creates TimescaleDB `iex_minute_bars` and
`iex_snapshots`, plus `iex_recorder_health`. Versions deduplicate only when the
latest payload is unchanged; late revisions append. Snapshots created 5–90
seconds after a regular quarter-hour boundary are immutable, including missing
minutes. A restart outside that window skips the old boundary. Early closes
come from the broker's calendar. No historical snapshot is fabricated.

- `bars_asof(session, symbol=..., start=..., end=..., known_before=...)` returns
  the latest revision of each completed minute known **strictly before** the
  supplied time. This is the warm-up interface for the separate state builder.
- `load_snapshot(session, symbol, decision_at=..., boundary=None)` returns a
  detached, digest-verified current-session snapshot already known before the
  decision, or `None`. It refuses a boundary older than 16½ minutes. `intervals`
  has regular-session 15-minute aggregates, coverage gaps and source revision
  hashes; incomplete OHLCV is explicitly labelled and must not be mistaken for
  a complete signal window. Its quote is a feature observation; every order
  still needs a fresh execution quote and the shared risk/cost guard.
- `IexRecorderHealth.state` reports poll status and the last per-symbol quote
  assessment. Health receipt time is **not** evidence that a quote is fresh now.
  Consumers recompute age from `quote_ts` and the current time. Errors preserve
  captured evidence and have sanitized incident/log codes.

`ops/iex_intraday.sh` runs under an additional pane in `ops/services.sh`.
A PostgreSQL session lock prevents duplicate recorder processes. The existing
TOM and scheduler panes are preserved. Apply `uv run alembic upgrade iex40data`
before invoking the script, or use `uv run python -m tradingbot.data.iex_intraday
--once` for one bounded capture. No retention deletion is automatic: combined
archive/database size is checked each minute, free disk before every batch.

Validation on October 2: **28 focused checks** cover strict knowledge cutoffs,
late revisions, deduplication, missing minutes, immutable snapshots, unchanged
quote timestamps, invalid/future/crossed quotes, raw units, startup/early-close
timing, IEX-only pagination, response/window bounds and combined storage. The
migration is applied and Alembic reports no schema drift. First real capture
stored **11,529 minute revisions across all 40 symbols**, **40 snapshots** for
19:00 UTC, and actual quote observations. Only **15/40** latest quarter-hour
intervals contain all 15 minutes; free IEX gaps are explicit, not synthesized.
Quote probes had **33–39/40** fresh valid symbols. These are feed-quality counts,
not a strategy trial or evidence of profit.

The focused checks plus the existing AI-forward and risk suites pass together:
**93 passed**, with one upstream websockets deprecation warning. Shell syntax,
Python compilation and whitespace checks also pass.

The watchdog observed the new service hook before schema application, producing
sanitized startup failures; capture succeeded after migration. Only the new
recorder pane was paused for bounded validation. No TOM restart, allocation,
paper-book reset, model request or order occurred. The $140 shared paper cash
book and trial 3298 remain unchanged. Final service status is recorded below.

**Service verified 19:06 UTC:** the final implementation `860c874` is running in
the new recorder pane. Health was 3.5 seconds old, 34 quotes were fresh and valid,
and minute revisions had advanced to 11,700. The 40-symbol source recorder is
operational; partial IEX coverage is an explicit downstream eligibility input.
Research/data bead complete. AI-1 remains unlaunched while its overlap with the
newer J1 specification is resolved; no experiment pass is implied.
