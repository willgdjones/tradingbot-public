# Strategy #1 history capture — completion audit

Completed 2026-10-01 for `tradingbot-oma`. The frozen cohort covers scheduled closes from **2025-09-01 00:00 UTC through 2026-10-01 00:00 UTC**, exclusive end: thirteen calendar months. Selection was fixed before inspecting strategy returns. See the [capture plan](08-history-plan.md) and [machine-readable audit](08-history-capture.json).

All **35,762 expected request chains** are complete, with **zero missing or partial chains**. The audit checked 40,353 compressed Parquet pages. The selected instruments contain **10,149,700 stored trade rows**, exactly reconciling the three load passes. Every category has eligible tape observations in all thirteen selected calendar months.

The capture retains known catalog gaps, eleven invalid Polymarket trading windows, and two unverified token payouts belonging to one condition. These require declared treatment before the strategy replay. This report records data coverage and integrity; `tradingbot-yg2` owns returns, the locked holdout, drawdown, regime results and promotion review.

## Selected cohort

| Family | Selected events | Contracts | Scheduled UTC close dates | Zero-volume contracts not queried |
|---|---:|---:|---:|---:|
| Kalshi BTC 17:00 NY | 393 | 22,820 | 393 | 11,621 |
| Kalshi NYC weather | 395 | 2,370 | 395 | 3 |
| Kalshi S&P ranges | 273 | 8,190 | 273 | 4,474 |
| PM international BTC | 394 | 394 | 394 | 0 |
| PM international NYC weather | 394 | 3,610 | 393 | 0 |

There are 74,768 outcome instruments, exactly two per selected contract, with no missing instrument pairs or resolution timestamps. Zero-volume skips use an explicit final Kalshi catalog value of zero. They remain in the catalog and are separate from exhaustively queried empty feeds. All Polymarket conditions were queried, in batches of up to twenty.

Coverage counts are not independent statistical observations. Sibling strikes, the two projections of one Kalshi execution, duplicate events on a date, and the same underlying across venues are correlated. Scheduled-close dates and observed trade dates are separate measures.

## Completed source requests

| Source | Requests complete / expected | Empty complete requests | Raw records | Pages |
|---|---:|---:|---:|---:|
| kalshi / `markets_historical` | 397 / 397 | 63 | 48,804 | 427 |
| kalshi / `markets_recent` | 397 / 397 | 327 | 7,090 | 398 |
| polymarket_intl / `events` | 2 / 2 | 0 | 788 | 8 |
| polymarket_intl / `resolutions` | 201 / 201 | 0 | 4,004 | 201 |
| kalshi / `trades_historical` | 17,282 / 17,282 | 2,399 | 3,120,875 | 18,897 |
| kalshi / `trades_recent` | 17,282 / 17,282 | 14,529 | 712,744 | 17,668 |
| polymarket_intl / `trades_taker_history` | 201 / 201 | 0 | 2,657,334 | 2,754 |

Catalog records can include markets outside the selected window; normalization filters to the frozen cohort. Polymarket request counts are batch counts, so a nonempty batch does not imply every constituent condition has trades. Kalshi tape includes both recent and historical endpoints and the final seven days before scheduled close. Polymarket uses the documented condition-scoped, taker-only served feed; unsupported date filters were not assumed.

Five positive-volume Kalshi BTC contracts returned complete but empty tapes from both endpoints within the requested window: `KXBTC-26JUL2417-B72750`, `-B73250`, `-B73750`, `-B74250` (one contract of catalog volume each), and `KXBTC-26JUL3117-B75250` (120). The JSON retains their complete identifiers, source pages and response hashes. Their catalog volume is not converted into invented executions.

## Database coverage and execution identities

| Family | Stored rows | Execution identities | Eligible rows | Eligible identities | Trade-bearing events / contracts | Observed UTC trade days |
|---|---:|---:|---:|---:|---:|---:|
| Kalshi BTC 17:00 NY | 1,370,662 | 685,331 | 1,370,662 | 685,331 | 393 / 11,194 | 395 |
| Kalshi NYC weather | 5,699,496 | 2,849,748 | 5,699,496 | 2,849,748 | 395 / 2,367 | 397 |
| Kalshi S&P ranges | 422,208 | 211,104 | 422,208 | 211,104 | 273 / 3,716 | 373 |
| PM international BTC | 1,185,784 | 1,185,784 | 1,185,784 | 1,185,784 | 394 / 394 | 397 |
| PM international NYC weather | 1,471,550 | 1,471,550 | 1,471,550 | 1,471,550 | 394 / 3,610 | 398 |

