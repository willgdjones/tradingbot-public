# C19 correlation-conditioned hedge — results

2026-10-02, NavyLantern; `tradingbot-n7j`. Actual allocation **$0**.

**Historical after-fee profit criterion met.** The sole final, trial **5646**, earned **+$81.704996** on $140 virtual cash (**+58.36%**) with **$30.025233 marked drawdown: 19.28% of peak / 21.45% of initial cash**. It completed flat with zero rejected orders or halts. This is a positive historical execution result; it does not establish an advantage over fixed hedges or broker/paper fidelity. No funded promotion or live activation occurs.

The [plan](43-c19-correlation-hedge-plan.md) contains the unchanged Pearson-correlation rule, source/code freeze and exact selection. All SPY/IEF/GLD history overlaps previous C03 research and familiar market regimes; the result is diagnostic, not pristine unseen confirmation. Primary coverage is 5,218 sessions per fund with 27 hash-bound inputs. SPY/IEF/GLD paired-return agreement is 99.880573% / 100% / 99.037037%; all 29 disagreements and unmatched pre-2016 dates remain in the source. No history, ticker, price, threshold or rule was changed to rescue an outcome.

## Four fixed training cases

All cases completed positive and flat with zero rejected orders/halts. The 22-dependency map remained identical to freeze `1963400`; trials 5642–5644 record that commit, and trial 5645 records unrelated C16 claim/log commit `0af26b5`. Training strictly precedes 2020-07-10T14:24:00Z.

| Lookback | Cost/side | Trial | Net $ | Fees $ | Adverse cost $ | Trips / fills | Drawdown $ / peak % / initial % |
|---|---|---:|---:|---:|---:|---:|---|
| 63 | 5 bp | 5642 | +134.769251 | 4.14 | 1.3071 | 13 / 220 | 38.5335 / 24.23% / 27.52% |
| 63 | 10 bp | 5643 | +133.563008 | 4.18 | 2.4359 | 13 / 222 | 38.5807 / 24.32% / 27.56% |
| 126 | 5 bp | 5644 | +143.596335 | 4.06 | 0.6796 | 5 / 214 | 38.9858 / 24.03% / 27.85% |
| 126 | 10 bp | 5645 | +143.026601 | 4.09 | 1.2725 | 5 / 214 | 38.9939 / 24.06% / 27.85% |

**Selected: 126 sessions at 10 bp**, trial **5645**, solely by highest positive complete 10 bp net. The exact selected trial/version/receipt was committed in **1a1e833** before final 5646. There was no additional parameter, second-cost final or sibling-family retry.

## Selected execution and final

| Metric | Selected training | Single final |
|---|---:|---:|
| Net after all modeled costs | +$143.026601 | +$81.704996 |
| Gross after adverse execution, before fees | $147.116601 | $83.454996 |
| Same-quantity P&L before measured adverse costs and fees | $148.389111 | $85.223044 |
| Fees / measured adverse costs | $4.09 / $1.2725 | $1.75 / $1.7680 |
| Round trips / fills | 5 / 214 | 11 / 102 |
| Turnover | $1211.03 | $1712.92 |
| Average marked equity exposure | 68.84% | 74.20% |
| Monthly IEF / GLD / warm-up cash targets | 158 / 10 / 6 | 32 / 36 / 6 |
| Hedge switches, excluding initial cash | 3 | 9 |
| Skip/clip observations | 325 | 155 |
| Cash-delay or sub-$1 buy-attempt skips | 51 | 50 |
| Terminal liquidation fills | 2 | 2 |
| Ending cash including unsettled proceeds | $283.026601 | $221.704996 |
| Ending inventory / rejected orders / halts | 0 / 0 / 0 | 0 / 0 / 0 |
| Marked months / distinct exit-month clusters | 175 / 4 | 75 / 10 |
| Registered month-cluster luck p-value | null | null |

Final begins with the 2020-07-10 close after the intraday cutoff, flat with no training observations carried over. Its first valid decision is 2021-01-29; the first buys occur 2021-02-01. The last open, 2026-09-30, liquidates both remaining funds. Monthly weights freeze half of min(95% decision equity, $140) in SPY and half in IEF or GLD, with no daily retargeting. Reductions precede additions, sale proceeds wait for settlement, and every saved buy respects its full adverse-price target and frozen reserve.

The final has six warm-up skips, 32 sub-$1 reductions, 26 sub-$1 pro-rata allocations, 41 adverse-price full-target clips and 50 buy skips labelled cash delay or sub-$1 allocation. The last category does not distinguish pure settlement delay from a small remaining allocation. The independent stored-fill cash audit found minimum settled cash $6.57 in final and $6.33 in selected training; reserves are frozen per decision and vary with equity.

