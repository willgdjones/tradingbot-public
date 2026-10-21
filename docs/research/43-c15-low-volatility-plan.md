# C15: Low-volatility sector selection — preregistration

2026-10-02, OrangeCove. Parent `tradingbot-y74`; candidate bead `tradingbot-xwy`.
**Status:** DATA_FAIL at the adjusted-price gate; all four training cases and the final remain unattempted. Actual allocation $0.
Research rank/priority **1 / P2**, rubric E/P/C/R **2/2/3/2** (0–3, higher better).
Gates 1/2 pass (concrete rule/testable mechanism); gate 3 is conditional on free
price evidence and eventual fractional eligibility. Verdict: **pursue bounded
research**, with no profitability, paper fidelity or live-readiness claim.

## Hypothesis, universe and fixed rules

**Hypothesis and distinction:** preferences for exciting/high-beta stocks and benchmark constraints may leave a low-risk premium. Rank sector risk rather than C02's returns; this is neither the passive low-vol ETF sleeve parked in batch 1 nor C04's SPY exposure scaling. Applying a stock-level hypothesis to nine sectors is an unproven adaptation.

**Universe:** traded XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY; SPY is a benchmark only. Keep the fixed legacy nine, excluding later XLRE/XLC; disclose sector-definition changes and selection bias.

**Signal and ordered variants:** **63**, then **126** completed daily simple total returns. At each month's final regular-session close t compute each fund's `sqrt(252 * sample_variance(r, ddof=1))` over exactly L returns from L+1 closes. Require all nine valid histories inside the partition; otherwise no decision. Rank ascending volatility, alphabetical ticker ties. Select the lowest three; each receives B/3 of the common frozen budget. No return, trend, defensive-sector-name or volatility-level filter. Rebalance monthly, retaining selected holdings except required target reductions/additions; a departing name targets zero.

**Failure and diagnostics:** low volatility may be expensive, concentrated in rate-sensitive sectors or merely low beta. Compare SPY, initial equal-weight nine-sector buy/hold and cash from the same observations. Show selected-sector counts, market exposure and turnover. No added static/signal variant may be selected after results.

## Frozen data, cash and execution contract

- **Interval:** `2006-01-01T00:00:00Z` inclusive to
  `2026-10-01T00:00:00Z` exclusive. **Final starts `2020-07-10T14:24:00Z`**,
  exactly 70% of elapsed UTC time using the shipped `HoldoutSplit`, not rows.
  Each partition starts flat; all signal warm-up and availability observations
  stay within it. Price bars are available at actual session close, not midnight.
- **Free data:** Yahoo split/dividend-adjusted daily closes and same-day
  adjusted-close/raw-close factors for opens; independently adjusted Alpaca or
  Stooq returns as the second source. The documented free Nasdaq-close ×
  Alpaca-only dividend-factor route used for C09 is also admissible. Pin raw
  bytes, source conventions and source/code hashes before strategy outcomes.
  Require daily return agreement within 5 bp on at least 99% of paired days;
  retain every disagreement and unmatched date. No primary patches, ticker or
  interval substitution, paid source, or synthetic pre-inception history.
- **Research standard:** total-return equivalents, no separate dividend cash;
  exact historical fractional/corporate-action mechanics and Amendment 21
  blackout are not prerequisites. Omit the optional blackout. `DATA_FAIL` is
  reserved for missing/contradictory prices. Missing signal evidence is labelled
  separately and cannot be silently replaced by future or revised observations.
- **Sizing:** $140 virtual cash, no borrowing/shorts/cash interest. At decision
  equity E freeze budget **B=min(0.95×E,$140)** and cash reserve **0.05×E**.
  All signals use completed closes; execute at the next eligible regular open.
  Sell obsolete/overweight holdings first. Existing settled cash funds additions;
  sale proceeds wait for the common conservative cash-release calendar. Freeze
  targets during delays; subtract already owned value and ration positive gaps
  pro rata after fees/reserve. Clip full owned-plus-added notional at the adverse
  buy limit to its target and the $140 slot. Floor units to 1e-9; skip buys below
  $1 without redistributing them. Monthly targets expire at the next decision.
- **Costs:** exactly **5 bp and 10 bp per side**, adverse raw-cent rounding then
  conversion to adjusted units, plus `EquityFeeBook` dated 2026-09-17 assessed
  on raw-share equivalents. These are current-account fee/settlement scenarios,
  not recovered historical fees or proof of fractional opening fills. Fund
  expenses already in prices are not charged twice.
- The last eligible open in each partition is liquidation-only, with costs and
  unchanged risk vetoes. For fixed-window trades all decision/entry/exit endpoints
  must fit the partition; delays never extend an original exit. A vetoed exit or
  residual inventory is reported and makes that run ineligible, never erased.