Eligibility here is the source-level flag for supporting a later trade-through-price fill. Settlement verification, valid trading intervals, the strategy’s seven-day horizon, fees and risk rules still apply. Kalshi block trades are excluded from that flag. Polymarket mixed maker/taker activity and display prices cannot support these fills. There are zero duplicate instrument/execution identities and zero stored rows without an execution identity in the selected cohort.

Kalshi records one matched execution on both yes and no instruments. Polymarket uses conservative economic fingerprints where no venue trade ID or log index is supplied; indistinguishable repeats are collapsed. Its identity counts therefore describe retained observations and can understate underlying fills. Same-second Polymarket ordering cannot establish a later maker fill.

| Family | First observed trade (UTC) | Last observed trade (UTC) |
|---|---|---|
| Kalshi BTC 17:00 NY | 2025-09-01T04:01:03.182274Z | 2026-09-30T20:59:37.139228Z |
| Kalshi NYC weather | 2025-08-30T14:09:07.441204Z | 2026-09-30T04:54:50.480300Z |
| Kalshi S&P ranges | 2025-08-30T23:13:10.279077Z | 2026-09-30T19:59:34.055158Z |
| PM international BTC | 2025-08-29T15:15:47Z | 2026-09-30T16:19:30Z |
| PM international NYC weather | 2025-08-29T22:43:27Z | 2026-09-30T05:32:32Z |

### Monthly eligible tape coverage

Cells count eligible outcome rows. Per-month distinct event counts are retained in the JSON. Pre-close observations can precede the first selected close month.

| UTC trade month | Kalshi BTC | Kalshi NYC | Kalshi S&P | PM BTC | PM NYC |
|---|---:|---:|---:|---:|---:|
| 2025-08 | 0 | 2,444 | 6 | 403 | 90 |
| 2025-09 | 19,572 | 108,116 | 3,330 | 37,069 | 13,406 |
| 2025-10 | 21,794 | 213,380 | 6,882 | 85,097 | 22,487 |
| 2025-11 | 23,354 | 209,136 | 6,920 | 102,870 | 62,414 |
| 2025-12 | 37,204 | 366,076 | 11,654 | 95,549 | 38,949 |
| 2026-01 | 75,284 | 523,184 | 25,652 | 166,710 | 66,524 |
| 2026-02 | 185,708 | 552,222 | 39,632 | 201,916 | 142,603 |
| 2026-03 | 175,098 | 489,106 | 66,322 | 131,047 | 269,799 |
| 2026-04 | 129,796 | 504,006 | 70,286 | 77,417 | 259,559 |
| 2026-05 | 109,950 | 526,666 | 50,616 | 73,393 | 164,693 |
| 2026-06 | 117,382 | 586,930 | 47,044 | 69,923 | 115,272 |
| 2026-07 | 181,654 | 689,834 | 44,750 | 52,739 | 150,038 |
| 2026-08 | 151,950 | 464,192 | 33,334 | 51,243 | 92,785 |
| 2026-09 | 141,916 | 464,204 | 15,780 | 40,408 | 72,931 |

## Reconciliation and repeatability

| Pass | Trade rows inserted | Existing observations matched |
|---|---:|---:|
| Initial complete PM plus partial Kalshi load | 3,647,550 | 0 |
| Kalshi incremental snapshot | 3,709,802 | 990,216 |
| Remaining 5,302 Kalshi contracts | 2,792,348 | 174,872 |

The inserted-row sum is 10,149,700, equal to the independent physical row count. The full raw trade feeds normalize to 10,324,572 observations; 174,872 outcome observations repeat across the Kalshi endpoints and do not create additional stored rows. Source-group, category and monthly row totals reconcile.

| Full venue replay | Pages | Observations matched | Inserts / identity / reference / document changes | Finished UTC |
|---|---:|---:|---|---|
| Polymarket international | 2,963 | 2,657,334 | All zero | 2026-10-01T08:17:20.929468Z |
| Kalshi | 36,993 | 7,667,238 | All zero | 2026-10-01T12:50:16.470649Z |

The Kalshi replay ran after the final union load and recompression. Polymarket’s complete replay preceded the later Kalshi append; its selected rows were independently counted again after final recompression. The replays compare normalized fields and execution evidence against actual database rows, and validate archived checksums and exhausted request chains.

Focused validation passed: 15 capture/disk-budget checks, 7 cohort/storage checks and the loader/cohort checks covering exact UTC timestamp comparison. The real Timescale regression compresses 1,000 rows, adds 100 late rows, recompresses twice, and verifies fully compressed state, unchanged count and unchanged sum; its test objects roll back.

