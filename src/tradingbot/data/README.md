# Public historical data

Run from the repository root with Python 3.12 via `uv run`. These downloaders
only issue public GETs. They do not use venue credentials, place orders, or
connect to Postgres. The CLI loads `.env` with python-dotenv without displaying
it. Import the captured pages with the separate [database loader](LOADING.md)
(`tradingbot-pu9`, local port 5433).

## Kalshi (research only)

```sh
uv run python -m tradingbot.data kalshi series --run research-20260930
uv run python -m tradingbot.data kalshi events --series KXCPI --run research-20260930
uv run python -m tradingbot.data kalshi markets --series KXCPI --run research-20260930
uv run python -m tradingbot.data kalshi trades --ticker KXCPI-26JUN-T-0.2 \
  --start 2026-06-08T00:00:00Z --end 2026-07-15T00:00:00Z --run research-20260930
uv run python -m tradingbot.data kalshi series-fees --series KXCPI --run research-20260930
uv run python -m tradingbot.data kalshi event-fees --event KXCPI-26JUN --run research-20260930
```

Omit `--series`/`--ticker` to scan the entire public dataset. Trades require an
explicit UTC range (or Unix seconds); timestamp bounds are passed to the API
unchanged. Download both neighbouring windows with overlap and deduplicate
by `trade_id` during loading. Market snapshots include settlement outcomes,
rules, and event references as returned by the API; use event/series metadata
for category and fee attribution. Metadata observed today is not proof of
what was known at an earlier decision time.

Markets/trades capture the cutoff and page through **recent first, historical
second**, preserving both tiers. Archive cutoffs can advance during a scan;
these requests are not an atomic exchange snapshot. Reconcile with a new run
near the handoff for completeness. Raw overlap is intentional. Do not infer
charged per-fill fees from the public trade tape: series/event fee changes
and an explicit historical fee model are required.

`--max-pages N` bounds each endpoint for smoke tests or incremental batches.
The JSON output reports `complete: false` when a cursor remains; this is a
partial capture, not a complete backtest dataset. Rerun the same command to
continue. `--page-size` is 1–1000 (events capped at 200).

## Polymarket US

```sh
uv run python -m tradingbot.data polymarket-us markets --category crypto --run research-20260930
uv run python -m tradingbot.data polymarket-us markets --closed --category crypto --run settled-20260930
uv run python -m tradingbot.data polymarket-us prices --slug cpc-btc-150k-12-31-2026 --run research-20260930
uv run python -m tradingbot.data polymarket-us prices --slug cpc-btc-150k-12-31-2026 \
  --start 2026-09-27T00:00:00Z --end 2026-09-29T00:00:00Z --run daily-windows-20260930
uv run python -m tradingbot.data polymarket-us settlement --slug cpc-btc-150k-08-31-2026 --run research-20260930
```

`markets` supports an exact `--slug`, optional `--closed` / `--no-closed`, and
`--category` (for example `crypto` or `politics`). Omitting a status filter does
not intentionally restrict the scan to active markets. Catalog pagination is
ordered by ID, advances by the actual returned count, and continues until an
empty page. A repeated page of IDs is an error, including across restarts.
The public catalog defaults to hiding hidden markets; this is not an exchange
database export. Changing statuses during offset scans can still cause gaps.

The `display_prices` dataset contains **book-derived display prices**:
`longPrice` is normally the Yes best ask; `shortPrice` is normally one minus the
Yes best bid. Their sum may exceed one because of the spread. It cannot prove
trade-through maker fills. No public historical trade-tape endpoint is documented
on the US gateway; account activity is not a substitute for the whole market.

With no dates, `prices` requests `INTERVAL_ALL` at the documented fidelity of
180: newer histories have roughly three-hour samples and older histories can
be daily. With dates, it requests contiguous windows of at most 24 hours at
fidelity 1, retaining irregular observations. Empty price history can mean an
unknown slug or no stored observations; validate the slug against `markets`.
Settlement returns the venue's settlement price; 404 means unknown or unsettled,
and fails the capture rather than inventing an outcome. Use a new run to retry
an empty history after the venue backfills it.

## Polymarket international (research only)

```sh
uv run python -m tradingbot.data polymarket-intl markets --closed --run research-20260930
uv run python -m tradingbot.data polymarket-intl events --run research-20260930 --max-pages 1
# Copy the outcome token and condition ID from the raw Gamma market record:
uv run python -m tradingbot.data polymarket-intl prices --token "$TOKEN_ID" --run research-20260930
uv run python -m tradingbot.data polymarket-intl prices --token "$TOKEN_ID" \
  --start 2026-09-13T00:00:00Z --end 2026-09-30T00:00:00Z \
  --bucket-seconds 3600 --run hourly-20260930
uv run python -m tradingbot.data polymarket-intl trades --condition "$CONDITION_ID" --run recent-20260930 --max-pages 1
uv run python -m tradingbot.data polymarket-intl resolutions --condition "$CONDITION_ID" --run research-20260930
```

