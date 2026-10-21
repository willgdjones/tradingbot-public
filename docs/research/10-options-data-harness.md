# Free Alpaca options archive: surfaces, evidence and limits

2026-09-30 America/Los_Angeles / 2026-10-01 UTC, `tradingbot-lwv`, OrangeCove.
The harness archives current contract metadata, current indicative chains and
quotes, and bounded historical bars/trades through the official Alpaca SDK.
It uses the existing paper credentials in `.env`, GET-only transports, and no
paid endpoint, subscription, order, exercise, account or permission change.
This is data plumbing, not a passed options strategy or promotion.

## What each surface means

| Surface | Captured information | What it cannot establish |
|---|---|---|
| Paper `/v2/options/contracts` | Explicit underlying, expiry bounds, active/inactive status, size, deliverables, strike/type/style, dated open interest | Point-in-time historical chain membership or historical tradability |
| Data `/v1beta1/options/snapshots/{underlying}` | Latest indicative quotes/trades and vendor Greeks for the requested expiry range | An historical option-chain snapshot, executable OPRA BBO, or independently verified Greeks |
| `/options/quotes/latest` | Explicit symbols, indicative bid/ask, size and timestamp | Tradable prices or stale-data exemption |
| `/options/bars`, `/options/trades` | Explicit symbols and bounded inclusive historical time interval; symbol-first pagination exhausted | Historical BBO, contemporaneous spreads/Greeks or maker fills |