## Storage and policies

- Entire repository `data/` tree at the final budget check: **1.023 GB** (1,022,950,624 bytes), below the strict 20,000,000,000-byte ceiling.
- Free volume space: **106.059 GB** (106,059,444,224 bytes), above the 30,000,000,000-byte abort floor.
- Audited compressed source Parquet pages: **0.576 GB** (575,538,534 bytes). Manifests, state, directory allocation and other research also count toward the whole-tree budget.
- Whole database size at its report snapshot: **3.627 GB**. Its chunk inventory is 100 compressed and 2 rowstore chunks.
- Final manual pass rechecked all **100 chunks older than seven days**, including already-compressed chunks with late rowstore inserts. The post-pass catalog confirms fully compressed status for every eligible chunk.

| Whole hypertable | Current physical chunk bytes | Recorded bytes before compression | Recorded bytes after compression | Compressed / total chunks |
|---|---:|---:|---:|---:|
| `quotes` | 23,994,368 | 6,774,784 | 2,932,736 | 44 / 45 |
| `trades` | 3,280,052,224 | 12,796,149,760 | 1,236,393,984 | 56 / 57 |

Physical size uses `chunks_detailed_size`, including remaining rowstore/index storage. Compression statistics describe the recorded compression pass and can differ from current physical allocation. These whole-hypertable and database measurements include other research.

| Policy | Enabled | Configuration | Runs / failures | Next scheduled start |
|---|---|---|---:|---|
| `quotes` (1000) | True | `{"compress_after": "7 days", "hypertable_id": 9}` | 0 / 0 | 2026-10-01 20:33:56.30795-07 |
| `trades` (1001) | True | `{"compress_after": "7 days", "hypertable_id": 10}` | 0 / 0 | 2026-10-01 20:33:56.30795-07 |

The first scheduled policy run is still in the future at this audit; the manual compression and current storage state are verified. Capture/load retained the owner’s disk gates, guarded writes, resumable archives and per-page free-space checks throughout.

## Source limitations and handoff

- The expected Kalshi BTC events `KXBTC-25DEC2617` and `KXBTC-25DEC3117` returned empty complete catalogs from both endpoints. No alternate-hour event was substituted.
- Selected Polymarket scheduled-close dates omit BTC on 2026-05-24 and NYC weather on 2026-06-18 and 2026-09-30. These are gaps in the captured scheduled-close catalog, not proof that no event or trading activity existed.
- Polymarket weather has two events on May 19: `493658` and `503590`. The latter’s eleven conditions open after their recorded scheduled close. Retain the evidence, flag the invalid intervals, and avoid counting two events as two independent days.
- Kalshi index coverage includes all 272 regular equity-session close dates plus `KXINX-26JAN19H1600`, closed early on Saturday January 17. Four of its thirty contracts have nonzero catalog volume; its finalized settlement evidence is retained. Declare its treatment before the strategy replay.
- The two null payouts belong to condition `0xc43ed576db00fc6e4954b09376fd15bd77a100b9421df23cb26cf1d4bef660dd` (Bitcoin July 25, 2026). Gamma still reports a proposed resolution while the lifecycle endpoint reports resolved. The actual terminal timestamp is retained, but display prices and an oracle value do not independently certify both token payouts. Exclude these unverified labels from performance analysis.
- PM US has no documented public historical trade tape in this capture. International Polymarket remains research evidence; PM US display prices cannot fill makers. Applying PM US fees to another venue’s history is an explicit counterfactual.
- Preregister the treatment of chronology anomalies, eligibility and correlated observations before returns; tune only on the first 70% and consume the last 30% once per strategy version. Record every variant, including failures, and report costs, trade counts, drawdown, regimes and luck statistics. The six earlier strategy variants remain in the ledger.

No strategy-return analysis, holdout attempt, promotion, capital/account/key change or trading-risk-limit change was performed by this capture. PRD §6 remains unchanged. Original evidence and source hashes for the chronology and payout findings are in the capture plan.

## Audit identity

- Frozen cohort SHA-256: `35c64518ea06b437e6c4a614d43f1650333ac5e9c66da7800825e7b7700be0d9`.
- Final verification code revision: `32728b1771f558b72cd7b4c4fc2764adfefa77c3`.
- Report verified at: `2026-10-01T13:28:33.184227+00:00`.
- The JSON includes full coverage tables, row and policy evidence, replay receipts, source artifact paths and SHA-256 hashes. Bulk source/state artifacts remain local under `data/history/longshot-20260930/` and the immutable raw archive tree.