Gamma `/markets/keyset` and `/events/keyset` use `after_cursor`; Data API v2
uses `pagination.next_cursor` / `cursor`. Keep these opaque cursor types separate.
Raw capture retains all market shapes, outcome labels, token mappings, event
nesting, resolution fields and fee metadata. In particular, it avoids the typed
SDK's omission of markets that cannot be represented by a binary model.
`clobTokenIds`, `outcomes` and `outcomePrices` can themselves be JSON strings;
preserve token/outcome ordering. A condition ID identifies the market; a token
ID identifies one outcome and is required for price history.

Prices come from `/v2/prices-history` in USDC per share. No dates means
`interval=max`: full **available sampled** history, normally 12-hour buckets.
The documented full-history resolutions are 10800 and 43200 seconds; finer
`max` resolutions may return only the last 30 days. Explicit ranges are split
into at most 15-day windows (start inclusive, end exclusive), and each window's
cursor is exhausted before the next begins. The full requested range is part
of the job identity, even when two jobs share the same first window. Preserve
each point's `resolution_seconds`: observed responses include a final raw
observation with resolution 0 alongside regular buckets. Never assume every
row has the requested resolution or that an empty range means no trading.

`trades` is saved as `trades_recent`: the documented market-wide public feed
does not support historical time bounds. The downloader intentionally rejects
`--start`/`--end` for it. It requests `taker_only=false` and follows v2 cursors;
cursor exhaustion does not establish historical completeness. No authenticated
CLOB trade history or wallet/account activity is requested. Transaction hash
alone is not a unique fill key. Establish deduplication rules from the actual
raw row fields when loading. The loader uses a venue trade ID or log index when available,
otherwise a fingerprint of the returned economic fields.

All PM data is public. US uses the official SDK with a response hook to retain
exact response text before float parsing. International uses the official
`polymarket-client` (`py-sdk`) raw `SyncTransport.get_bytes` interface with no
signer. These small SDK integration points are covered by transport tests;
recheck them when upgrading the locked SDK versions. Venue paths are
`polymarket_us` and `polymarket_intl` and must remain distinct at load time.

## Raw format and recovery

Files are written only under the gitignored root `data/` by default:

```
data/raw/<venue>/<dataset>/<run>/<query-hash>/
  manifest.json
  page-00000000.parquet
  page-00000001.parquet
```

Each Parquet file contains **one API response page**, not one trade. The stable
schema contains `format_version`, `venue`, `dataset`, `page`, UTC `retrieved_at`,
`request_json`, exact `response_json`, its SHA-256, `record_count`, and nullable
`next_request_json`. Preserving the response text avoids float rounding,
unknown-field loss, and heterogeneous Arrow schemas. Even empty terminal
responses are saved. Example for inspecting a page:

```python
import json
from decimal import Decimal
import pyarrow.parquet as pq

page = pq.read_table(path).to_pylist()[0]
response = json.loads(page["response_json"], parse_float=Decimal)
trades = response["trades"]
```

`manifest.json` binds the query and data semantics to the job. Files are
flushed and atomically renamed before advancing the checkpoint. A process
lock prevents simultaneous writers to one job. Recovery validates page
continuity, request chaining, and checksums; `.partial-*` files are ignored.
A failed request, malformed payload, or cursor cycle leaves the last valid
checkpoint intact. Stop and investigate corrupt files; do not delete valid
pages merely to get a scan to finish.

A run name identifies a frozen capture: completed jobs do not refresh. Use a
**new `--run`** for a later snapshot, changed venue data, or stale/expired
cursors. Query changes create a different job hash. No claim is made that a
paginated mutable API provides a point-in-time consistent snapshot. Loaders
must explicitly deduplicate trades, reconcile snapshots and establish actual
time coverage before running a backtest.

Transient failures retry at most five times with pacing (four requests/second
at most, plus response latency). Permanent errors fail immediately. Retry-After
is honoured up to 60 seconds; a larger value stops the run for later resumption.
Do not confuse these downloader retries with the live trading risk engine.

## Verified sources (2026-09-30)

- [Kalshi archive partitioning](https://docs.kalshi.com/getting_started/historical_data)
- [Historical trades](https://docs.kalshi.com/api-reference/historical/get-historical-trades)
- [Historical markets](https://docs.kalshi.com/api-reference/historical/get-historical-markets)
- [Series fee changes](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes)
- [Event fee changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes)
- [US market catalog](https://docs.polymarket.us/api-reference/markets/get-markets)
- [US price history and its sampling limits](https://docs.polymarket.us/api-reference/price-history/get-price-history)
- [US settlement prices](https://docs.polymarket.us/api-reference/markets/get-market-settlement)
- [International keyset catalogs](https://docs.polymarket.com/market-data/discover-markets)
- [International price history windows and resolution](https://docs.polymarket.com/market-data/prices-order-books)
- [International recent trades and resolutions](https://docs.polymarket.com/market-data/public-analytics)

The binding PRD names `kalshi-python`. This downloader uses its public raw
`ApiClient` transport because typed models can drop new fields and the package
has no historical endpoint wrappers. [Kalshi now deprecates that package](https://docs.kalshi.com/sdks/overview)
in favour of `kalshi_python_sync`/`kalshi_python_async`; migration can be a separate
change. `cryptography` is explicit because the installed SDK imports it without
declaring it. No keys are configured on the client.
