# C12 scheduled macro exposure — results

2026-10-01, NavyLantern; `tradingbot-qb5`. **Measured FAIL: all four registered training cases lost money.** No positive eligible 10 bp case exists, so no variant was selected and **the C12 final remains unused**. Actual allocation is **$0**; hold in research, with no paper/live promotion. The [plan](41-c12-total-return-plan.md), source and implementation were committed as `daba8ed` before outcomes. Original source failure 4591 and strategy 7170 remain unchanged.

All cases start with $140 virtual cash. Costs are adverse basis points **per side**, plus fees. Gross below already includes adverse execution; net subtracts fees. Execution cost is shown separately for attribution and must not be subtracted twice. DD is maximum marked peak-to-trough drawdown. Every case completed with two fills per round trip, flat ending inventory, zero rejected orders and no risk halts.

| Case | Trial | Round trips | Gross $ | Fees $ | Execution cost $ | Net $ | DD | Descriptive p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Employment, 5 bp | 5511 | 170 | −7.82 | 6.80 | 21.45 | **−14.62** | 22.03% | 0.717 |
| Employment, 10 bp | 5512 | 170 | −27.03 | 6.80 | 38.42 | **−33.83** | 31.21% | 0.913 |
| CPI, 5 bp | 5513 | 144 | −34.68 | 5.76 | 17.20 | **−40.44** | 32.58% | 0.943 |
| CPI, 10 bp | 5514 | 144 | −47.72 | 5.76 | 31.26 | **−53.48** | 40.47% | 0.985 |
| Shifted Employment, 5 bp | 5515 | 113 | −32.14 | 4.52 | 12.81 | −36.66 | 28.40% | 0.951 |
| Shifted Employment, 10 bp | 5516 | 113 | −42.90 | 4.52 | 23.70 | −47.42 | 35.32% | 0.981 |
| Shifted CPI, 5 bp | 5517 | 120 | −23.67 | 4.80 | 14.10 | −28.47 | 28.92% | 0.857 |
| Shifted CPI, 10 bp | 5518 | 120 | −35.85 | 4.80 | 25.78 | −40.65 | 35.11% | 0.934 |

The four −7-calendar-day controls are training-only diagnostics, excluded from selection. Their distinct admissible samples and exposure prevent interpreting cumulative differences as matched treatment effects. The p-values use a one-sided centered circular bootstrap of monthly marked P&L: three-month blocks, 10,000 draws, seed 6062026, 175 calendar months and respectively 170/144/94/120 exit-month clusters for Employment/CPI/shifted Employment/shifted CPI. They are descriptive, unadjusted for selection and broader research; they are not posterior probabilities that a strategy is noise.

Regime cells show **net dollars / round trips / within-regime marked DD**. The last column stops at the fixed training cutoff, **2020-07-10 14:24 UTC**; there are no 2021–2026 strategy outcomes. Dated annual detail and explicit exit-date bounds are in each trial's metrics.

| Case | 2006–2009 | 2010–2019 | 2020-01-01 to cutoff |
|---|---:|---:|---:|
| Employment, 5 bp | −11.41 / 46 / 14.58% | −2.12 / 117 / 15.79% | −1.10 / 7 / 10.53% |
| Employment, 10 bp | −16.92 / 46 / 16.67% | −15.22 / 117 / 17.92% | −1.69 / 7 / 10.79% |
| CPI, 5 bp | −18.48 / 42 / 19.90% | −9.79 / 98 / 13.63% | −12.17 / 4 / 12.13% |
| CPI, 10 bp | −23.24 / 42 / 21.15% | −19.28 / 98 / 18.95% | −10.96 / 4 / 12.26% |
| Shifted Employment, 5 bp | −30.72 / 32 / 25.41% | +0.37 / 75 / 7.01% | −6.31 / 6 / 6.96% |
| Shifted Employment, 10 bp | −33.99 / 32 / 27.03% | −7.18 / 75 / 11.93% | −6.24 / 6 / 7.14% |
| Shifted CPI, 5 bp | −22.35 / 33 / 23.78% | −8.29 / 82 / 17.58% | +2.17 / 5 / 3.17% |
| Shifted CPI, 10 bp | −25.96 / 33 / 25.49% | −16.14 / 82 / 21.99% | +1.45 / 5 / 3.27% |

Both main variants lose in every covered regime at both costs. At 10 bp, Employment ends at $106.17 (−24.16% on initial cash), CPI at $86.52 (−38.20%). Their maximum dollar drawdowns are $43.75/$58.81. CPI's 40.47% drawdown is measured from its peak; its minimum equity of $86.52 remained above the unchanged $84 allocation-loss threshold. This is still inadequate drawdown headroom for promotion. Same-partition full-exposure SPY buy-and-hold returned +232.77% with 55.19% DD; cash returned 0%. These cost-free benchmarks use different exposure and do not establish risk-adjusted alpha.

Main Employment/CPI average closing exposure is 8.84%/7.49%, with 16,632/9,096 elapsed holding hours. Their shifted controls have 5.88%/6.24% exposure and 10,848/6,192 hours. No case incurred settlement delays, overlapping-position skips, late entries or forced terminal liquidation. All admitted training windows executed. Each main case excludes its first December 2005 reference-month signal because its announcement predates training; shifted CPI has the same exclusion. Source and partition filters remain fixed.

