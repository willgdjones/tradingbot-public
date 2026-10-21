# C20: Conditional January small-cap recovery — preregistration

2026-10-02, OrangeCove. Parent `tradingbot-y74`; candidate bead `tradingbot-6f0`.
**Status:** rules frozen before new candidate outcomes; actual allocation $0.
Research rank/priority **6 / P3**, rubric E/P/C/R **2/1/3/1** (0–3, higher better).
Gates 1/2 pass (concrete rule/testable mechanism); gate 3 is conditional on free
price evidence and eventual fractional eligibility. Verdict: **pursue bounded
research**, with no profitability, paper fidelity or live-readiness claim.

## Hypothesis, universe and fixed rules

**Hypothesis and distinction:** tax-loss selling followed by its reversal may create turn-of-year pressure in small stocks. Applying stock-level tax-loss arguments to a diversified ETF is explicitly weaker. This is an annual conditional small-cap event, not the dead pre-holiday SPY idea, unconditional overnight drift or C07's weekly sector reversal.

**Universe:** IWM traded, SPY reference only, cash otherwise.

**Signal and ordered variants:** holding H = **5**, then **10 session intervals**. At December's final regular-session close, compute December total returns of IWM and SPY using that close and the previous November's final close, all inside the partition. Qualify only if IWM's December return is **strictly negative and strictly below SPY's**. Otherwise no January position. For a qualifying year, buy at the next regular open S (January's first session) and exit at the original S+H session open: sixth/eleventh January session for H=5/10. At most one entry per year. No size, tax-law, December-loss magnitude or January-price filter. Freeze entry budget and exit at decision; a cash-delayed entry must precede that original exit, never restart H.

**Failure and diagnostics:** tax-loss pressure may have migrated away from a broad ETF or been arbitraged away. December weakness may signal continuing economic deterioration. At most 14 training and six final January events exist before the condition; the resulting cluster p-value will be null under the common reporting minimum. Report qualified/all-year counts, missed events, per-year net and exposure; compare IWM/SPY buy/hold and cash. This can be evaluated mechanically within 60 days, but cannot establish the seasonal effect statistically in that time. No extra years, replacement dates or pooled unrelated events to inflate the sample.

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
**one final at 10 bp** in canonical family `c20`. Failed/interrupted
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

Small-cap liquidity and overnight gaps can magnify losses during a continuing selloff. A January open is not a guaranteed fractional auction fill. Sparse annual events make a lucky result especially easy to mistake for an edge; the −40% kill and −$50 daily halt do not replace that uncertainty. IWM remains equity-beta exposure correlated with the other stock sleeves.

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

- [Poterba and Weisbenner, NBER Working Paper 6616](https://www.nber.org/papers/w6616): studies tax-loss incentives and turn-of-year stock return patterns. The tax regimes, individual-stock losses and sample differ from our December ETF qualifier.
- [Constantinides, NBER Working Paper 1176](https://www.nber.org/papers/w1176) supplies a counterpoint: tax-trading volume seasonality need not establish the small-firm price premium. Broad-IWM applicability is therefore not assumed. Primary indexed abstracts were reviewed; direct page opens failed. No historical candidate trade or current tax advice is inferred.

Before execution, verify source coverage, chronology, formula/tie behavior,
settled cash, unchanged risk vetoes and durable single-use final admission.

## Source and code freeze (BoldValley, 2026-10-02)

The unchanged rule sections above were frozen in `62f30fa`. The immutable C20
source bundle was captured and cross-checked before any strategy outcome.

- **Source SHA-256:** `58175627d2bc45813bffe95f24722c380640efdad477295250f5a318247824c7`
  (`data/research/c20-january-small-cap/source.json`). The `data/` tree is
  gitignored; the bundle is reproduced from the pinned raw inputs and verified by
  this hash and the per-input SHA-256 map it contains.
- **Primary:** Yahoo split/dividend-adjusted daily closes, raw-open × adj/close
  factor for opens, **5,218 sessions per fund** 2006-01-03 … 2026-09-30.
- **Second source:** free Nasdaq split-adjusted close × Alpaca all/split dividend
  factor (the C09 route). Nasdaq deep history and Stooq were both unavailable as
  direct series on the capture date; the admissible Nasdaq-close × Alpaca-factor
  route covers **2016-10-03 onward (2,511 paired return days)**. Paired-day
  agreement at 5 bp: **IWM 99.920350%, SPY 99.880526%** — both pass the 99%
  standard. The pre-2016 interval (2,706 unmatched dates) is single-source Yahoo
  and is disclosed, never resliced or backfilled. Every disagreement and
  unmatched date is retained in the source bundle.
- **Frozen code:** `src/tradingbot/strategy/c20_january_small_cap.py`,
  `src/tradingbot/research/c20_january_small_cap.py`,
  `src/tradingbot/strategy/c05_commodity_trend.py`, and the shared
  total-return/backtest/ledger/risk dependencies hashed in the training and
  selection artifacts.
- **Elapsed 70/30 split:** `2020-07-10T14:24:00Z` via the shipped `HoldoutSplit`.

Four main training trials (H=5, H=10 × 5 bp, 10 bp) and, if a positive complete
flat rejection-free 10 bp training case exists, one 10 bp final follow. The
selected trial/version/receipt is pinned below before the final is run.

### Training outcome and selected final (pinned before the final)

Four training trials completed, flat, rejection-free, all positive after costs;
3 of 14 evaluated Decembers qualified (IWM December return strictly negative and
below SPY). Net after all modeled costs: H5 **+$3.087** (5 bp) / **+$2.669**
(10 bp); H10 **+$1.702** (5 bp) / **+$1.287** (10 bp).

Selection rule — highest positive complete flat rejection-free **10 bp** training
net, listed-variant order breaking ties — picks **H=5**.

- **Selection SHA-256:** `3effe967e777f010c38577cd757e7f0898f619bc65fbb28832852d79a558bee9`
  (`data/research/c20-january-small-cap/selection.json`).
- **Selected trial:** `5683` (H=5, 10 bp training).
- **Selected/final strategy version:** `3325d02132fb44f3f9115604896d0ee249b26b2b8c86e38463ea87ab5af45c07`.

Exactly one 10 bp final in canonical family `c20` follows at the selected
version; no second-cost, sibling or cosmetic final may reuse it.

