# Historical data in TimescaleDB

`tradingbot-pu9` imports the [public Parquet archives](README.md) into the existing
Claude foundation schema. Run from the repository root:

```sh
# Validate identities, page order, request chains, checksums and normalization.
uv run python -m tradingbot.data.loader --validate-only
# Import data/raw, or supply another archive root as the positional argument.
uv run python -m tradingbot.data.loader
# Includes transaction-rollback integration tests on the existing database.
RUN_DB_TESTS=1 uv run pytest tests/data -q
```

The write command loads `.env` through python-dotenv and requires the existing
local `tradingbot` database on port **5433**. It does not create tables, seed or
enable venues, alter risk settings, or write orders/fills/positions/trials.
`--validate-only` does not open a database connection.

Each page is one transaction, serialized against other loader instances with
an advisory lock. All archives are checked first; catalogs precede settlement
and observation pages. A missing catalog mapping, contradictory trade ID,
unsupported payload, or value the schema cannot represent exactly stops the
import. The failing page rolls back; earlier committed pages remain. After
repairing the source problem, rerun the command: already imported observations
and snapshots are skipped. No checkpoint file must be reset. Page bodies are
read one at a time; only descriptors stay in memory across the run.
Existing market/instrument references are locked and loaded once per page;
repeated references still retain each distinct source snapshot and source-time
ranking. Already-known snapshots do not copy or rewrite metadata.

The duplicate contract is enforced by this importer, not a new DB constraint.
Other writers must coordinate on identities if they ingest the same history.
Earlier derived fingerprints are upgraded in place using canonical decimals
and UTC timestamps; this never changes venue-native trade IDs. Trade identities
include the instrument, so identically named US and
international instruments remain separate. A repeated native trade ID with a
changed time, price, quantity or eligibility is an error, including when its
old timestamp falls outside the current page's time range. Decimal spelling
(e.g. `0.50` versus `0.5`) does not change an economic fingerprint.

## Mappings and evidence

| Source | Market `external_id` | Instrument `external_id` |
|---|---|---|
| Kalshi | Event ticker | Contract ticker + `:yes` / `:no` |
| Polymarket US | Market slug | Slug + `:yes` / `:no` (long / short) |
| Polymarket international | Condition ID | Actual outcome token ID |

The venue is always part of the lookup. US named outcomes follow the explicit
`marketSides.long` mapping, not alphabetical outcome labels. International
outcome/token array order is retained, including reversed Yes/No order and
markets with more than two outcomes. Kalshi event status/times summarize only
the **observed** contracts; they do not establish complete event coverage.
Its payouts are per instrument, never a single resolution for a multi-contract
event. Missing source titles/categories are left unknown.

Market and instrument `metadata.historical` contains:

- `version: 1`, `snapshots` indexed by content hash, and `latest` mapping each
  evidence channel to its latest snapshot. Each snapshot retains `raw`,
  normalized `fields`/`state`, source timestamp rank and provenance.
- Instrument `state.status` and `state.payout` (exact decimal string or null).
  A US settlement endpoint overrides catalog guesses. A catalog's resolved
  flag alone cannot create a payout from invalid/missing outcome prices.
  International oracle proposals/sentinel values are evidence only.
- `source` in each snapshot: archive path, job hash, page, response checksum,
  request, retrieval time, data semantics and capture completion flag.

Source-updated timestamps rank catalog versions when available, falling back
to retrieval time. Older snapshots remain queryable but cannot overwrite newer
state. Other applications' metadata keys are preserved. Auxiliary series,
cutoff, fee-change and event documents live in `venues.metadata.historical.documents`.
The Parquet response text remains the lossless source; JSONB decimal numbers
are converted to exact strings.

`retrieved_at` is when this system observed a snapshot. A current catalog or
its source-updated timestamp does not establish what a strategy knew months
ago. Apply evidence-availability rules when forming signals; final payout
labels may be used to score the result, not as prior trading information.
A missing payout is unknown, not zero.

## Reading prices and trades

US display prices and international sampled prices live in `quotes` with
**all BBO/last/size columns NULL**. Their values are in metadata, because these
sources do not establish actual executable BBO or last-trade semantics:

```sql
SELECT v.key, i.external_id, q.time,
       q.metadata->'historical'->>'kind' AS price_kind,
       (q.metadata->'historical'->>'price')::numeric AS observed_price,
       q.metadata->'historical'->>'resolution_seconds' AS resolution_seconds
FROM quotes q
JOIN instruments i ON i.id = q.instrument_id
JOIN venues v ON v.id = i.venue_id
WHERE q.metadata->'historical'->>'kind' IN ('display_price', 'sampled_price')
ORDER BY q.time, q.id;
```

These observations carry `maker_fill_eligible: false`. International resolution
0 observations retain that value; do not assume uniform sampling intervals.
Source corrections with a different price/resolution at the same timestamp
remain distinct observations; the consumer must select its sampling policy.

Kalshi trade rows represent a matched trade on **both outcome instruments**.
Each has the same native `external_trade_id`, its side's price and the projected
aggressor side. Sum volume on one outcome only, or deduplicate by venue and
native trade ID; summing both doubles matched volume. Block trades are excluded
from maker-fill eligibility. The eligibility flag is a prerequisite; the
backtester must still enforce later-time, strict trade-through, side, size and
execution assumptions under PRD §7.

