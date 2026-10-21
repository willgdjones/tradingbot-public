# C18: Long-horizon country-equity reversal — preregistration

2026-10-02, OrangeCove. Parent `tradingbot-y74`; candidate bead `tradingbot-ifc`.
**Status:** rules frozen before new candidate outcomes; actual allocation $0.
Research rank/priority **5 / P3**, rubric E/P/C/R **2/1/2/1** (0–3, higher better).
Gates 1/2 pass (concrete rule/testable mechanism); gate 3 is conditional on free
price evidence and eventual fractional eligibility. Verdict: **pursue bounded
research**, with no profitability, paper fidelity or live-readiness claim.

## Hypothesis, universe and fixed rules

**Hypothesis and distinction:** multi-year overreaction or depressed valuations may reverse across national equity markets. Lagged returns are only a valuation proxy. This is a multi-year country hypothesis, distinct from C07's weekly sector liquidity reversal and C03's recent winner selection.

**Universe:** traded **EWA, EWC, EWG, EWJ, EWS, EWU**. Fixed unhedged USD-listed country ETFs, not present-day stock constituents or a claimed complete country universe. Freeze these six before any price fetch; disclose survivorship, currency and market-composition biases.

**Signal and ordered variants:** L = **36**, then **60 months**, always skipping the most recent **12 months**. At month's final regular-session close t, require L+1 month-end adjusted closes for every fund, all within the partition. Score `P[t-12]/P[t-L]-1`. Rank ascending score; alphabetical ties. Hold the lowest two with B/2 each, even if their scores are positive. No threshold, absolute-trend filter or recent-return qualifier. Rebalance monthly; retain selected holdings except target-size changes. The 12-month skip is fixed, not another variant.

**Failure and diagnostics:** cheap countries can remain cheap because of structural decline; currency and sector concentration may dominate. Five-year warm-up leaves a short final measurement window, and long holding spells are not independent trades. Compare same-partition initial equal-weight six-country buy/hold, SPY buy/hold and cash; show each fund's selection count. Disclose both calendar-span benchmarks and the strategy's warm-up drag. No extension of the sample or shorter lookback to rescue sparse outcomes.

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
**one final at 10 bp** in canonical family `c18`. Failed/interrupted
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

Country concentration, currency shocks, geopolitical restrictions and value traps can overwhelm the reversal premise. US-listed ETFs can gap while their underlying markets are closed; fixed slippage may understate execution costs. The portfolio shares global-equity and commodity-exporter risk with existing sleeves; slow signals cannot guarantee a timely exit.

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

- [Richards, IMF Working Paper 97/182](https://www.imf.org/en/publications/wp/issues/2016/12/30/winner-loser-reversals-in-national-stock-market-indices-can-they-be-explained-2458): investigates long-horizon winner–loser reversal across national market indices. Its country set, index portfolios and formation/holding methods differ from the six ETFs, fixed recent-year skip and monthly rebalancing here. It motivates a test, not transferred returns. No paper portfolio-return data were downloaded.

Before execution, verify source coverage, chronology, formula/tie behavior,
settled cash, unchanged risk vetoes and durable single-use final admission.

## 2026-10-02 source audit — no strategy replay

The frozen rules above are unchanged. All six original Yahoo primary series
contain 5,218 sessions, but **EWA and EWS fail the fixed 99% / 5 bp price gate**.
The preregistered Nasdaq × Alpaca-only adjustment route reaches 98.44683% and
97.80964%, respectively; direct Alpaca also fails for both. Stooq returns no
CSV price series. EWC/EWG/EWJ pass the Nasdaq route; EWU passes direct Alpaca.
All mismatches and unmatched dates are retained, with no primary patch,
universe/interval substitution or relaxed threshold.

Immutable local `data/research/c18-country-reversal/audit.json` SHA-256:
`94fc0643d20c3b7c9940b03dd3b7874a0b8ae286812ade09fcd712ccde65fb93`.
It pins 44 input files and five source-audit dependencies. **22 focused checks
pass**, covering fixed-universe admission, null performance, the unchanged
cutoff, immutable evidence and idempotent ledger recording without a final spend.
No ranking, strategy outcome or execution reactor is admitted. All four
36/60-month × 5/10 bp training configurations remain **unattempted**; no winner
or final. Source failure **trial 5651 / strategy 10573** was recorded after audit
freeze `d49249d`, with all performance fields null. Stored-only verification
confirmed 44 input/five code hashes, zero orders/fills and no C18 final spend.
The sole results file records the complete account-risk hold decision.
Actual allocation/data spend $0; no promotion.
