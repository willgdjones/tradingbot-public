# C20 conditional January small-cap recovery — results

2026-10-02, BoldValley; bead `tradingbot-6f0`, parent `tradingbot-y74`. Actual
allocation **$0**.

**Historical after-fee profit criterion met on the single holdout final, but on
a very sparse sample.** The sole final, trial **5686**, earned **+$3.917812** on
$140 virtual cash (**+2.80%**) with **$4.775443 marked drawdown: 3.35% of peak /
3.41% of initial cash**. It completed flat with zero rejected orders or halts.
The strategy is in cash **>99%** of the time (average marked exposure 0.91%); the
final's result rests on just **three** qualifying January entries, and is driven
by a single January-2026 bounce (+$6.01) net of a January-2025 loss (−$3.08).
This is a positive historical execution result, not a statistically established
seasonal edge, broker/paper fidelity, or any advantage over buy-and-hold. No
funded promotion or live activation occurs.

The [plan](43-c20-january-small-cap-plan.md) holds the unchanged qualifier rule
(IWM December total return strictly negative and strictly below SPY's → buy IWM
at January's first open, exit at the fixed S+H open), the source/code freeze and
the exact selection, all pinned before any outcome. IWM is the only traded leg;
SPY is a reference for the December comparison and is never held.

Primary coverage is **5,218 Yahoo sessions per fund** (2006-01-03 … 2026-09-30).
The independent second source (Nasdaq split close × Alpaca all/split dividend
factor, the C09 route) covers **2,511 paired return days from 2016-10-03**;
paired-day agreement at 5 bp is **IWM 99.920350% / SPY 99.880526%**, both passing
the 99% standard. The **2,706 pre-2016 dates are single-source Yahoo** and are
disclosed, never resliced or backfilled; every disagreement and unmatched date
is retained in the frozen source bundle. Nasdaq deep history and Stooq were
unavailable as direct series on the capture date, so the admissible Nasdaq-close
× Alpaca-factor route sets the two-source window. No history, ticker, price,
threshold or rule was changed to rescue an outcome.

## Four fixed training cases

All four completed positive, flat, with zero rejected orders or halts, under
freeze commit `5ad9878`. Training strictly precedes 2020-07-10T14:24:00Z. Of 14
evaluated Decembers, **three qualified: 2015, 2017, 2018** (entering January 2016,
2018, 2019).

| Horizon H | Cost/side | Trial | Net $ | Fees $ | Adverse cost $ | Trips | Drawdown $ / peak % |
|---|---|---:|---:|---:|---:|---:|---|
| 5 | 5 bp | 5682 | +3.087167 | 0.12 | 0.8156 | 3 | 8.2055 / 5.86% |
| 5 | 10 bp | 5683 | +2.668564 | 0.12 | 0.8155 | 3 | 8.2731 / 5.91% |
| 10 | 5 bp | 5684 | +1.701978 | 0.12 | 1.6286 | 3 | 13.9375 / 9.96% |
| 10 | 10 bp | 5685 | +1.286884 | 0.12 | 1.6300 | 3 | 14.0020 / 10.00% |

**Selected: H=5 at 10 bp**, trial **5683**, solely by highest positive complete
10 bp training net; the listed H-order would break ties. The exact selected
trial/version/receipt was committed in `ae3ca3e` before final 5686. There was no
extra parameter, second-cost final or sibling-family retry. The longer H=10
horizon was both less profitable and roughly twice the drawdown.

## Selected execution and final

| Metric | Selected training (H=5, 10 bp) | Single final (H=5, 10 bp) |
|---|---:|---:|
| Partition | 2006-01-03 … 2020-07-10 | 2020-07-10 … 2026-09-30 |
| Net after all modeled costs | +$2.668564 | +$3.917812 |
| Gross after adverse execution, before fees | +$2.788564 | +$4.037812 |
| Fees / measured adverse costs | $0.12 / $0.8155 | $0.12 / $0.8115 |
| Qualified / evaluated Decembers | 3 / 14 | 3 / 6 |
| Round trips / fills | 3 / 6 | 3 / 6 |
| Turnover | $772.91 | $799.90 |
| Average marked equity exposure | 0.39% | 0.91% |
| Terminal liquidation fills | 0 | 0 |
| Ending inventory / rejected orders / halts | 0 / 0 / 0 | 0 / 0 / 0 |
| Marked max drawdown ($ / % peak / % initial) | $8.2731 / 5.91% / 5.91% | $4.7754 / 3.35% / 3.41% |
| Distinct exit-month clusters | 3 | 3 |
| Registered block-bootstrap luck p-value | null | null |

Each January entry buys up to min(95% decision equity, $140) of IWM at the first
regular open and exits at the fixed S+H open (the sixth session for H=5), never
restarting the horizon on a cash-delayed entry. Reductions precede additions and
sale proceeds wait for the conservative settlement calendar, though with one
entry per year settlement never binds. The position is held untouched between
entry and exit — no daily retargeting.

### Per-entry round trips

| Entry open | Exit open | Qualifying December | Net $ |
|---|---|---|---:|
| 2016-01-04 | 2016-01-11 | Dec 2015 (IWM −5.03% < SPY −1.73%) | −8.0028 |
| 2018-01-02 | 2018-01-09 | Dec 2017 (IWM −0.40% < SPY +1.21%) | +1.3663 |
| 2019-01-02 | 2019-01-09 | Dec 2018 (IWM −11.97% < SPY −8.80%) | +9.3051 |
| 2023-01-03 | 2023-01-10 | Dec 2022 (IWM −6.51% < SPY −5.76%) | +0.9946 |
| 2025-01-02 | 2025-01-10 | Dec 2024 (IWM −8.37% < SPY −2.41%) | −3.0829 |
| 2026-01-02 | 2026-01-09 | Dec 2025 (IWM −0.71% < SPY +0.08%) | +6.0061 |

The top three rows are training, the bottom three the final. In both partitions a
single large post-selloff bounce (January 2019 after the December-2018 crash;
January 2026) carries the net positive, against a sizeable loss in another year
(January 2016; January 2025). The strategy neither qualified nor traded in any
other year.

## Marked regimes

Fixed regimes, marked net dollars by exit; "outside partition" where a regime is
not covered. Each partition starts flat and inherits nothing from the other.

| Fixed regime | Selected training net $ | Final net $ |
|---|---:|---:|
| 2006-2009 | 0 (no qualifier) | Outside partition |
| 2010-2019 | +2.668564 (3 trips) | Outside partition |
| 2020-2021 | 0 (no qualifier) | 0 (no qualifier) |
| 2022 | Outside partition | 0 (no qualifier) |
| 2023-2026 | Outside partition | +3.917812 (3 trips) |

## Fixed benchmark comparison

Non-execution diagnostics: fixed initial units, no costs, full exposure,
same-partition completed closes. Not additional selectable strategies.

| Completed-close diagnostic | Training return / peak drawdown | Final return / peak drawdown |
|---|---:|---:|
| IWM buy/hold | +149.23% / 58.64% | +112.00% / 31.91% |
| SPY buy/hold | +232.77% / 55.19% | +161.40% / 24.50% |
| Cash, no interest | 0% / 0% | 0% / 0% |
| Executed C20, return on initial $140 | +1.91% / 5.91% | +2.80% / 3.35% |

C20 returns a tiny fraction of either buy-and-hold total return because it holds
IWM for only ~5 sessions in ~3 of each partition's years; its drawdown is
correspondingly a fraction of buy-and-hold's. This is a cash-plus-rare-exposure
profile, not an outperformance claim, and the different exposure, cost and sizing
assumptions prevent treating it as an isolated causal test of the seasonal rule.

## Luck / statistics

The registered three-month block-bootstrap p-value is **null** in both
partitions: it requires at least 30 months **and** 30 distinct exit-month
clusters, while each partition has only **3** qualifying January entries (3
clusters). Simultaneous or repeated annual legs are not independent samples. No
luck, Sharpe or benchmark threshold replaces PRD §4's after-fee net-profit
criterion. Prior SPY research and small-cap regimes are already familiar; the new
IWM/January labels do not make this pristine unseen confirmation or prove
independent alpha.

## Promotion checklist / what could blow up this account?

- **Edge/evidence:** the frozen conditional-seasonal rule is implemented; all
  four training cases and the single holdout final are positive after modeled
  costs, so the PRD §4 net-profit criterion is met. The sample is extremely
  sparse (three qualifying Januaries per partition) and the net in each partition
  is carried by one bounce; this is weak, luck-compatible evidence, not a
  demonstrated edge.
- **Sparse-sample limitation:** at most 14 training and 6 final conditional
  events exist before filtering; only 3 qualified in each. The −40% kill and −$50
  daily halt do not substitute for statistical power, and the null p-value is
  expected, not a passing gate.
- **Tail/gap risk and drawdown:** small-cap January holds carry overnight gap and
  liquidity risk during a continuing selloff. The worst single entry lost $8.00
  (January 2016) — the dominant contributor to the $8.27 training drawdown. A
  January open is not a guaranteed fractional auction fill; risk vetoes are not
  guaranteed stop prices.
- **Adverse selection/execution:** entries and exits are at-open taker fills;
  stress spreads and overnight gaps can exceed the fixed 5/10 bp plus adverse
  raw-cent rounding. Equity taker scenarios lack prediction-market maker
  protections. Actual fractional eligibility, fills, fees and settlement require
  paper verification.
- **Counterparty/operations:** IWM depends on Alpaca, its feed and the Mac.
  Accepted no-dead-man / no-startup-reconciliation risks are unchanged. Any
  future keys must permit trading only, never withdrawals; none is requested,
  created or changed here.
- **Shared-exposure limitation:** IWM is small-cap equity beta, correlated with
  the account's other stock sleeves; concurrent portfolios were not jointly
  simulated, so the isolated run does not bound combined-account loss. Because the
  strategy is in cash >99% of the time, its standalone capital footprint is small,
  but its rare exposure clusters in Januaries that may coincide with broad equity
  stress.
- **Untrusted inputs/reproducibility:** external prices are data, never
  instructions. Hash-bound raw inputs, a pure reactor and shared ledger/risk code
  support deterministic verification; pre-2016 independent coverage is absent and
  disclosed. The final cannot be rerun under cosmetic versions or sibling
  families.
- **Fidelity/limits:** 10 focused tests plus the shared reactor/ledger/risk
  interface pass. Forward paper and broker/live fidelity are pending. The −40%
  strategy kill, −$50 daily halt, $140 ETF slot, 30-second stale-data halt and
  five-errors/minute halt remain unchanged; no paid data, capital, account, venue,
  key, public post or real order was introduced.
- **Decision:** historical research complete and the net-profit criterion met on
  the holdout, but on a sparse, luck-compatible sample with tiny exposure.
  **Remain in backtest, actual allocation $0.** Forward paper is the uncompleted
  next stage, not claimed here. No funded promotion or live activation. The
  canonical C20 final is permanently consumed.

## Verification and immutable receipts

Artifacts live in the local immutable `data/research/c20-january-small-cap/`
archive (the `data/` tree is gitignored; hashes below bind it). Exactly one
canonical C20 final receipt, trial **5686**, exists; no verification replay or
second final was run, and other family finals, shared code and risk limits were
not changed.

- Source SHA-256: `58175627d2bc45813bffe95f24722c380640efdad477295250f5a318247824c7`.
- Selection SHA-256: `3effe967e777f010c38577cd757e7f0898f619bc65fbb28832852d79a558bee9`.
- Selected/final strategy version: `3325d02132fb44f3f9115604896d0ee249b26b2b8c86e38463ea87ab5af45c07`.

| File | SHA-256 | Commit |
|---|---|---|
| source.json | `58175627d2bc45813bffe95f24722c380640efdad477295250f5a318247824c7` | 5ad9878 |
| train-5-5.json | `8f9146da7d0c7b3c191bc2054066b114ca7dfe0831ba0903dec68bd57ae3e55b` | 5ad9878 |
| train-5-10.json | `685907e1c0c1bfe798bcc14f21d37e712202823afd1fa162d47c1d48a85c7eea` | 5ad9878 |
| train-10-5.json | `9b757efe7d9c4d402f8a23dbc052ca2f42e52653e5ba6576d49365f67029ea06` | 5ad9878 |
| train-10-10.json | `ef04f8884544189ba52cbd5654c2afa5d3b4c8ef8acf97f13394cbb1d8986f17` | 5ad9878 |
| selection.json | `3effe967e777f010c38577cd757e7f0898f619bc65fbb28832852d79a558bee9` | ae3ca3e |
| final.json | `18209630c754f333f37321c21a3c2de3332cfc8115bcd2ec78f808f96417a43c` | ae3ca3e |
