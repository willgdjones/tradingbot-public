# C17 credit signal — results

2026-10-02, NavyLantern; `tradingbot-t87`. Actual allocation **$0**.

**Historical net-profit criterion met; hold in backtest, no funded promotion.** The sole final, trial **5587**, earned **+$45.485000** after modeled costs on $140 virtual cash (+32.49%), with **$48.288990 maximum marked drawdown: 33.15% of peak / 34.49% of initial cash**. It ended flat with zero rejected orders or halts. This result does not establish a protective credit signal: 2022 lost $42.12 on a marked basis, and SPY buy/hold returned more with a smaller peak drawdown over the final interval.

The [plan](43-c17-credit-signal-plan.md) records the unchanged 63/126-session rules, 4,716-session source audit and source/code freeze. SPY/IEF inputs and historical regimes were already familiar; this is diagnostic research, not pristine unseen confirmation. Hash-bound source inputs cost $0; the second source covers only 2016 onward. Earlier unmatched returns and all seven price disagreements remain in the archive.

## Four fixed training cases

Training ends before 2021-02-14T14:24:00Z. All cases ran once under commit `52d6cc0`, completed flat, and had zero rejected orders/halts.

| Lookback | Cost/side | Trial | Net $ | Fees $ | Adverse cost $ | Trips / fills | Drawdown $ / peak % / initial % |
|---|---|---:|---:|---:|---:|---:|---|
| 63 | 5 bp | 5583 | +156.260525 | 2.33 | 2.4560 | 16 / 97 | 35.1575 / 24.35% / 25.11% |
| 63 | 10 bp | 5584 | +153.922488 | 2.30 | 4.7607 | 16 / 96 | 35.2515 / 24.43% / 25.18% |
| 126 | 5 bp | 5585 | +161.793636 | 2.09 | 1.7708 | 11 / 85 | 22.1995 / 11.69% / 15.86% |
| 126 | 10 bp | 5586 | +160.150362 | 2.06 | 3.4345 | 11 / 84 | 22.3381 / 11.77% / 15.96% |

**Selected: 126 sessions at 10 bp**, trial **5586**, by highest positive complete 10 bp net. Exact trial/version/receipt was committed in **6a1db85** before final 5587. There was no parameter change, second final cost case or sibling final.

## Selected execution and final

| Metric | Selected training | Single final |
|---|---:|---:|
| Net after all modeled costs | +$160.150362 | +$45.485000 |
| Gross after adverse execution, before fees | $162.210362 | $46.185000 |
| Same-quantity P&L before fees and measured adverse costs | $165.644844 | $48.557434 |
| Round trips / fills | 11 / 84 | 9 / 32 |
| Turnover | $3338.83 | $2350.77 |
| Average marked equity exposure | 34.81% | 70.28% |
| Risk-on / risk-off monthly decisions | 85 / 66 | 52 / 9 |
| Risk-on to cash / cash to risk-on transitions | 10 / 11 | 8 / 8 |
| Cash months followed by a positive SPY month | 39 | 8 |
| Risk-on months followed by a negative SPY month | 21 | 22 |
| Total skip/clip observations | 47 | 61 |
| Cash-delay or sub-$1 buy-attempt skips | 0 | 8 |
| Terminal liquidation fills | 1 | 1 |
| Ending cash, including unsettled | $300.150362 | $185.485000 |
| Ending inventory / rejected orders / halts | 0 / 0 / 0 | 0 / 0 / 0 |
| Marked months / distinct exit-month clusters | 158 / 11 | 68 / 9 |
| Registered month-cluster luck p-value | null | null |

Final starts flat at the registered cutoff; actual source sessions begin 2021-02-16. Its first eligible signal is 2021-08-31 and first buy 2021-09-01 after partition-local warm-up. The last open, 2026-09-30, liquidates all remaining SPY. SPY is the only filled instrument; HYG/IEF are references. The eight delayed/small buy skips share one diagnostic reason, so the log does not distinguish pure settlement delay from a sub-$1 remaining allocation. Other final observations are six warm-up skips, 19 small reductions, 13 adverse-price cap clips and 15 sub-$1 pro-rata allocations.