[Alpaca describes the free indicative feed](https://docs.alpaca.markets/us/docs/historical-option-data)
as modified quotes and delayed derived trades, with documented option history
from February 2024. The [chain](https://docs.alpaca.markets/us/reference/optionchain)
and [latest quotes](https://docs.alpaca.markets/us/reference/optionlatestquotes)
requests explicitly set `feed=indicative`; no automatic OPRA fallback is allowed.
The [historical trades](https://docs.alpaca.markets/us/reference/optiontrades)
and [bars](https://docs.alpaca.markets/us/reference/optionbars) endpoints expose
no feed selector, so this harness labels their feed **provider-unspecified**.
It does not claim those returned histories are indicative or actual OPRA fills.
The API start and end are inclusive; downstream frozen datasets must explicitly
convert their coverage to the backtester's exclusive end convention.

The [contract catalog](https://docs.alpaca.markets/us/reference/get-options-contracts)
defaults to active/near-expiry contracts. Explicit expiry bounds and status avoid
that silent restriction. Expired contracts can be requested as inactive, but
metadata retrieved today still cannot prove when a contract entered an old
trading universe. Open interest carries its own date. Never screen past entries
using today's open interest, status or a survivorship-filtered current catalog.

## Archive and safety properties

`src/tradingbot/data/alpaca_options.py` keeps the exact response text in Zstandard
Parquet API pages before SDK float coercion, with request, retrieval timestamp,
checksum, record count and next cursor. Manifests identify immutable queries.
A repeated run resumes its cursor and validates existing pages; refreshing a
current chain/quote requires a **new run ID**. A run ID is not an as-of date.
Multi-page current chains are sequential observations, not atomic snapshots.

Explicit UTC history bounds begin on/after 2024-02-01 and end at least 16 minutes
before retrieval. The client is paced below 100 requests/minute before retries,
with bounded retry/timeout behavior. History uses at most 100 contract symbols
per query. `--max-pages` bounds each call; incomplete captures remain visibly
incomplete and must be resumed before coverage is claimed. Full pagination is
required because the provider sorts by symbol before timestamp.

All options files live under `data/options/`; the **global `data/`** coordinated
budget remains below 20 GB with at least 30 GB free plus write headroom. It
shares the same reservation lock as the longshot downloader, checks before
capture and each GET/write, and refuses roots outside that budgeted tree.
No old file is removed to make space. Quotes and contracts do not enter the
executable backtest/feed tables.

The audit independently checks checksums, page sequence, request chain, record
counts, cursors and repeated pages. It lists requested symbols with no history,
per-symbol timestamps, retrieval times and quote age at retrieval. Empty pages
mean no returned records, not a zero option price. All reports explicitly set
historical-BBO, historical-chain-membership and executable-fill-evidence false.
Availability is no earlier than retrieval, even if a quote's event timestamp is
older. A current snapshot can never be assigned to a prior research date.

## Verified capture

Run `options-probe-20261001` used only free read-only requests. These are bounded
integration/coverage samples, not a reconstructed universe from 2024 onward.
The [compact audit evidence](10-options-data-harness-results.json) records every
request, response-set hash, completeness, count and local archive path.

| Sample | Result |
|---|---:|
| F active contracts, expiries Oct 1–16 2026 | 206 contracts, 1 complete page |
| Matching F indicative chain | 206 snapshots, 1 complete page |
| SPY active contracts, expiry Oct 16 2026 | 458 contracts, 1 complete page |
| Matching SPY indicative chain | 458 snapshots, 1 complete page |
| SPY inactive contracts, expiry Feb 16 2024 | 362 contracts, 1 complete page |
| SPY Feb 16 2024 490 call and put daily bars, Feb 1–16 | 22 bars, 1 complete page |
| Same two historical contracts/dates, trades | 37,107 records, 4 complete pages |
| Explicit latest quotes, one call/put each for F and SPY | 4 indicative quotes, 1 complete page |

The demonstration underlyings were fixed for data-shape coverage, without any
return-based selection. Their inclusion is not an options recommendation or a
claim that a trade fits the account. Contemporary captures were made outside
market hours; old timestamps are expected and remain labelled in the audit.
No quote in this archive bypasses the shared 30-second stale-data rule.

## Cash-account research handoff

For long calls/puts, research must budget **ask premium × the recorded contract
size plus fees**, validate the actual deliverables, and model expiration and
possible exercise explicitly. A low quoted per-share premium is not the whole
contract cost. For a cash-secured put, use the full strike obligation from the
recorded size/deliverables, reserve exercise/assignment fees, and apply the
strategy-slot limit; do not treat premium proceeds as free collateral. For a
standard 100-share contract, a $140 slot permits at most $1.40 strike collateral
before fees. Even a nominally cheap $5 strike needs $500 and does not fit that
slot. The harness preserves nonstandard deliverables and never silently assumes
all contracts are 100-share standard options.

No option order/assignment/fee simulator exists in this data harness. A candidate
needs its own exact fee, exercise, settlement, corporate-action and position-risk
model before execution research. Indicative prices can support integration and
explicit sensitivity scenarios, but cannot establish executable option alpha.
Missing historical BBO must remain a limitation; do not invent spreads or relabel
trade prints as historical quotes. Future chain observations can be accumulated
with new run IDs at a preregistered cadence once a candidate specifies its needs.

## Short holdout and prior inspection

Even full documented coverage 2024-02-01 through 2026-10-01 gives only about
32 months. The shared `HoldoutSplit` places the final 30% boundary at
**2025-12-13 02:24 UTC**, leaving **291.9 days (about 9.6 months)**. This is a
boundary illustration, not a consumed trial or a claim of complete source data.
The actual probes above cover two contracts for two weeks. They cannot be used
as proof of a multi-year options strategy.

A future dataset must bind the archived hashes, universe/selection and adjustment
policy, freeze its actual full coverage, tune only the first 70% and consume the
last 30% once per version. Published selection bias, previous probes and any
inspected SPY equity history remain disclosed. A short final period cannot test
all volatility, assignment and liquidity regimes. There is no luck filter added;
counts, uncertainty and absent execution evidence must remain visible.

## Commands

```sh
uv run python -m tradingbot.data.alpaca_options contracts --run-id my-catalog --underlying F --expiry-from 2026-10-01 --expiry-to 2026-10-16
uv run python -m tradingbot.data.alpaca_options chain --run-id my-snapshot --underlying F --expiry-from 2026-10-01 --expiry-to 2026-10-16
uv run python -m tradingbot.data.alpaca_options quotes --run-id my-quotes --symbols F261009C00016000,F261009P00016000
uv run python -m tradingbot.data.alpaca_options trades --run-id my-history --symbols SPY240216C00490000,SPY240216P00490000 --start 2024-02-01T00:00:00Z --end 2024-02-16T23:59:59Z
uv run python -m tradingbot.data.alpaca_options audit --directory data/options/raw/alpaca/options_trades/options-probe-20261001/3cd3009cef43d55c88e67cbc
```

No recurring job or real/paper option order is activated by these commands.