Gross-before-costs adds measured costs back to the same executed quantities; it is not another zero-cost replay. Slippage is 10 bp per side plus adverse raw-cent rounding, and fees use the dated 2026-09-17 raw-share-equivalent schedule. Adjusted prices include dividends without duplicate cash credits. Actual fractional opening fills, historical fees and historical settlement mechanics are not claimed.

The registered three-month block-bootstrap p-value is null: the minimum is 30 months **and 30 distinct exit-month clusters**, while selected training/final have only 4/10 clusters. Two terminal legs on the same day and repeated monthly rebalances are not independent samples. No p-value, Sharpe or benchmark threshold replaces the owner’s after-fee profit criterion.

## Marked regimes and years

Each cell is marked net dollars / maximum within-period drawdown as a percent of peak. Open holdings are included; exit-attributed round-trip totals remain separately in each artifact. The 2020–2021 training row ends July 2020, while its final counterpart starts July 2020. Neither partition inherits the other’s position or warm-up.

| Fixed regime | Selected training: net $ / drawdown | Final: net $ / drawdown |
|---|---:|---:|
| 2006-2009 | +15.3561 / 24.06% | Outside partition |
| 2010-2019 | +119.0371 / 4.83% | Outside partition |
| 2020-2021 | +8.6334 / 7.74% | +14.9686 / 4.35% |
| 2022 | Outside partition | -17.1019 / 18.89% |
| 2023-2026 | Outside partition | +83.8383 / 5.90% |

| Year | Selected training: net $ / drawdown | Final: net $ / drawdown |
|---|---:|---:|
| 2006 | +8.3242 / 4.64% | Outside partition |
| 2007 | +12.1474 / 4.07% | Outside partition |
| 2008 | -18.1044 / 20.95% | Outside partition |
| 2009 | +12.9888 / 14.27% | Outside partition |
| 2010 | +17.1449 / 4.27% | Outside partition |
| 2011 | +12.1073 / 4.83% | Outside partition |
| 2012 | +13.2047 / 2.32% | Outside partition |
| 2013 | +11.1375 / 3.72% | Outside partition |
| 2014 | +15.3222 / 1.87% | Outside partition |
| 2015 | +2.4350 / 3.68% | Outside partition |
| 2016 | +8.8587 / 2.09% | Outside partition |
| 2017 | +15.5054 / 0.88% | Outside partition |
| 2018 | -1.9244 / 4.68% | Outside partition |
| 2019 | +25.2459 / 1.03% | Outside partition |
| 2020 | +8.6334 / 7.74% | +0.0000 / 0.00% |
| 2021 | Outside partition | +14.9686 / 4.35% |
| 2022 | Outside partition | -17.1019 / 18.89% |
| 2023 | Outside partition | +26.2467 / 5.90% |
| 2024 | Outside partition | +35.2673 / 4.89% |
| 2025 | Outside partition | +21.7556 / 4.92% |
| 2026 | Outside partition | +0.5687 / 5.27% |

## Fixed benchmark comparison

| Completed-close diagnostic | Training return / peak drawdown | Final return / peak drawdown |
|---|---:|---:|
| Initial 50/50 SPY/IEF | +173.48% / 21.12% | +73.70% / 21.53% |
| Initial 50/50 SPY/GLD | +226.05% / 31.52% | +143.25% / 18.85% |
| SPY buy/hold | +232.77% / 55.19% | +161.40% / 24.50% |
| Cash, no interest | 0% / 0% | 0% / 0% |
| Executed C19, return on initial $140 | +102.16% / 24.06% | +58.36% / 19.28% |

Benchmarks hold their initial quantities; their weights drift, with no monthly rebalancing, hindsight hedge choice, costs, warm-up or $140 target cap. They are nonexecution diagnostics, not additional selectable strategies. Both fixed 50/50 portfolios returned more than C19 in both partitions. C19 final drawdown was lower than SPY/IEF but slightly higher than SPY/GLD. Different exposure, reserve/cap and trading assumptions prevent treating this as an isolated causal test of the correlation rule’s added value.

All three covered broad training regimes were positive. The final lost **$17.10 in 2022**, then made **$83.84 in 2023–2026**; 2026 through September added only $0.57 on a marked basis even though closing long-held positions attributed much more realized profit to that year. The final had 36 gold-target and 32 bond-target months versus 10/158 in training, illustrating a changed stock/bond correlation regime. Gold gains and the permanent SPY half remain risk exposures, not demonstrated independent forecasting alpha.

## Promotion checklist / what could blow up this account?