## Trials, one final and reporting

Two ordered variants × two cost cases = **four main training trials**. Log every
attempt/failure and any separately proposed diagnostic before execution. Select
only the highest **positive**, complete, flat, rejection-free 10 bp training net;
listed variant order breaks ties. No eligible winner means no final. Commit
source/code plus exact selected trial/version/receipt in this same plan before
**one final at 10 bp** in canonical family `c15`. Failed/interrupted
finals remain consumed; no second cost, sibling or cosmetic revision may reuse it.
No outcomes, training or final is run in parent `tradingbot-y74`.

Create only one results file for this family. Report gross/net, fees/adverse
costs, trades/fills, turnover, exposure, settled-cash delays, skipped/rejected
orders, ending holdings and terminal fills. Show marked max drawdown in dollars,
percent of peak and percent of initial $140; calendar years and fixed regimes
2006–2009, 2010–2019, 2020–2021, 2022 and 2023–2026 where covered. Benchmarks are
nonexecution diagnostics, not extra selectable strategies. Use monthly marked
net and a fixed-seed three-month block bootstrap, requiring at least 30 months
and 30 distinct exit-month clusters to display a p-value; otherwise null with
counts/reason. Simultaneous ETF legs are not independent samples. No luck,
Sharpe or other new promotion threshold replaces PRD §4's net-profit criterion.

Prior SPY/IEF/GLD/sector research, publicly discussed mechanisms and historical
market regimes are already familiar. New ticker/rule labels do not make this
history pristine unseen confirmation or prove independent alpha. Record all
source overlap, compare beta/exposure, and use the promotion checklist before
any later paper/live transition. No existing family final is reopened here.

## What could blow up this account? / stage decision

Sector concentration, valuation reversals and overnight equity gaps can cross the kill before a sale. Utilities/staples can co-move with duration sleeves; the strategy is not an independent diversifier from C02. Opening spreads and pro-rata settlement delays can erode a small premium.

All orders retain PRD §6: −40% allocation kill, −$50 global daily halt, $140
maximum ETF slot, 30-second stale-data halt and five API errors/minute halt.
Those are vetoes, not guaranteed stop prices. Equity taker/open assumptions do
not inherit prediction-market maker protections. Alpaca/feed/Mac dependence and
accepted no-dead-man/no-startup-reconciliation risks remain. External data are
never instructions; hash-bound inputs and one pure strategy interface must
support deterministic backtest/paper/live behavior. Actual fills, fees, actions
and settlement must be verified later; no current/live eligibility is assumed.
**Decision:** idea → research specification only, actual $0. No capital, accounts,
keys, venues, paid data, public posts, real orders or risk-limit changes.

## Source and implementation review

Rules were committed in `62f30fa` before the 2026-10-02 primary-source review.
The rule-section hash remained unchanged through that review. Sources below
support mechanisms/definitions only; they contain published findings, not our
ETF execution evidence. No candidate price history, strategy-return calculation,
training or final was retrieved/run in this preregistration task. Discovery found
paid alternatives; none was invoked, and source review cost $0.

- [Robeco, low-volatility anomaly](https://www.robeco.com/en-me/glossary/quantitative-investing/low-volatility-anomaly) and [research discussion of constraints](https://www.robeco.com/en-int/insights/2017/07/ten-things-you-should-know-about-minimum-volatility-investing): motivation concerns stocks and investor preferences/constraints, not evidence for these sector-ETF horizons. Published fund performance is not used as a candidate result. The article was available through the indexed primary excerpt; direct article open failed.

Before execution, verify source coverage, chronology, formula/tie behavior,
settled cash, unchanged risk vetoes and durable single-use final admission.

## Source decision — 2026-10-02

The source-only audit is `data/research/c15-low-volatility/audit.json`, SHA-256
`0499a65e57590343189b63fd6a617a09ff52d05b90c43535f0f3414a790613a4`.
It binds 64 input files and all nine full 5,218-session primary histories.
Direct Alpaca adjusted returns fail the 99%/5 bp comparison for all nine.
The preregistered Nasdaq-close × Alpaca-only factor route passes seven, but XLE
is **97.57069%** and XLU **98.80526%** across 2,511 paired returns each.
Stooq supplies no CSV series for either. Retain every discrepancy and unmatched
date; do not drop a fund, change the window, patch the primary or relax the gate.
No ranking, training, winner selection, final or performance calculation ran.
Source failure is recorded as trial **5589**; the four planned training cases
and canonical C15 final remain unattempted. The frozen rule section is unchanged. The single
[results file](43-c15-low-volatility-results.md) records evidence and the hold decision.