```sql
SELECT t.*, i.external_id
FROM trades t
JOIN instruments i ON i.id = t.instrument_id
WHERE t.metadata->'historical'->>'maker_fill_eligible' = 'true'
ORDER BY t.time, t.id;
```

International recent activity is retained in `trades` for descriptive research,
with `maker_fill_eligible: false` and `aggressor_side: NULL`: a wallet's BUY/SELL
side is not necessarily the aggressor. Without a native trade ID or log index,
the dedup key uses transaction, wallet, token, timestamp, side, price and size.
Distinct returned economic fills survive; indistinguishable rows cannot prove
distinct executions. This feed is not a complete historical tape. PM US has no
historical tape in these captures. None of these records are account fills or
fee evidence for a trading ledger.

The new `trades_taker_history` dataset is separate. Its source must be the
official `/v2/trades` endpoint with an explicit condition filter (up to twenty
IDs) and `taker_only=true`. The current API spec documents a three-year served
window and one row on the taker side per fill. The normalizer verifies the
request and returned condition, maps BUY/SELL to aggressor direction, and permits
strict later-trade maker matching. Block timestamps do not establish ordering
within a second. An economic fingerprint conservatively collapses indistinguishable
rows; the API's default 0.01-share minimum is also a coverage limitation.
These facts do not make old mixed-side activity maker eligible.

Migration `98b1835af012` preserves all public tape price/size decimals in
unconstrained NUMERIC; the earlier fixed scale rejected genuine v2 prices such
as `0.997952381`. Order/fill/position accounting types are unchanged. Quotes and
trades have instrument-segmented, time/id-ordered compression, with daily policies
for chunks older than seven days. The historical capture workflow checks the
owner's disk budget before writes and explicit compression. Downgrade refuses
to narrow the tape types if doing so would lose any source precision.

## Fixed thirteen-month cohort (`tradingbot-oma`)

The expanded capture uses the preselected categories and dates in
[the history plan](../../../docs/research/08-history-plan.md). Use the scoped
loader for this work, since the raw archive also contains broader exploratory
catalogs and deliberately interrupted probes:

```sh
uv run python -m tradingbot.data.bulk_history resolutions
uv run python -m tradingbot.data.bulk_history_load load
uv run python -m tradingbot.data.bulk_history_load compress
uv run python -m tradingbot.data.bulk_history_load report
uv run python -m tradingbot.data.bulk_history_load capture-report
```

The loader validates all expected request chains and refuses missing or partial
jobs. `load --allow-incomplete` is an incremental import of complete jobs only;
its result explicitly records every missing job and cannot certify completion.
Catalog filtering happens before normalization, while original page hashes and
provenance remain intact. Every 32-page load batch (or 30 seconds) checks the
20 GB data-tree ceiling; every page transaction checks the 30 GB free-space
floor before and after its write, with headroom. Old-chunk compression checks
both limits and reserves twice the source chunk size. The capture audit verifies
all expected requests, including empty daily Bitcoin catalogs, and distinguishes
empty, partial, absent and finalized zero-volume-skipped trade requests.

For international markets, the `resolution_time` evidence channel supplies
`resolve_ts` from an explicit terminal resolution timestamp, or a resolved
lifecycle event carrying a transaction hash and log index. It takes precedence
over catalog times, including later catalogs that omit `resolvedTime`. Scheduled
`endDate` is not proof of payout availability. Oracle prices may use 18-decimal
units or unresolved sentinel values; this channel never invents a payout by
scaling them. Separately validated catalog outcome/token mappings supply labels.

The report includes per-category and monthly eligible trade counts, execution
identities, event/contract/day coverage, observed time bounds, missing payout and
resolution labels, and actual database/compression size. Capture completion does
not establish profitability or authorize promotion.

## Initial implementation sample loaded on 2026-09-30

| Venue | Markets | Instruments | Trade rows | Price observations |
|---|---:|---:|---:|---:|
| Kalshi | 67 | 1,104 | 8,250 (4,125 matched trades) | 0 |
| Polymarket US | 7 | 14 | 0 | 4,636 |
| Polymarket international | 10 | 20 | 4 | 972 |
| **Total** | **84** | **1,138** | **8,254** | **5,608** |

The 35 pages cover 25 capture jobs, **eight partial**. Cursor exhaustion means
that particular request completed, not that the exchange's history is complete.
The present data are implementation samples; they do not meet the PRD's
strategy-validation history requirements. Some catalogs include sports records;
these are source metadata, not authorization to research or trade sports.

Observed time bounds (UTC, across the captured instruments, without claiming
continuous coverage):

- Kalshi trades: 2026-06-09 13:01:55.804676 to 2026-07-14 12:23:57.422990.
- US display prices: 2026-07-10 00:00 to 2026-09-30 00:00.
- International sampled prices: 2025-11-26 00:00 to 2026-09-30 17:07:41.
- International recent activity: 2026-09-30 16:23:09 to 16:28:39.

All 51 data tests passed. The final source/DB check matched every normalized
observation and its evidence. The initial import skipped four overlapping source
observations. A full rerun
skipped all 13,866 source observations and added zero trades, quotes, documents
or reference snapshots, and upgraded zero identities. Verification found no orphan instrument references,
no duplicate trade/price identities and no sampled values misclassified as BBO.
Venue identity/enablement and all strategy, trial, ledger, FX, incident and risk
rows matched the pre-import baseline. Venue metadata and its automatic update
timestamp changed to retain source documents, as intended.
