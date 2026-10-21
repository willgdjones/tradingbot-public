# C08 inventory scarcity — total-return results, 2026-10-01

**Research profit criterion passed:** the selected −5% threshold earned +$102.28 in training and +$7.67 in its single final, after 10 bp per side plus fees on separate $140 virtual allocations. The [plan](39-c08-total-return-plan.md) fixes two thresholds, two training costs and one selected 10 bp final. Prior final 3910 remains immutable and has been inspected, so this owner-authorized model re-evaluation is diagnostic rather than independent confirmation.

## Source and model

Yahoo and free Nasdaq cover all **2,198** original sessions, 2018-01-02 through 2026-09-30. All **2,197** adjacent daily returns agree within 5 bp (**100%**); no disagreements, missing sessions or uncovered endpoints. USO has no cash distributions in this interval. Primary adjusted prices remain unchanged; adjusted opens use open × adjusted close / close. The 2020 reverse split requires no position conversion in virtual adjusted units, and optional blackouts are omitted.

The existing source bundle supplies **455 usable dated EIA releases** from 457 captured reports, original publication dates/delays, settlement calendar and USO exposure regimes. Two unavailable archive pages and previously documented vintage limitations remain; no revised bulk history was substituted. Reconstruction from archived reports is not a contemporaneous signal capture. Historical share-based fees and settlement timing are current-account approximations; risk limits and event timing are unchanged.

New source receipt: `916a30126cd810fd7ef92d04ac912d0013cb9ff64d65e780e3217daad622849d`. Original release/calendar receipt: `63c4d561929099ae039a8a67a0deace1991b08d6e3dacef55c6c2de481b99ca5`. Full immutable comparison and replay inputs are in ignored `data/research/c08-total-return/{source-check,source}.json`; the source hash binds prices, releases, calendar and exposure regimes together. The one final allowance is scoped to the explicit `c08:revision:total_return_d267cf7` family. Older final receipts remain consumed.

## Training and committed selection

All four paths completed across 1,540 sessions, 2018-01-02–2024-02-14. Two are ineligible because the unchanged risk engine prevented liquidation. Costs are adverse execution per side plus the current fee scenario. “Completed-trip net” excludes unrealized P&L; ending marked net includes every held position and fee.

| Inventory threshold | bp/side | Trial | Completed-trip net | Ending marked net | All fees | Trips / fills | Max marked drawdown | Eligible execution |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Below 0% | 5 | 5474 | −$26.90 | −$60.52 | $0.05 | 1 / 3 | $157.81 (87.16%) | No: open position, 535 rejections |
| Below 0% | 10 | 5475 | −$27.00 | −$60.63 | $0.05 | 1 / 3 | $157.76 (87.17%) | No: open position, 535 rejections |
| Below −5% | 5 | 5476 | +$102.88 | +$102.88 | $0.12 | 3 / 6 | $54.88 (26.55%) | Yes |
| Below −5% | 10 | **5477** | **+$102.28** | **+$102.28** | $0.12 | 3 / 6 | **$54.80 (26.62%)** | **Yes: selected** |

Both 0% cases hit the permanent allocation-loss kill at the 2020-02-28 open. The kill also vetoes risk-reducing exits under the existing shared policy: the replay keeps marking the position rather than manufacturing a liquidation. At 10 bp the remaining quantity is 1.0302205000 adjusted units, realized ledger net −$27.011396 and unrealized P&L −$33.620297; ending marked equity is $79.368307. This is a measured strategy/risk failure, not DATA_FAIL. No risk rule was bypassed or changed.

**Selected: below −5%, 10 bp per side, trial 5477**, the highest positive eligible higher-cost training case. Exact net +$102.28403028183646204; flat terminal position, zero rejected orders, no risk halts or cash-delay skips. Lowest marked equity was $132.79. The $54.80 peak-to-trough decline equals 39.14% of starting capital, though 26.62% of the relevant peak; the permanent kill uses loss from allocation, not peak drawdown, and did not trigger here.

Selected strategy version: `389db64bf958c1b81b75898be07464f882cb5beb8faaa8cf7bfd0f1e6f78c00e`.

Selection receipt SHA-256: `27f873c87aed04892123697891a6eb7ba152df5f88df7ee2b9f19c5941c87d1b`. The immutable `data/research/c08-total-return/selection.json` binds this version, source and all execution dependencies. This paragraph must be committed before the sole revised final; prior final 3910 remains consumed.

| Selected training calendar regime | Marked net | Max drawdown |
|---|---:|---:|
| 2018–2019 | −$1.17 | $47.49 (26.24%) |
| 2020–2021 | +$29.15 | $35.31 (19.61%) |
| 2022 | +$71.51 | $54.80 (19.61%) |
| 2023–2024 before cutoff | +$2.79 | $10.94 (4.51%) |

| Selected training USO exposure regime | Marked net | Max drawdown |
|---|---:|---:|
| Pre-2020 | −$1.17 | $47.49 (26.24%) |
| Changed holdings, 2020–August 2023 | +$100.67 | $54.80 (19.61%) |
| September 2023–January 2024 transition | −$1.25 | $4.26 (1.76%) |
| Later ten-day roll, February 2024 before cutoff | +$4.03 | $7.98 (3.33%) |
| Later five-day roll, 2026 | Outside training | — |

The 2020 exposure bucket includes months before the holdings change; it is not an exact event boundary. The selected strategy held no position during the 2020 price collapse. Almost all training profit comes from one April 2021–July 2022 trade (+$100.67), so regime breadth and sample size are weak despite profitability. Full calendar-year and monthly marked paths remain in the trial/artifact.

