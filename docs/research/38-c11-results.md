# C11: expiration-week total-return results

**FAIL — hold at $0.** On 2026-10-01, the preregistered next-open winner lost
**$37.879554** in its single 10 bp final, trial **5399**: 75 completed round
trips, flat ending, no rejected orders or risk halts. Training trial 5388 made
$16.268694. This fails PRD4's profit-in-both-partitions requirement. No sibling,
second cost case or revised calendar gets another final on this history.

The [plan](38-c11-plan.md) was committed before outcomes (`1af38bf`), and the
training selection before final (`258e431`). Prior source failure 4589 remains
unchanged. The adjusted-total-return research model follows AGENTS `d267cf7`;
the old fractional/action-mechanics blocks do not prevent this measurement.

## Source and execution

Yahoo supplied all 5,218 sessions, 2006-01-03–2026-09-30. Nasdaq split-adjusted
closes × independently captured Alpaca `all/split` factors agree within 5 bp
on **2,509/2,512 returns (99.8806%)**, 2016-10-03–2026-09-30. The earlier 2,705
returns have no second-source match. Primary prices were never patched.
Exceptions, retained in the source artifact:

| Return date | Absolute difference |
|---|---:|
| 2018-06-15 | 44.3558 bp |
| 2026-04-20 | 20.0381 bp |
| 2026-04-21 | 19.9142 bp |

Stooq returned verification HTML; the original SIP-close comparison failed at
93.59%, and remains archived. Nasdaq's close convention resolved that mismatch
before any strategy outcomes. This cross-check covers overlapping history only.

The original 2020-07-10T14:24Z split, two exits, $140 virtual cash, frozen 95%
targets, settled cash and unchanged risk engine were retained. Adverse raw-price
rounding, 5/10 bp per side and dated September 17, 2026 raw-share-equivalent fees
are explicit execution assumptions. No separate dividend credit, blackout or
claim of actual fractional auction fills. The calendar agrees with all 33
reviewed 2024–September 2026 Cboe dates. Prior SPY research contaminates the
claim of an untouched holdout; this is a diagnostic historical test.

## Measured results

| Partition / exit / cost | Trial | Trades | Net | Marked max drawdown |
|---|---:|---:|---:|---:|
| Training / expiry close / 5 bp | 5378 | 174 | $34.68 | $44.42 / 24.89% |
| Training / expiry close / 10 bp | 5383 | 174 | $7.88 | $49.27 / 28.39% |
| Training / next open / 5 bp | 5384 | 174 | $42.74 | $38.37 / 21.34% |
| Training / next open / 10 bp | 5388 | 174 | $16.27 | $46.50 / 26.59% |
| **Final / next open / 10 bp** | **5399** | **75** | **−$37.88** | **$44.29 / 30.97%** |

All five main cases completed their expected trips, ended flat, and had no
rejected orders. Selected training/final fees were $6.96/$3.00; adverse reference
costs $49.15/$16.00; gross after execution costs but before fees $23.23/−$34.88.
Average daily exposure was 21.71%/22.11%. Final cash including unsettled cash
was $102.120446; selected training/final turnover was $47,714.85/$15,832.03.
Zero-yield cash returned 0%; same-partition SPY buy/hold returned
232.77%/161.40%, with 55.19%/24.50% drawdowns and no execution costs. Benchmark
drawdown dollar fields in raw artifacts are per adjusted unit, not a $140
portfolio; percentage comparisons above are scale independent.

Monthly 3-month-block bootstrap p-values: **0.34437 training / 0.98110 final**,
10,000 draws, fixed seed, one-sided against positive mean. They are descriptive,
not selection-adjusted and not an extra promotion threshold.

| Regime | Selected training net / drawdown | Final net / drawdown |
|---|---:|---:|
| 2006–2009 | $18.15 / 20.39% | — |
| 2010–2019 | $1.06 / 20.41% | — |
| 2020–2021, within partition | −$2.95 / 10.44% | −$19.22 / 15.55% |
| 2022 | — | −$18.38 / 15.22% |
| 2023–2026 | — | −$0.28 / 8.01% |

