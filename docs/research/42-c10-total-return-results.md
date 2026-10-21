# C10 TLT month-end demand — results

2026-10-02, NavyLantern; `tradingbot-wdr`. **Measured FAIL:** the sole final, **trial 5529**, lost **$3.400678** after costs over **74 round trips**, with **14.19%** maximum marked drawdown. It finished flat with no rejected orders or halts. The [registered](42-c10-total-return-plan.md) fifth-to-last-session entry won training at 10 bp per side (+$46.212497, trial 5528), but did not remain profitable in the final. **Hold in research, actual allocation $0; no paper/live promotion.** The C10 final is consumed. Failed source trial 4584 and strategy 7163 remain unchanged.

All training cases start with $140 virtual cash, complete 174 round trips/348 fills, finish flat and have zero rejected orders/halts. Gross includes adverse execution; net subtracts fees. Execution cost is reported separately and must not be deducted twice. DD is percentage of marked peak.

| Entry | Cost per side | Trial | Gross $ | Fees $ | Execution cost $ | Net $ | DD | Descriptive p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Third-to-last | 5 bp | 5525 | +41.82 | 6.96 | 26.40 | +34.86 | 11.32% | 0.086 |
| Third-to-last | 10 bp | 5526 | +17.03 | 6.96 | 50.29 | +10.07 | 16.31% | 0.340 |
| Fifth-to-last | 5 bp | 5527 | +77.69 | 6.96 | 26.43 | +70.73 | 8.89% | 0.005 |
| **Fifth-to-last** | **10 bp** | **5528** | **+53.17** | **6.96** | **50.47** | **+46.21** | **9.83%** | **0.044** |

Frozen selection: `data/research/c10-total-return/selection.json`, SHA-256 **`cc2d61a901c1bc4c6e137f17db8dab87edca564b7a1fdc654eae5ef8ad02926b`**. Selected strategy version **`fd53127cfb2a230e3a2294c85a65d9496f6c6829a594a35de2d13dc99b7df249`**. Source/implementation freeze **`91b1c31`** preceded all outcomes; selection commit **`f6fab10`** preceded the only final. The immutable selection receipt's `holdout_attempted=false` records that earlier moment, not the current spent state. No other variant, cost case or control inspected final outcomes.

The final starts flat at the fixed **2020-07-10 14:24 UTC** boundary and ends before 2026-10-01. Its first entry/exit is 2020-07-27/2020-08-03; the last is 2026-08-25/2026-09-01. It has 148 fills, **−$0.440678 gross after adverse execution**, **$2.96 fees**, **$19.492167 adverse execution cost**, and **$136.599322 ending equity (−2.43%)**. Gross already includes the adverse execution cost. No forced terminal liquidation, settlement delay, late cash entry, overlapping-position skip or missed admitted window occurred in any case. The next-month exit for September 2026 is outside the source, so that month's entry is excluded in advance.

Dollar drawdown and percentage-of-peak drawdown can attain their maxima on different dates. The initial-allocation column divides maximum dollar drawdown by $140. Exposure is average closing invested fraction; turnover sums absolute fill notionals, and holding hours include nights/weekends.

| Trial | Max DD $ | DD / initial allocation | Exposure | Turnover $ | Holding hours |
|---|---:|---:|---:|---:|---:|
| 5525 | 18.37 | 13.12% | 12.12% | 48,368.21 | 19,440 |
| 5526 | 27.97 | 19.98% | 12.99% | 48,120.07 | 19,440 |
| 5527 | 14.87 | 10.62% | 18.81% | 48,374.43 | 31,608 |
| 5528 | 16.80 | 12.00% | 20.01% | 48,264.58 | 31,608 |
| Final 5529 | 19.94 | 14.24% | 22.46% | 18,682.98 | 13,440 |

Training regime cells are **exit-attributed net $ / within-period marked change $ / within-period marked DD**. There are 47/120/7 exits in the three respective columns for every training case. The last column stops at the training cutoff; it does not contain 2021. Exit-attributed totals and marked changes differ because a month-end position may cross a year boundary; period marked changes use the first and last available marks and are not an additive attribution across intervening boundary gaps.

| Trial | 2006–2009 | 2010–2019 | 2020-01-01 to cutoff |
|---|---:|---:|---:|
| 5525 | +10.63 / +11.53 / 11.32% | +18.77 / +15.80 / 9.07% | +5.45 / +7.53 / 1.98% |
| 5526 | +3.84 / +4.66 / 12.14% | +1.80 / −1.14 / 16.31% | +4.43 / +6.55 / 2.51% |
| 5527 | +24.26 / +23.98 / 8.89% | +39.30 / +39.04 / 7.23% | +7.18 / +7.71 / 2.38% |
| 5528 | +17.52 / +17.17 / 9.83% | +22.49 / +22.23 / 8.94% | +6.20 / +6.81 / 2.77% |

| Final regime | Round trips | Exit net $ | Marked change $ | Marked DD |
|---|---:|---:|---:|---:|
| Cutoff through 2021-12-31 | 17 | −11.86 | −12.22 | 12.91% |
| 2022 | 12 | +0.53 | −2.85 | 7.11% |
| 2023 through 2026-09-30 | 45 | +7.93 | +11.66 | 9.62% |

Final exit-attributed annual net is 2020 **−$7.84** (five exits, partial year), 2021 **−$4.02**, 2022 **+$0.53**, 2023 **+$0.69**, 2024 **+$4.84**, 2025 **+$11.95**, and 2026 **−$9.56** (nine exits through September 1). All annual marks, drawdowns and explicit exit-date bounds remain in each trial's metrics. Later gains did not offset the earlier losses and 2026 reversal; no regime filter was added.