- **Edge/evidence:** the fixed diversification hypothesis is implemented, all four training cases and the selected final are profitable after modeled costs, and the historical net-profit criterion is met. Small episode counts and shared prior history remain explicit. The comparison does not establish an advantage over fixed hedges; it is not an extra promotion gate.
- **Tail/gap risk and drawdown:** stocks, bonds and gold can fall together. The final peak-to-trough loss was $30.03 from $155.72 on 2021-12-28 to $125.70 on 2022-10-13: 19.28% of peak / 21.45% of initial. The low was 10.22% below initial cash and $41.70 above the $84 permanent-kill boundary. Selected training drawdown was larger, $38.99 / 24.06% of peak / 27.85% of initial. Neither observed history nor a trailing correlation sign bounds overnight losses; risk vetoes are not guaranteed stop fills.
- **Adverse selection/execution:** hedge switches can sell low and buy high at the next open. Stress spreads, overnight gaps and asynchronous underlying bond marks can exceed fixed 10 bp assumptions. Equity taker scenarios do not have prediction-market maker protections. Settled-cash delays and skipped small orders can change the intended equal halves; actual broker fractional eligibility/fills/actions require paper verification.
- **Counterparty/operations:** all instruments depend on Alpaca, feeds and the Mac. Accepted no-dead-man/no-startup-reconciliation risks remain unchanged. Future keys must permit trading only, never withdrawals; none is requested, created or changed here.
- **Untrusted inputs/reproducibility:** external prices remain data, never instructions. Hash-bound raw inputs, pure reactor, shared ledger/risk code and immutable receipts support deterministic verification. GLD clears the data gate narrowly; pre-2016 independent coverage is absent. Adjustment/source errors and unavailable historical announcement-time calendar provenance remain limitations. The final cannot be rerun under cosmetic versions or sibling families.
- **Correlation/account exposure:** the permanent SPY half overlaps other equity strategies; the selected IEF or GLD half overlaps duration/gold sleeves. These exposures can lose together and trigger the global daily halt. Concurrent account portfolios were not jointly simulated. The isolated final’s worst marked close-to-close day was −$4.38, which does not bound combined-account loss.
- **Fidelity/limits:** 47 focused tests and stored-fill reconciliation pass through the common reactor/risk/ledger interfaces. Forward paper and broker/live fidelity are pending. The −40% strategy kill, −$50 daily halt, $140 ETF slot, 30-second stale-data halt and five-errors/minute halt remain unchanged; $25 is the prediction-market cap. No paid data, capital, account, venue, key, public post or real order was introduced.
- **Decision:** historical research complete and net-profit criterion met; **remain in backtest, actual allocation $0**. Paper fidelity is the uncompleted next stage, not claimed by this research bead. No funded promotion or live activation. Luck and benchmark comparisons remain descriptive; the canonical C19 final is permanently consumed.

## Verification and immutable receipts

**47 focused checks pass.** Stored-only reconciliation verifies every trial/artifact, adverse fill prices, nonnegative and flat per-fund quantities, full frozen buy targets, cash reserves, settlement availability, fees/net, monthly marked totals and drawdown. All dependency maps match the pre-outcome freeze. Exactly **one canonical C19 final receipt**, trial **5646**, exists. No verification replay or second final was run, and other family finals/shared code/risk limits were not changed.

- Source SHA-256: `65e1fa75f5fd805fc7528eb83fbd536ccd0f8e1e2de304d6bac33188dc2da93b`.
- Selection SHA-256: `fbbb75631a1035e1402666f7b700a63f40a2f02e032fca20571e28effbe16d21`.
- Selected/final strategy version: `0e30d4d2c81c95d15c4e6381716f3fab97eaf4f51a40883fbe83ce7d5d731f57`.
- Artifacts live in the local immutable `data/research/c19-total-return/` archive; full source identities and exceptions are recorded in the plan/source bundle.

| File | SHA-256 |
|---|---|
| train-63-5.json | `ffa4e6fb3075057e4c7965add45fb8ff0ab3b1483a80e1260b76d546ca48e03b` |
| train-63-10.json | `d61edd66e5b362785c70372b7c0beaa177d14c9733277b641a5a1b06044c4a4c` |
| train-126-5.json | `ec261d21bf8aee74012d7d213c3f3b3b2d7c5d5dcb80d1e23aa7b572964f6e5f` |
| train-126-10.json | `9417d48a87b7aef2d840955bc5af017bbba6b8571661778e4aab3bca0a10107f` |
| final.json | `1a038d1266625a09c445a5fdb2e9718932d7b22c506ed7be2c6d7bdab4ae6ba5` |
| training-stored-audit.json | `417da91c5cf2f6a1f743bacd57c8378238b8fc422167d24410608d2c12eec014` |
| complete-stored-audit.json | `4bb44dd8fc75b2d03a51e3563d6960e2a74492363398947f4cb4e4f0d3dcca57` |