Gross-before-costs above adds the measured costs back to the same executed quantities; it is not a separate zero-cost replay. Fees use the dated 2026-09-17 raw-share-equivalent schedule; slippage is 10 bp per side plus adverse raw-cent rounding. Adjusted prices include distributions without separate dividend cash. Historical fees, exact fractional opening fills and historic settlement mechanics are not claimed.

Both luck estimates are null because the preregistered minimum is 30 months **and 30 distinct exit-month clusters**; 84 or 32 fills are not independent samples. No luck threshold changes the net-profit criterion. The forward-month counts are descriptive false-exit/missed-rebound diagnostics, use next completed calendar-month closes, and exclude decisions lacking a next month; they are not selectable trials.

## Regimes and calendar years

Values are marked net dollars / maximum within-period drawdown as a percent of peak. They include open holdings; exit-attributed trade accounting is separately retained in each artifact. The training 2006–2009 label covers only the actual 2008–2009 source; final 2020–2021 covers only February–December 2021.

| Fixed regime | Selected training: net $ / drawdown | Final: net $ / drawdown |
|---|---:|---:|
| 2006-2009 | +36.2884 / 7.21% | Outside partition |
| 2010-2019 | +102.1746 / 11.77% | Outside partition |
| 2020-2021 | +21.6874 / 3.76% | +2.7862 / 4.88% |
| 2022 | Outside partition | -42.1192 / 32.12% |
| 2023-2026 | Outside partition | +84.8180 / 18.64% |

| Year | Selected training: net $ / drawdown | Final: net $ / drawdown |
|---|---:|---:|
| 2008 | +0.0000 / 0.00% | Outside partition |
| 2009 | +36.2884 / 7.21% | Outside partition |
| 2010 | -1.6325 / 11.77% | Outside partition |
| 2011 | +6.7818 / 5.57% | Outside partition |
| 2012 | +17.0484 / 3.96% | Outside partition |
| 2013 | +39.7537 / 3.69% | Outside partition |
| 2014 | +7.0683 / 3.42% | Outside partition |
| 2015 | -10.0429 / 6.84% | Outside partition |
| 2016 | +5.4852 / 2.65% | Outside partition |
| 2017 | +24.5555 / 1.60% | Outside partition |
| 2018 | +9.2630 / 5.40% | Outside partition |
| 2019 | +3.8941 / 1.82% | Outside partition |
| 2020 | +15.9235 / 3.76% | Outside partition |
| 2021 | +5.7639 / 1.92% | +2.7862 / 4.88% |
| 2022 | Outside partition | -42.1192 / 32.12% |
| 2023 | Outside partition | +23.7693 / 9.72% |
| 2024 | Outside partition | +29.3429 / 8.99% |
| 2025 | Outside partition | +10.0832 / 18.64% |
| 2026 | Outside partition | +21.6226 / 3.44% |

## Benchmarks and interpretation

| Completed-close diagnostic | Training return / peak drawdown | Final return / peak drawdown |
|---|---:|---:|
| SPY buy/hold, no costs | +253.18% / 51.87% | +109.88% / 24.50% |
| Cash, zero interest | 0% / 0% | 0% / 0% |
| Executed C17, return on initial $140 | +114.39% / 11.77% | +32.49% / 33.15% |

SPY buy/hold is a nonexecution comparison: full exposure, no warm-up/costs/slot cap, and fixed initial holdings. It is not an extra strategy trial. Lower C17 training exposure helped avoid the 2008 equity crash, but the final remained risk-on for 10 of 12 decisions in 2022. HYG minus IEF is not a duration-neutral credit spread: Treasury losses can leave the relative signal positive during falling equities. Final recovery in 2023–2026 generated $84.82 after the 2022 loss. This shows regime dependence and directional SPY exposure, not established credit forecasting power or independent alpha.

## Promotion checklist / what could blow up this account?

