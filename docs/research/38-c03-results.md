# C03: cross-asset momentum total-return results

**Profit test passed; hold at actual $0 pending forward evidence.** The frozen
top-two portfolio at 10 bp earned **$142.654445 in training** (5482) and
**$70.915728 in its single final** (5485). The final completed 26 round trips,
ended flat at $210.915728, and had zero rejected orders or risk halts. Marked
final drawdown was **$38.990032 / 25.55%**. This establishes positive historical
net P&L under the assumptions, not incremental alpha or broker fidelity.

The [plan](38-c03-plan.md) retains the original five funds, three variants,
5/10 bp cases and 2020-07-10T14:24Z cutoff. Implementation `bdbe651` preceded all
outcomes; selection `9a9d6a4` preceded final 5485. Failed source trials
3516/4067/5314 remain unchanged. No other variant or cost consumed a final.

## Data and model

Yahoo supplies all 5,218 sessions per fund, 2006-01-03–2026-09-30. Adjusted
opens use the same day's adjusted-close/raw-close ratio, with no separate
dividend credit. The free independent comparison retained every primary price:

| Fund | Agreed / paired returns | Agreement | Exceptions | Earlier unpaired returns |
|---|---:|---:|---:|---:|
| SPY | 2,509 / 2,512 | 99.8806% | 3 | 2,705 |
| IEF | 2,512 / 2,512 | 100% | 0 | 2,705 |
| GLD | 2,674 / 2,700 | 99.0370% | 26 | 2,517 |
| EFA | 2,512 / 2,512 | 100% | 0 | 2,705 |
| VNQ | 2,510 / 2,512 | 99.9204% | 2 | 2,705 |

GLD's reference is Alpaca adjusted SIP, 2016-01-05–2026-09-30 returns. Others
use Nasdaq split-adjusted closes × Alpaca-only `all/split` dividend factors,
2016-10-03–2026-09-30 returns, after the SIP close-convention mismatch identified
before C11 outcomes. Every disagreeing day, return, delta and unmatched date is
in the frozen source artifact. Earlier prices do not have a second-source match.

The simulation uses $140 virtual cash, 95% decision-close targets capped at the
slot, a frozen 5% reserve, pro-rata additions using settled cash, conservative
cash-release dates, adverse raw-cent rounding and dated 2026-09-17 fees expressed
in raw-share equivalents. Holdings are total-return equivalents. Actual broker
fills/actions belong in paper/live, not a new research prerequisite. There is
no leverage, dividend double credit, extra blackout or actual auction-fill claim.
Warm-up stays inside each partition: first decisions were 2007-01-31 and
2021-07-30. Prior SPY/IEF and other fund research is disclosed contamination.

## Measurements

| Case | Trial | Round trips | Net | Marked max drawdown |
|---|---:|---:|---:|---:|
| Top one, 5 bp | 5478 | 63 | $110.77 | $44.37 / 19.04% |
| Top one, 10 bp | 5479 | 63 | $101.79 | $45.67 / 19.71% |
| Top two, 5 bp | 5481 | 62 | $147.18 | $37.61 / 13.38% |
| **Top two, 10 bp training** | **5482** | **62** | **$142.65** | **$38.72 / 13.90%** |
| Top two + SMA10, 5 bp | 5483 | 61 | $131.68 | $39.45 / 14.51% |
| Top two + SMA10, 10 bp | 5484 | 61 | $127.26 | $40.37 / 14.99% |
| **Top two, 10 bp final** | **5485** | **26** | **$70.92** | **$38.99 / 25.55%** |

Every case ended flat with no rejections. Selected training/final fees were
$4.29/$1.65; adverse reference costs $9.54/$3.64; gross after execution costs
but before fees $146.94/$72.57; turnover $9,096.31/$3,523.28. Average daily
exposure was 58.60%/70.51%. Each partition had two terminal liquidation fills.
Recorded cash-delay/sub-dollar allocation skips were 36/83, with 139/155 total
skip records including warm-up and small adjustments; these count fund/session
records, not independent missed trades. Dollar targets were never recomputed
from later equity during those delays.

The selected training monthly-block p-value is **0.00319968**, 10,000 fixed-seed
three-month block draws, 60 exit-month clusters. **Final cluster p-value is null**:
26 trips occupy only 22 exit months, below the predeclared 30-cluster reporting
minimum. Simultaneous ETF legs are not independent bets. No p-value gate was
added to the owner's profit criterion.

| Regime | Selected training marked net / drawdown | Final marked net / drawdown |
|---|---:|---:|
| 2006–2009 | $56.13 / 12.98% | — |
| 2010–2019 | $81.78 / 13.90% | — |
| 2020–2021 within partition | $4.74 / 5.96% | $12.27 / 6.03% |
| 2022 | — | −$27.11 / 25.55% |
| 2023–2026 | — | $85.76 / 10.50% |

Final annual marked net: 2020 $0 (warm-up), 2021 $12.27, 2022 −$27.11,
2023 $12.88, 2024 $24.96, 2025 $44.35, 2026 $3.56. Exact annual net/drawdowns
for all seven trials are retained in their ledger metrics and run artifacts.
Marked attribution above avoids assigning an entire long holding's profit to
its exit year. The 2022 loss and concentration of later gains remain material.

Diagnostic no-cost buy/hold returns, training/final: SPY **232.77%/161.40%**,
equal-weight five funds **151.86%/83.53%**, cash 0%/0%. Strategy returns were
101.90%/50.65%. Both buy/hold benchmarks outperformed in the final and had lower
drawdowns (SPY 24.50%, equal weight 23.62%). Different exposure and in-partition
warm-up matter; positive raw P&L does not demonstrate timing alpha.

## Promotion checklist and what could blow up this account?

- **Edge/statistics:** the documented momentum hypothesis, fixed rules, costs,
  counts, drawdown and regimes are measured. Profit passes in both partitions;
  final independent sample size, 2022 losses, prior inspection and weak benchmark
  comparison limit inference. Decision: **hold for forward evidence**, actual
  $0; OrangeCove, 2026-10-01. No ready-for-live or paper activation.
- **Tail/gaps:** two selected ETFs can fall together before monthly rotation.
  A $140 equity slot is allowed; the prediction-market $25 cap is inapplicable.
  The −40% allocation kill and −$50 daily halt are vetoes, not guaranteed exits.
- **Adverse selection:** taker/open slippage is assumed, not observed. Prediction
  maker guards are inapplicable. Replacements may wait for settled cash.
- **Venue/operations:** eventual Alpaca, feed and Mac dependence and accepted
  no-dead-man risks remain. No venue, permission, key, funded allocation or
  withdrawal capability changed; data spend was $0.
- **Inputs/reproduction:** external values are data only. Hash-bound originals,
  deterministic ranking, 13 focused tests, durable fills and exact strategy
  version support inspection. The same pure reactor interface is used. The
  consumed final remains unavailable for another run.
- **Correlation/fidelity:** stock, bond, REIT and gold exposures overlap other
  momentum sleeves and can concentrate losses. Paper has not demonstrated
  actual fills, fees, settled cash and corporate actions. PRD6 and accepted
  PRD9 risks remain unchanged; confirmation must use genuinely new observations.

Source and selection hashes/version are pinned in the plan. Immutable artifacts
are in `data/research/c03-total-return/`; `final.json` SHA-256:
`fc4c959821e59b830b2512bc67809ae3290b1f143728da8f164ea9aa9eb90518`.
Stored-only verification checks source hashes, seven trial metrics/code versions
and exactly one permanent C03 family receipt (5485), without replaying outcomes.
