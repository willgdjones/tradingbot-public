# Strategy #1 history expansion — fixed capture cohort

Recorded 2026-09-30 for `tradingbot-oma`, before inspecting any strategy returns.

The observation window is **2025-09-01 00:00 UTC through 2026-10-01 00:00 UTC**
(exclusive end), thirteen calendar months. This is a bounded cross-category
research cohort, not a claim to have downloaded either exchange in full.

| Venue | Cohort | Selection |
|---|---|---|
| Kalshi | `KXHIGHNY`, NYC daily maximum temperature | Every daily event in the window, all strikes |
| Kalshi | `KXINX`, daily S&P 500 range | Every daily closing event in the window, all strikes |
| Kalshi | `KXBTC`, Bitcoin range | The 17:00 America/New_York event each day, all strikes |
| Polymarket international | series `10005`, `nyc-daily-weather` | Every daily event in the window, all constituent conditions |
| Polymarket international | series `41`, `btc-up-or-down-daily` | Every daily event in the window, all constituent conditions |

The recurring series and their identifiers were verified against public venue
metadata. No market is selected using its winning outcome, return, or strategy
performance. All selected catalog records remain in the audit, including missing
settlements and zero-volume markets. Zero-volume Kalshi contracts may skip their
trade request only when the final catalog explicitly reports exact zero; these
are counted separately, not described as exhaustively queried tapes. Missing
volume is not zero. Capture completeness and settlement availability are separate.

These series cover weather, financials, and crypto without sports or company/
government announcements. Correlated daily outcomes and sibling strikes are not
independent observations. The subsequent backtest must report event/date counts,
calendar regimes, fees, drawdown and luck odds, and must not treat a thousand
strikes as a thousand independent events. The capture does not promote a strategy
or establish that any price process or fill assumption transfers to PM US.

## Tape and point-in-time limitations

- Kalshi: retain both recent and historical public trade endpoints, native trade
  IDs, exact decimals, settlement evidence and source timestamps. Capture the last
  seven days before each scheduled close (including endpoint overlap), sufficient
  for the strategy's seven-day eligibility window. Block trades remain ineligible
  for maker fills. Final catalog facts are labels, not historical trading signals.
- PM international: the current official Data API v2 spec says a condition-scoped
  request serves a **fixed three-year window**. `taker_only=true` returns each fill
  on its taker side; `false` also returns maker rows. A September 2025 weather
  condition returned 42 trades and an exhausted cursor in the initial probe.
  Capture the complete served condition feed, without pretending unsupported
  `start`/`end` filters apply to market requests. The default minimum size is 0.01
  shares. Report observed timestamp bounds and empty results explicitly.
- The distinct `trades_taker_history` dataset carries this verified request
  contract. Earlier mixed-side `trades_recent` archives keep their ineligible
  status. No actual trade ID or log index is exposed by the normal v2 row: use a
  conservative economic fingerprint, collapsing indistinguishable repeated rows
  rather than inventing extra fill volume. Block timestamps have second precision;
  same-timestamp ordering cannot support a later-trade maker fill.
- PM US still lacks a documented public historical trade tape here. Its sampled
  display prices cannot fill a maker order. International history is research only;
  trading remains PM US only. Current PM US fees on another venue's history are
  an explicit counterfactual, not observed historical fees.
- Polymarket daily weather catalog `endDate` can precede the day's final outcome.
  The handoff must disclose the distinction between scheduled close and actual
  resolution evidence. Never backdate a payout into a signal.

## Storage and completion

Keep the entire repository `data/` tree strictly below **20,000,000,000 bytes**.
Before each capture/load batch, abort if free space is below **30,000,000,000
bytes**; reserve additional space for the next write. Check before fetching and
before saving each page. Preserve compressed Parquet pages and resumable request
chains. On a failed budget gate, leave completed pages intact and stop; never
delete unrelated data or silently truncate the cohort. Load only this cohort's
catalog/tape into the local port-5433 DB. Add Timescale compression policies and
verify actual compressed storage. No risk-limit or trading-state changes.

Capture writers coordinate with an OS file lock and a shared conservative byte
reservation journal. Every batch performs a full data-tree scan; active writes
rescan after 30 seconds or 128 reservations as well. Each page reserves its
uncompressed size times three (at least 64 KiB) before the atomic write, plus
the 64 MiB safety margin. The reservation is fsynced first, so an interruption
can overcount until the next scan but cannot restore spent capacity. Actual
free space is checked before each GET, after its response, and around each
serialized write. This removes redundant whole-tree scans from concurrent
workers while preserving the owner's limits. Other data writers remain visible
at each full batch scan and in every free-space check.
Capture batches now contain at most 128 jobs. This changes scan/checkpoint
frequency only: four workers, at most four request starts per second, the
30-second/128-write scan gates, and every per-page reservation remain unchanged.
The progress cache can be replayed after a checkpointed restart; completed
immutable archive pages are revalidated and reused without another network fetch.
Database loading performs a full scan every 128 pages (or after 30 seconds) and
checks actual free space before and after every page transaction. DB writes do
not grow `data/`; both capture processes still account for each archive write.
The 128-page load batch replaces the initial 32-page batch after profiling found
the 124,000-entry tree scan took 9.6 seconds versus 1.0 second for a representative
622-observation strict database comparison. The 30-second scan-age gate,
per-page free-space checks and every capture-write reservation remain in force.