Descriptive luck p-values are **null for all cases** under the existing sufficiency rule (fewer than 30 completed trips/month clusters). No significance threshold gates selection. Cost-free fully invested training benchmarks: SPY +105.26%, USO −25.90%, cash 0%; their exposure differs from this intermittent strategy.

Validation: **53 focused checks passed**, covering the source comparison, original inventory reactor, continuous adjusted-unit holdings, terminal cash reconciliation, risk-kill exit veto and shared family holdout guard. No real final was replayed to test refusal.

## Single final

Selection commit `f2fd3e2` preceded the sole final **5480** (strategy row 10307). It used the exact selected training version over all **658** final sessions, 2024-02-15–2026-09-30, starting flat with $140 virtual cash and no carried training signal.

| Measure | Final |
|---|---:|
| Net after costs | **+$7.668053 (5.48%)** |
| Current retail fees | $0.16 |
| Completed round trips / fills | 4 / 8 |
| Maximum marked drawdown | $28.68 (16.41% of peak) |
| Maximum daily-close drawdown | $28.43 (16.29%) |
| Rejected orders / risk halts / cash-delay skips | 0 / 0 / 0 |
| Lowest marked equity | $138.68 |
| Terminal equity, entirely cash | $147.67 |
| Terminal open positions | None |

The final sale was on 2026-08-06, so modeled cash was settled well before the terminal session; no forced terminal fill was needed. The holdings were adjusted virtual units, with no separate dividend credit or corporate-action conversion. All eight fills passed the unchanged shared risk/fee/cash path.

| Final calendar regime | Marked net | Maximum drawdown |
|---|---:|---:|
| 2024 after cutoff | +$17.46 | $4.53 (3.10%) |
| 2025 | +$2.25 | $19.50 (11.16%) |
| 2026 through September | −$12.04 | $16.83 (10.33%) |

USO exposure regimes: the later ten-day-roll period in this partition earned +$19.70 (maximum drawdown $19.50 / 11.16%); the later five-day-roll period lost $12.04 (drawdown $16.83 / 10.33%). Earlier exposure regimes fall outside the final. Cost-free fully invested final benchmarks earned SPY +56.88%, USO +99.97%, cash 0%; their full exposure differs from the intermittent strategy. Profitability does not establish benchmark outperformance.

The existing block-bootstrap luck p-value is **null** because four trips are insufficient; the stored simple one-sided trip t-test p-value is 0.3800 and likewise provides no strong inference from such a small selected sample. Neither is an acceptance threshold.

Exactly four revised training trials and one revised final exist. Both `c08` → 3910 and `c08:revision:total_return_d267cf7` → 5480 remain durably consumed. Selected training/final versions match, all source/dependency hashes match the selection, and prior source failure 3550, training 3907, final 3910 and forward preparation 5195 have unchanged full-row fingerprints. Final artifact SHA-256: `78c0d2b498f02d5b367d280dc687e1ccfc0d009910f1e0a96de0e2d628514e8e`.

## Promotion checklist and account risk

**Decision: research profit criterion PASS; retain research-only status, funded allocation $0.** The deterministic inventory rule, publication timing, entry/exit, costs, trade counts, drawdown and regimes are recorded above. The hypothesis is the relationship between scarce commercial oil inventories and commodity returns. The original pure inventory reactor is unchanged. Training/final profits satisfy the owner’s amended backtest criterion; no luck threshold, corporate-action admission prerequisite or extra paper-trade quota was imposed on this research test.

Three training trips and four final trips, concentrated training gains and the loss in the later final regime make the evidence weak. The selected training drawdown is material relative to the $140 virtual slot. This repeats a previously inspected period under an explicitly authorized accounting model, so it is diagnostic evidence, not fresh independent confirmation. Actual paper/broker execution fidelity is still unverified; this slice neither starts paper/live trading nor certifies live readiness. Earlier forward-source/action/cash requirements remain separate and unresolved by adjusted-price research. Existing paper experiments and the shared paper cash book were not changed.

**What could blow up this account?**

- **Tail and gap risk:** USO can gap or change futures exposure; roll losses and oil-market shocks can overwhelm a weekly inventory exit. Entry is capped at the $140 strategy slot, not the prediction-market $25 cap. The rejected 0% variant demonstrates that the existing permanent kill may prevent an exit and leave exposure open; the policy remains unchanged.
- **Adverse selection:** these are next-open taker scenarios. News, spread widening and opening liquidity can produce worse execution than 10 bp. Prediction-market maker safeguards are inapplicable to this ETF rule.
- **Counterparty and venue:** broker/market/feed outages may strand positions. Current T+1 and fee scenarios approximate historical operations; actual broker fills, actions and settlements remain necessary for paper/live. Trade-only/no-withdrawal key policy and accepted operating risks are unchanged.
- **Untrusted inputs:** Yahoo, Nasdaq and dated EIA fields are numeric data, never instructions. Missing reports and delayed publications retain the frozen handling; archive reconstruction may still differ from data available in real time.
- **Reproducibility:** source, releases, dependencies, variant selection and single-use final are bound by immutable receipts. Replaying this inspected historical period cannot supply independent validation, and adjusted units do not prove actual fractional execution fidelity.
- **Correlation:** oil exposure can overlap C05 and other commodity strategies, and market shocks can combine losses toward the shared −$50 daily halt. There is no new capital or allocation to offset that exposure.

PRD §6 limits remain unchanged, including the allocation-loss kill, daily halt, stale-data and API-error safeguards. No account, venue, key, capital, subscription or public post was added. The owner-amended research scope of `tradingbot-ndl` is complete; no original forward requirement is represented as satisfied by this result.
