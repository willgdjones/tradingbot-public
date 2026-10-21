# Live market-data recorder (`tradingbot-xgt`)

Captures the Polymarket US **order book** and **public trade tape** into the
TimescaleDB `quotes` / `trades` hypertables, and keeps a **staleness heartbeat**
so the risk engine's §6 gate ("halt if data is more than 30 s old") stays honest.

```sh
uv run python -m tradingbot.recorder --slug will-it-rain-nyc-2026-10-01 --slug some-other-market
uv run python -m tradingbot.recorder --slug my-market --lite   # best-price updates only
```

Requires `POLYMARKET_US_KEY_ID` / `POLYMARKET_US_SECRET` (the market websocket is
authenticated) and `DATABASE_URL` in `.env`. It writes only `quotes`, `trades`
and the incident log — it never places orders.

## Design

The Polymarket US market websocket (`polymarket_us.websocket.markets`) is an
event emitter whose callbacks fire synchronously on the asyncio loop. The
recorder is split so the logic is testable without a network:

| Module | Responsibility |
|---|---|
| `decode.py` | Pure wire-frame → `QuoteObs` / `TradeObs`. Prices parsed with `Decimal`, never `float`. The **receive** timestamp becomes the row `time` (see below); the venue's own event time is kept in `meta`. |
| `heartbeat.py` | `FeedHealth`: liveness timestamps + the keep-alive / silence decisions. Cadence is derived from `risk.limits.STALE_DATA_MAX_SECONDS` so it can never drift from the gate. |
| `store.py` | `resolve_subscriptions` (slug → `instrument_id`) and `DbSink` (write + flush; the driver commits). |
| `recorder.py` | `MarketDataRecorder`: a synchronous core (handlers + `tick`) and a thin async `run()` that owns the socket lifecycle, subscriptions and reconnect backoff. |

### Why the receive timestamp is authoritative

The §6 staleness gate means *how long since we last observed data*, so the row
`time` must be **our** clock at receipt, not the venue's. A skewed or oddly
formatted venue timestamp can then never make stale data look fresh. The venue's
precise `transactTime` / `tradeTime` is preserved in `metadata.transact_time` /
`metadata.trade_time` for the tape and the paper engine.

### The staleness heartbeat

* Every book update and trade is written straight through.
* `tick()` re-snapshots each subscribed market's top-of-book on a cadence well
  under 30 s (`KEEPALIVE_INTERVAL_SECONDS`, marked `metadata.source = "keepalive"`),
  so a **connected but quiet** market never trips the gate falsely.
* When the feed goes silent past `FEED_SILENCE_SECONDS`, a single `connectivity`
  incident is logged — and, because the re-snapshots stop, the data legitimately
  ages out and the §6 gate halts trading on its own. There is no dead-man
  protection beyond this (PRD §9).
* A websocket error counts toward the §6 five-errors-per-minute API halt via
  `RiskEngine.record_api_error`.

### Slug → instrument resolution

Canonical (from the historical loader, `tradingbot-pu9`): a market is keyed by
`markets.external_id = slug`, and the Yes (long) / No legs are
`instruments.external_id = "<slug>:yes" / "<slug>:no"`. A PM US market's book is
quoted on the Yes side, so that is the line recorded. A `symbol == slug` match is
a fallback for hand-seeded data.

Historical `quotes` rows written by the loader carry `metadata.historical.kind =
display_price` with NULL BBO columns; they are **not** live BBO and must not be
treated as a heartbeat. Live rows this recorder writes carry
`metadata.source = market_data | market_data_lite | keepalive | trade` and always
have a recent `time`, so `max(time)` naturally reflects live liveness.