The final loses both before the 2022 weekday-expiry structure break and after
it; 2023–2026 is approximately flat after costs. Annual marked results and
drawdowns for every trial are in its ledger metrics and immutable run artifact.
For the selected rule, annual net dollars are:

| Year | Training | Final |
|---|---:|---:|
| 2006 | 9.00 | — |
| 2007 | 2.78 | — |
| 2008 | 1.51 | — |
| 2009 | 4.87 | — |
| 2010 | −3.95 | — |
| 2011 | −16.00 | — |
| 2012 | −3.46 | — |
| 2013 | 2.54 | — |
| 2014 | 9.85 | — |
| 2015 | −4.01 | — |
| 2016 | 8.04 | — |
| 2017 | 5.77 | — |
| 2018 | −12.15 | — |
| 2019 | 14.43 | — |
| 2020 | −2.95 | −6.23 |
| 2021 | — | −12.99 |
| 2022 | — | −18.38 |
| 2023 | — | 1.80 |
| 2024 | — | −2.29 |
| 2025 | — | 0.20 |
| 2026 | — | 0.01 |

Training-only ±7-calendar-day controls preserve endpoint type and session
interval counts; invalid shifted endpoints are omitted, never rolled. At 10 bp:
expiry-close +7 (5391) lost $15.24 over 113 trips; next-open −7 (5392) lost $55.15
over 119; next-open +7 (5397) lost $15.72 over 93. Expiry-close −7 (5386) is
**incomplete**: the unchanged −40% allocation kill fired on 2008-12-11, after
29/138 expected trips, and later exits were vetoed. Its −$54.72 realized net
and residual position must not be presented as a completed control return.
All controls were excluded from selection and none consumed a final.

## Promotion checklist and what could blow up this account?

- **Edge/statistics:** the forced-expiry-flow hypothesis and fixed entry/exit
  were measurable, but final profit fails. Counts, costs, marked drawdown,
  regimes and descriptive luck are recorded. Decision: **hold**, actual $0;
  reviewer OrangeCove, 2026-10-01. No paper/live promotion.
- **Tail/gaps:** unlevered SPY can gap through a monthly exit; a $140 equity
  position is allowed, not the prediction-market $25 cap. A stop is a veto,
  not a guaranteed liquidation. The killed control demonstrates residual risk.
- **Adverse selection:** these are taker scenarios, so prediction-market maker
  guards are inapplicable. Crowded expiry flow and open slippage remain risks.
- **Venue/operations:** eventual use depends on Alpaca, feed continuity and the
  owner's Mac. Accepted no-dead-man and venue risks remain; no keys or orders
  changed, and no withdrawal capability was requested.
- **Inputs/reproduction:** external prices are data, never instructions.
  Original bytes, code hashes, fixed controls and durable trials are preserved.
  Reproduce mechanics with synthetic tests or inspect stored results; the
  consumed final cannot be replayed. Same pure reactor interface is used.
- **Correlation/fidelity:** SPY overlaps other equity strategies and can
  concentrate the −$50 daily halt. Actual broker fills/actions and paper
  fidelity were not demonstrated. PRD6, actual capital, venues, permissions,
  keys and accepted PRD9 risks are unchanged. Data spend: **$0**.

Validation: **17 focused tests passed**, including holiday shifts, causal
sizing, partition boundaries, fee-unit conversion, actual shared ledger/risk
behavior and admission before feed consumption. Nine measured trials comprise
four main training cases, four controls and exactly one family final.

Artifacts live in `data/research/c11-total-return/`: source/selection hashes and
the selected strategy version are pinned in the plan; `final.json` SHA-256 is
`f1ea9bdbc5a97bc41932bd4b9167302514734eac0698e8f7a1771aaf2dc9859e`.
Each run contains exact P&L, curve, fills, exposure, annual/regime metrics and
dependency hashes. The final receipt permanently records C11 family use.