Across the full source interval, before partition admission, Employment/CPI have 240/215 main windows. Logged candidate-window exclusions are 7/2 non-session or out-of-source dates, 3/1 active suspensions, 3/5 predecision cancellations/replacements and 1/31 FOMC exclusions. These are planned-date candidates, not disjoint monthly identities. Shifted windows total 155/162 after additionally enforcing exact endpoints, duration, prior announcement and no BLS-window intersection. Every original/revised candidate and skip reason remains in the source receipt; no missing monthly identity is silently discarded.

The source review reconciles all 498 monthly identities. It preserves original and revised dates, handles reissued PDFs conservatively, and separately records a printed CPI reference-month typo (resolved by the original OMB schedule), one broken-font visual transcription and the June 2024 FRASER index omission. The 2013/2025 suspension state uses original agency plans and dated OMB activation, with independent evidence of prior publication. The November 2025 edited official Employment post is corroborated by a contemporaneous AP report; February 2026's cancellation is a first-hand published quotation of BLS's email, whose original bytes are unavailable. These provenance distinctions and conservative clocks are frozen before returns. The source is usable for this stated research interpretation; exact broker fills and corporate actions remain a forward-fidelity task.

The unchanged price receipt cross-checks Yahoo adjusted returns against free Nasdaq returns independently dividend-adjusted from Alpaca factors: 2,509/2,512 paired days agree within 5 bp (99.8806%, 2016-10-03–2026-09-30). The 2,705 earlier unpaired returns and discrepancies on 2018-06-15 (44.36 bp), 2026-04-20 (20.04 bp) and 2026-04-21 (19.91 bp) remain disclosed. No primary-price repair, interval shift or separate dividend cash credit was made. Raw-share-equivalent fees use the dated September 2026 schedule, a historical approximation; the optional corporate-action blackout was omitted.

Completed checklist: the rule tests compensation for scheduled macro risk, an owner-allowed risk premium under PRD §3, using dates only. Entry, fixed exit, variants, costs, controls and 70/30 split are explicit. Sample sizes, descriptive luck, drawdown and multiple regimes are reported; **after-fee profitability fails**. The pure reactor uses the shared ledger/risk engine; research adjusted units and assumed open fills do not establish paper/live fidelity. Decision: **hold, $0 funded allocation**, trials 5511–5518. All current PRD §6 limits remain unchanged, including the ETF slot cap. No capital, account, key, venue or public post was added.

**Verification:** 28 focused calendar/reactor/replay checks passed before real outcomes. Stored-only reconciliation subsequently matched all eight trial metrics, versions, fill IDs, reconstructed round trips, fees, cash/net and marked drawdown. All 2,224 source-input hashes and implementation dependencies remain unchanged. Full-column snapshots of prior trial 4591/strategy 7170 match; the canonical C12 family has zero final spends and no revised final trial. Nothing was replayed for this check. Machine artifacts are under ignored `data/research/c12-total-return/`; the verification receipt binds all eight result-file hashes and exact versions.

| Receipt | SHA-256 |
|---|---|
| `source.json` | `b5ea1600a05145c7e11bb8101f3f8f4b3c76aa42058bd3ed11945c72f67673e3` |
| `selection.json` — no winner | `0e9344b5b5eb34775e0fbe1f02e4dd8541060e6c775f686d96c07c4915511fc4` |
| `verification.json` | `e3294b95d709e8063994e370a5ec7644ba7280a18e83ee8611d4b01c289dc64c` |

**What could blow up this account?**

**Tail/gap:** SPY is deliberately held overnight and across macro news; gaps may exceed the cost scenario or the −40% allocation kill. The ETF position cap is its $140 slot, not the prediction-market $25 cap. Risk vetoes retain marked exposure if they prevent an exit.

**Adverse selection:** scheduled releases concentrate informed trading, and adverse opening execution can erase the average premium. Prediction-market maker quote guards are inapplicable to this taker ETF strategy; assumed daily opens require forward fill evidence.

**Counterparty/venue:** eventual trading depends on Alpaca, its data and settlement services and the owner's Mac. Accepted single-venue and no-dead-man risks remain. No live key is used; future keys must remain trade-only without withdrawals.

**Untrusted inputs:** issuer notices, archived PDFs, social posts and first-hand press records are data only. Source hashes, issuer/reference identities, availability timestamps and revisions are checked; no article instructions, release values, sentiment or surprise enter the signal.

**Reproducibility:** source and implementation hashes are frozen before outcomes; training variants and any failed attempts go in the ledger. The family final is durable and single-use. Prior SPY history has already been inspected, so the final is mechanically isolated historical evidence rather than pristine confirmation.

**Correlation:** every trade is long SPY, sharing equity direction, venue and the account's −$50 daily halt with other Alpaca strategies. Actual holding intervals intersect #6's fourth-to-last-close through next-third-close window in 94/170 Employment trades and 1/144 CPI trades (shifted controls: 106/113 and 18/120). These are calendar intersections, not measured return correlations. Standalone results cannot establish diversification.