The final compression pass revisits **all** chunks older than seven days,
including chunks marked compressed: a later historical insert can leave a
rowstore tail in an already-compressed chunk. The installed TimescaleDB 2.30.2
supports idempotent `compress_chunk(..., if_not_compressed => true)` to fold in
those rows. Headroom uses `chunks_detailed_size`, which includes rowstore and
compressed storage, rather than only the visible chunk heap. A real, rolled-back
Timescale test compresses a chunk, inserts late rows, runs this pass twice and
checks storage-state restoration plus unchanged row count and sum. See the
[Timescale compression API explanation](https://www.tigerdata.com/blog/building-iterative-compression-for-dynamic-applications).

The completion report must enumerate selected events/contracts, complete/partial/
empty/zero-volume-skip jobs, actual trade rows and unique executions, per-month
coverage, missing payouts, raw/database bytes, remaining free space, validation
and idempotent rerun results. If evidence remains insufficient, record the gap
instead of claiming statistical proof. `tradingbot-yg2` owns the returns and
promotion review after capture; all six pre-existing parameter variants stay in
the trials ledger.

One currently captured Polymarket condition has conflicting settlement evidence:
`0xc43ed576db00fc6e4954b09376fd15bd77a100b9421df23cb26cf1d4bef660dd`
(`bitcoin-up-or-down-on-july-25-2026`). Gamma's market snapshot still says
`umaResolutionStatus=proposed` even though the Data API lifecycle row says
`resolved`. Its terminal timestamp is preserved, but that timestamp and an
oracle price do not independently certify the payout mapping for both tokens.
The loader leaves both token payouts null instead of turning display prices or
proposal fields into settlements. The final report must retain this gap and the
backtest must exclude those unverified payouts. Catalog response SHA-256:
`018e26928a3b7525a5b8e126c02f7ab98edc4be31a4f293b408a8e12b5cb54df`;
resolution response SHA-256:
`8262b9a40a29bc2e560547223f3bcbdab9ef150575a765ed44b201c33fe4c872`.

## Catalog coverage and chronology findings

These are source-metadata findings before the expanded strategy replay. They
do not change the fixed cohort or manufacture replacement events. Request
completion, daily coverage, usable trading windows and independent observations
are separate quantities.

- The expected Kalshi BTC events `KXBTC-25DEC2617` and `KXBTC-25DEC3117`
  returned zero catalog rows from **both** recent and historical endpoints;
  all four archived request chains are complete. No other hourly event was
  substituted for these dates.
- Selected Polymarket BTC catalog closes have no UTC date of 2026-05-24.
  Selected weather closes have no UTC date of 2026-06-18 or 2026-09-30. These
  statements describe the captured catalog's scheduled-close dates, not proof
  that no event or trading activity ever existed on those days.
- Polymarket weather has two May 19 events: `493658`
  (`arch-highest-temperature-in-nyc-on-may-19-2026`) and `503590`
  (`highest-temperature-in-nyc-on-may-19-2026`). The latter's eleven conditions
  have recorded opening timestamps after their 2026-05-19 12:00 UTC scheduled
  close. All records remain in the archive. Count distinct calendar dates as
  well as event IDs, and flag the invalid catalog trading windows before replay.
- The Kalshi index cohort contains all 272 regular equity-session close dates
  in the window, plus `KXINX-26JAN19H1600`, which advertises a January 19 index
  outcome but actually closed early on Saturday, January 17 at
  17:52:48.426762 UTC. Four of its thirty contracts have nonzero catalog volume;
  this is not an extra regular equity session or an all-zero event. The source
  marks it finalized and supplies actual settlement timestamps. Catalog page
  SHA-256: `f8eb0c083edc733e7430c02cbba9a90eb6f89e8809f0ee9e375170a49ed0963a`.

The capture report now includes distinct scheduled-close dates, duplicate-event
date groups and daily-family gaps. It does not assume calendar-day trading for
the index family. The database report lists selected Polymarket conditions with
missing or reversed catalog trading windows. The follow-on replay must declare
their treatment before outcomes and preserve the original evidence; this data
capture makes no performance or promotion claim.

Primary sources checked 2026-09-30:

- [Kalshi historical markets](https://docs.kalshi.com/api-reference/historical/get-historical-markets)
- [Kalshi historical trades](https://docs.kalshi.com/api-reference/historical/get-historical-trades)
- [Polymarket Data API v2 OpenAPI](https://data-api.polymarket.com/v2/openapi.json)
- [Polymarket Gamma OpenAPI](https://docs.polymarket.com/api-spec/gamma-openapi.yaml)
- [Polymarket public analytics](https://docs.polymarket.com/market-data/public-analytics)

Monid discovery found paid aggregators for both venues. The existing official
SDK transports provide the needed public reads, so no paid dataset, account,
wallet, or new key is used.
