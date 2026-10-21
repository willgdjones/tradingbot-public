# C16: Yield-curve-conditioned Treasury duration — preregistration

2026-10-02, OrangeCove. Parent `tradingbot-y74`; candidate bead `tradingbot-1rl`.
**Status:** rules frozen before new candidate outcomes; actual allocation $0.
Research rank/priority **4 / P2**, rubric E/P/C/R **2/2/2/1** (0–3, higher better).
Gates 1/2 pass (concrete rule/testable mechanism); gate 3 is conditional on free
price evidence and eventual fractional eligibility. Verdict: **pursue bounded
research**, with no profitability, paper fidelity or live-readiness claim.

## Hypothesis, universe and fixed rules

**Hypothesis and distinction:** the slope of the Treasury curve may proxy time-varying compensation for duration. It is not an observed term premium: expected future short rates also drive slope. This tests a macro-state allocation, distinct from C10's month-end window and C09's auction calendar.

**Universe:** TLT traded, cash otherwise; FRED/ALFRED **DGS10** and **DGS2** are signal inputs only. No macro-value substitution and no synthetic bonds.

**Signal and ordered variants:** slope threshold **0.00**, then **1.00 percentage point**. At each month's final regular-session close D, use the latest common observation date d for DGS10/DGS2, with `d <= D-2 calendar days` and `D-d <= 7 calendar days`. Values must come from their last ALFRED vintage dated no later than D-1; use no later revision. Treat vintage-date information as available at the following New York midnight, not the observation date. All used observations and availability dates must lie in the partition. Compute `slope = DGS10 - DGS2` in percentage points. If slope is strictly above the threshold, target B in TLT; otherwise zero. Equality means cash. Rebalance only monthly.

**Macro evidence:** archive free vintage download metadata and bytes before replay. The lag/staleness clock is not a license to use a current revised series: missing historical vintage evidence is `SIGNAL_EVIDENCE_GAP`, with null performance before outcomes, not a price `DATA_FAIL` or permission to silently drop months. If the archived decision-time record proves there was no valid observation within seven days, that decision targets cash and is counted. No new API key is authorized.

**Failure and diagnostics:** slope may predict neither the sign nor size of long-bond returns, and long-end inflation risk dominates a positive carry proxy. Compare TLT buy/hold and cash; show slope-regime occupancy, stale-observation decisions and duration exposure. Do not fit a new slope cutoff or term-premium model.

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
**one final at 10 bp** in canonical family `c16`. Failed/interrupted
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

A steep curve can coexist with a sharp selloff in long bonds. TLT can gap, and the kill/daily halt may veto liquidation after damage occurs. Rate exposure overlaps C10 and any bond allocations. Vintage errors can create look-ahead; unproven first-availability must not be backfilled from current FRED values.

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

- [Federal Reserve term-structure model Q&A](https://www.federalreserve.gov/data/three-factor-nominal-term-structure-model.htm): term premium separates yields from expected short rates; a 10y–2y slope is not that decomposition. This supports the interpretation limit, not the trading threshold.
- [DGS10](https://fred.stlouisfed.org/series/DGS10) and [DGS2](https://fred.stlouisfed.org/series/DGS2) identify daily H.15 constant-maturity yields in percent. [ALFRED download documentation](https://alfred.stlouisfed.org/help/downloaddata) distinguishes observation dates, specified vintage dates and real-time periods, including date snapshots when no revision occurred. Page metadata were reviewed; no vintage panel or TLT return series was downloaded. Exact archived coverage remains the child bead's source work.

Before execution, verify source coverage, chronology, formula/tie behavior,
settled cash, unchanged risk vetoes and durable single-use final admission.

## 2026-10-02 source audit — no replay admitted

The frozen rules above are unchanged. **SIGNAL_EVIDENCE_GAP:** bounded public
ALFRED download attempts did not obtain a historical DGS10/DGS2 vintage panel.
This is an access/evidence limitation, not proof that the archive lacks history
or that any historical decision should have held cash. No revised-value fallback.

TLT passes the original price standard: all 5,218 sessions retained; 2,509/2,511
paired returns agree within 5 bp (99.92035%), with two discrepancies and 2,706
unpaired returns retained. Reused C10 source SHA-256
`0580a449609e4a6597d6ac1d8988c349e60c87473e9c4aded6e50b16e4d7ddbd`;
its 22 input files were revalidated and the comparison recomputed from stored
prices/references. No C10 result or final was replayed.

The immutable local `data/research/c16-yield-curve/audit.json` SHA-256 is
`73a244f31364331b31528fe5dd998f7bb779b779fcc6bf2be82e47a13fa8ea7f`.
It pins 25 inputs (the price bundle, its 22 inputs and two investigation records)
plus four code files. **29 focused checks pass**, covering causal-evidence
classification, null performance, immutable prices/evidence, time bounds and
idempotent ledger recording without orders/fills or a final spend.

All four threshold/cost training configurations remain **unattempted**; there is
no selected winner or C16 final. Source-gap **trial 5648 / strategy 10570** was
recorded after source freeze `2d1face`, with every performance field null.
Stored-only verification confirmed no orders/fills or C16 final spend.
Results and account-risk decision are
in `43-c16-yield-curve-results.md`. Actual allocation $0; no promotion.