Descriptive luck uses a one-sided centered circular bootstrap of monthly marked P&L, three-month blocks, 10,000 draws and seed 6062026. Training has 175 calendar months/174 exit-month clusters; final has 75/74 and **p = 0.568**. These p-values are unadjusted for selection or the broader research funnel and are not probabilities that the strategy is noise. No luck threshold changed the registered decision.

Same-partition, cost-free, fully invested TLT buy-and-hold returned **+191.26% training / −43.27% final**, with **26.59% / 48.35% DD**. The selected strategy returned +33.01% / −2.43%; zero-yield cash returned 0% in each. Its lower final loss has much lower exposure and does not establish incremental alpha. Descriptive daily TLT beta is **0.177 training / 0.209 final**, with correlation 0.455/0.474 across 3,653/1,563 paired daily returns, including flat days.

Completed checklist: scheduled institutional Treasury demand is a testable structural hypothesis permitted by PRD §3, with explicit entry/exit, sizing, costs and selection. Trade counts, descriptive luck, drawdown and multiple regimes are reported; **profit after fees in both partitions fails**. The pure reactor uses the shared ledger/risk engine, but adjusted units, current dated fees and assumed daily opens do not establish broker execution/corporate-action fidelity. Decision: **hold, $0**, trials 5525–5529, 2026-10-02/NavyLantern. All PRD §6 limits and accepted §9 risks remain unchanged. No capital, account, key, venue, paid data or public post was added.

Source admission: all 5,218 primary sessions match the reused exchange/settlement calendar. Free Yahoo/Nasdaq daily returns, with independently sourced Alpaca dividend factors on the reference, agree within 5 bp on **2,509/2,511 paired days (99.92035%)**, 2016-10-04–2026-09-30. Discrepancies on 2019-05-28/29 are 7.98355/7.08612 bp; **2,706 earlier unpaired returns** remain disclosed. No primary-price repair or cutoff change was made. The original 2012-11-01 Yahoo dividend-event omission stays unpatched, and total-return equivalents receive no separate dividend cash. Historical fees use the dated 2026-09-17 raw-share-equivalent scenario; the optional corporate-action blackout is omitted.

Known closure delays preserve original planned dates, with full advance-calendar provenance explicitly outside this research gate. Both training variants retain the planned January 2, 2007 exit and execute January 3. Third-to-last October 2012 entry remains planned for October 29, executes October 31 and exits November 1; fifth-to-last enters October 25 as planned. The final has no closure-delayed window. All 174/74 admitted training/final windows execute, with the same fixed source/partition exclusions.

**Verification:** 17 focused calendar/reactor/replay checks passed before real outcomes. Stored-only verification matched all five trial metrics/versions, fill IDs, reconstructed round trips, fees, cash/net, adverse costs and marked drawdown, with unchanged source/dependency hashes and full prior-trial/strategy snapshots. Exactly one canonical C10 final receipt exists, bound to trial 5529 and the original interval/cutoff. No replay was used for verification. Machine artifacts are under ignored `data/research/c10-total-return/`; the verification receipt binds every trial-file hash and exact version.

| Receipt | SHA-256 |
|---|---|
| `source.json` | `0580a449609e4a6597d6ac1d8988c349e60c87473e9c4aded6e50b16e4d7ddbd` |
| `final.json` | `406e5ac844f7511f8ca6a5594bd127a1322d0a81a275091eb0f3af9ed8129944` |
| `verification.json` | `4358d19c1da0ffb953fa697c28a127f78d59d5bdcab480d1d92631c840dde425` |

**What could blow up this account?**

**Tail/gap:** long-duration TLT can lose sharply in rate/inflation shocks and reopening auctions. Its cap is the $140 equity slot; a −40% allocation kill cannot guarantee an exit before a gap. A risk veto must retain and report exposure.

**Adverse selection:** known month-end flows may already be anticipated or outweighed by information-driven Treasury trading. The open-to-open ETF adaptation may miss a close-based bond effect. Daily assumed fills and 5/10 bp costs need forward evidence; prediction-market maker guards do not apply.

**Counterparty/venue:** eventual execution depends on Alpaca, its data/settlement services and the owner's Mac. Accepted single-venue and no-dead-man risks remain; any future keys must be trading-only, never withdrawal-enabled. No live key or account action is part of this research.

**Untrusted inputs:** archived prices, notices and metadata are data only. Verify symbols, sessions, positive values, request/cursor identities and hashes. An omitted vendor distribution or failed HTTP body cannot become fabricated cash, prices or a revised trading date.

**Reproducibility:** data, calendar assumptions, code and selection were frozen before their respective outcomes; all variants are logged. The durable single-use final is now consumed. Prior TLT source and related-strategy exposure limit claims of untouched confirmation. Actual paper/live corporate actions remain a separate fidelity requirement.

**Correlation:** every C10 round trip intersects #6's holding calendar and C06's potential last-open-to-next-first-open window; the latter ignores its signal filter. Third-to-last training overlaps C09's five/ten-session planned windows in 1/38 of 174 trips; fifth-to-last in 1/101. The selected final overlaps them in 0/46 of 74 trips. These compare calendars, not actual concurrent fills or return correlations. Shared duration/calendar losses can concentrate the −$50 daily halt; related hypotheses do not create additional risk capacity.