- **Edge and statistics:** a fixed cross-market risk-appetite hypothesis is implemented and the historical after-fee criterion is met. Only nine final round trips/exit-month clusters exist; the registered p-value is null. Drawdown and both good and bad regimes are shown. These observations do not prove a structural premium or robust protection.
- **Tail/gap risk:** peak-to-trough equity fell from $145.68 on 2021-11-22 to $97.39 on 2022-11-03. The low was 30.44% below initial cash, only $13.39 above the unchanged $84 permanent-kill boundary. The $48.29 drawdown is 34.49% of initial allocation and is not well clear of a 40% loss scale. Overnight gaps can cross the kill before liquidation; vetoes are not guaranteed stop prices. ETF exposure is capped at the $140 slot; the $25 cap applies to prediction markets.
- **Adverse selection/execution:** monthly next-open taker assumptions face opening spreads, gaps and bond/equity mark timing differences; 10 bp plus raw-cent rounding can understate stress. Prediction-market maker guards do not describe these fills. Actual fractional eligibility, opening fills, action records and sale-proceeds availability remain unverified in paper/live.
- **Counterparty/operations:** Alpaca, feed and Mac failures remain. Accepted no-dead-man/no-startup-reconciliation risks are unchanged; no new venue/account/key is introduced. Any future trading keys must be trade-only, never withdrawals.
- **Untrusted inputs/reproducibility:** external data remain data, never instructions. Source/raw files, 22 code dependencies, exact selection and immutable outcomes are hash-bound. The deterministic pure reactor and shared risk/ledger interface are tested. Source-return agreement is a quality screen with partial independent coverage, not proof of perfect daily adjustment factors. Final receipts forbid historical reruns or cosmetic-family recycling.
- **Correlation/account risk:** SPY is shared directional exposure with other equity sleeves. HYG and equities can fail together, and IEF-relative outperformance does not make a hedge. Concurrent multi-sleeve losses and the global −$50 daily halt were not jointly simulated. Worst final marked close-to-close day was −$7.88 for this isolated sleeve; it does not bound combined account loss.
- **Fidelity/limits:** same pure strategy interface, synthetic integration and source checks pass; forward paper and backtest-versus-broker/live fidelity are pending. Per-strategy −40%, global daily −$50, $140 ETF slot, 30-second stale-data and five-errors/minute limits are unchanged. No capital, subscription, keys, real order, public post or accepted-risk change.
- **Decision:** research complete; **hold in backtest, actual $0**. Positive historical net is recorded without adding a p-value/Sharpe gate. Paper fidelity and account-risk readiness are not demonstrated, so this research bead does not promote or activate trading. A later stage requires its own scoped checklist; the C17 final remains consumed.

## Verification and receipts

**41 focused checks pass.** Stored-only reconciliation verifies all five durable trials, artifact hashes, every fill being SPY, nonnegative/flat inventory, cash, fees, ledger net within database rounding, monthly marked totals, drawdown and highest eligible training selection. Exactly **one canonical C17 final receipt**, trial **5587**, exists. This verification did not replay prices or consume another final. Shared code, risk limits and other family finals were not changed.

- Source SHA-256: `24bd6879c9793e9d20772807bf93d31ed9c74cff7646dc378196e69d112b59ec`.
- Selection SHA-256: `ae2102bd61b482f2e79394fece987aa92abe2c4a7f2c63b785757da28db94851`.
- Selected/final version: `e82f93d1b3178ff06f1feedeaf74dbea0874eb9df3abd13bc84ed1bbc52f16ce`.
- Local immutable artifacts below live in `data/research/c17-total-return/`; all source identities and exception dates are pinned in the plan/source audit.

| File | SHA-256 |
|---|---|
| train-63-5.json | `32c4b932f808f9fcc604280700ac78852802edb059a046793d4a5c61c9761985` |
| train-63-10.json | `6337b61d8311ff3e1ec62875deec383065b06d92f132821208784373e8114ef2` |
| train-126-5.json | `1a58acbc52872ab445c6a600aa02810c714bca1eb88b78ab17d5e6c639bfea2a` |
| train-126-10.json | `998713db2f14e50ad685c7101e8b914f66ee5526bc68c40b9e187b29e97b973e` |
| final.json | `208e2e082d77047e364d51e2c87d0596db7afa2dbd0356b75421bbb842696d91` |
| training-stored-audit.json | `76d37a7cd6a44b649742462b927f692756e3777e562b3e2fe9002ef799dc871c` |
| complete-stored-audit.json | `2e7260ea0561fb5616e5c8ca5605c1248d482d19109e4cb2c2e18ee99e9cb13a` |
