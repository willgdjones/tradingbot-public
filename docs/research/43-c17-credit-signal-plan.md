# C17: Credit-market signal for equity exposure — preregistration

2026-10-02, OrangeCove. Parent `tradingbot-y74`; candidate bead `tradingbot-t87`.
**Status:** rules frozen before new candidate outcomes; actual allocation $0.
Research rank/priority **2 / P2**, rubric E/P/C/R **1/2/3/2** (0–3, higher better).
Gates 1/2 pass (concrete rule/testable mechanism); gate 3 is conditional on free
price evidence and eventual fractional eligibility. Verdict: **pursue bounded
research**, with no profitability, paper fidelity or live-readiness claim.

## Hypothesis, universe and fixed rules

**Hypothesis and distinction:** credit investors' changing risk appetite may precede or accompany equity risk premia. The predictive step is a hypothesis, not established by a contemporaneous credit/equity relationship. Unlike C01/C03, the traded fund's own return does not choose the position.

**Universe:** SPY traded, cash otherwise; HYG and IEF are reference ETFs only. Use actual adjusted ETF prices, not a backfilled high-yield index. The 2008 start avoids needing pre-launch HYG history; confirm inception metadata without changing the interval.

**Signal and ordered variants:** **63**, then **126** exchange-session returns. At each month's final regular-session close t, require L+1 complete same-session adjusted closes for HYG and IEF inside the partition. Compute `score = (HYG[t]/HYG[t-L]-1) - (IEF[t]/IEF[t-L]-1)`. If strictly positive, target B in SPY; otherwise target zero. Equality means cash. No SPY trend filter, credit-spread regression, duration scaling or threshold product. Rebalance monthly and retain holdings between decisions.

**Failure and diagnostics:** HYG minus IEF is not a duration-neutral credit spread; coupons, rates, bond-ETF price/NAV differences and liquidity can drive it. Compare SPY buy/hold and cash; report risk-on months, equity exposure and false exits/re-entries. Simultaneous observed co-movement does not establish lead-lag or incremental forecasting power.

## Frozen data, cash and execution contract

- **Interval:** `2008-01-01T00:00:00Z` inclusive to
  `2026-10-01T00:00:00Z` exclusive. **Final starts `2021-02-14T14:24:00Z`**,
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
**one final at 10 bp** in canonical family `c17`. Failed/interrupted
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

SPY can crash before bond ETFs indicate trouble, and high-yield/stock risk can fail together. Fixed next-open slippage may understate stressed costs. HYG/IEF tracking and asynchronous underlying bond marks can produce misleading signals. This remains SPY directional risk correlated with existing equity sleeves.

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

- [Federal Reserve, Updating the Recession Risk and the Excess Bond Premium](https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html): a credit-spread component is interpreted as credit-investor risk appetite. The paper's EBP is neither our HYG-minus-IEF total return nor proof of a next-month SPY rule. This is a deliberately low-evidence cross-market adaptation, with that gap retained in the rubric.

Before execution, verify source coverage, chronology, formula/tie behavior,
settled cash, unchanged risk vetoes and durable single-use final admission.

## Source and code freeze before outcomes (2026-10-02, NavyLantern)

The original rule section remains unchanged. HYG launched 2007-04-04 according
to [iShares](https://www.ishares.com/us/products/239565/hyg-ishares-iboxx-high-yield-corporate-bond-etf),
before the registered 2008 start. All three primary funds have **4,716 sessions**
from 2008-01-02 through 2026-09-30, with no missing/extra calendar session.
SPY/IEF reuse the original C03 Yahoo bytes; HYG is a new free Yahoo capture.
The reference uses Nasdaq closes times Alpaca-only all/split adjustment factors,
with no Yahoo inputs in the reference. No paid endpoint was invoked.

| Fund | Paired returns | Within 5 bp | Disagreements | Unpaired earlier returns |
|---|---:|---:|---:|---:|
| SPY | 2,512 | 99.880573% | 3 | 2,203 |
| HYG | 2,511 | 99.840701% | 4 | 2,204 |
| IEF | 2,512 | 100% | 0 | 2,203 |

Paired returns begin 2016-10-03 (SPY/IEF) or 2016-10-04 (HYG) and end
2026-09-30. This accepts the registered paired-day comparison; it does not
independently validate 2008–2016. All discrepancies and unmatched dates remain
in `data/research/c17-total-return/source-audit.json` and the source bundle.
The full interval and 2021-02-14T14:24:00Z cutoff remain unchanged.

- Source: `data/research/c17-total-return/source.json`, SHA-256
  `24bd6879c9793e9d20772807bf93d31ed9c74cff7646dc378196e69d112b59ec`; 34 hash-verified input files.
- Price audit SHA-256: `668cc259f722c86386b1fe0437d98654bdffc9c1fe8def4e33d7a58a24dbeb20`.
- Canonical dependency-map SHA-256: `a116aaddb5c48ec10febf9a167c7d3666b4405e25fe3f76dfea82f6da5a18311`.
- Reactor: `src/tradingbot/strategy/c17_credit.py`, SHA-256 `79e2dd9fd31e67c7f88c1b6b7e0ce79a74e34a2dd0d6a0fed190a79bfa88ef6d`.
- Replay: `src/tradingbot/research/c17_total_return.py`, SHA-256 `0d62acc2cb71c4ec60d17e0e13bc1cae773845651abbdf9e694bcabc3b64084a`.

**41 focused checks pass**: exact lookbacks/equality, same-session references,
partition-local warm-up and intraday cutoff, frozen target/reserve, delayed
settled-cash additions, adverse-price full-position cap, terminal liquidation,
raw-equivalent fee/shared-ledger integration, retained rejected exits under
unchanged kills, pre-feed final admission, selected-version mismatch, repeated
final refusal and shared family-window guards. Tests use synthetic prices and
rollback-isolated trial rows; no real candidate training/final has run yet.

Same pure reactor/shared risk/ledger runs the research. Actual broker/fractional
fills and historical announcement-time calendar provenance are not established;
execution is the registered total-return/current-account approximation. The
optional corporate-action blackout is omitted. Final selection and receipt must
be committed here before the one canonical `c17` final. Actual allocation **$0**.

## Exact training selection committed before the final

All four fixed cases completed in source/code commit `52d6cc0`, trials
**5583–5586**, flat with zero rejected orders/halts. Highest eligible 10 bp net
selects **126 sessions**, trial **5586**, strategy **10466**:

- Net **+$160.1503621745726949300000001**, 11 round trips / 84 fills.
- Selected strategy version `e82f93d1b3178ff06f1feedeaf74dbea0874eb9df3abd13bc84ed1bbc52f16ce`.
- Selected training artifact SHA-256 `998713db2f14e50ad685c7101e8b914f66ee5526bc68c40b9e187b29e97b973e`.
- `data/research/c17-total-return/selection.json` SHA-256 `ae2102bd61b482f2e79394fece987aa92abe2c4a7f2c63b785757da28db94851`.
- Stored-only reconciliation SHA-256 `76d37a7cd6a44b649742462b927f692756e3777e562b3e2fe9002ef799dc871c`.

The selection includes every variant/cost attempt, source/dependency identities
and the exact split. It was recomputed from durable training records without
constructing a final feed. Canonical `c17` has **zero final receipts** at this
point. Only this version may consume the single 10 bp final; failure remains
spent. No second-cost or sibling final. Allocation stays **$0**.

## Final disposition

The single canonical `c17` final was admitted as **trial 5587**, strategy 10467,
under exact selection commit `6a1db85` and the selected strategy version above.
It completed at **+$45.485000** net with **33.15%** peak drawdown, nine round trips,
32 fills, flat ending and zero rejected orders/halts. It is consumed permanently.
Final artifact SHA-256 `208e2e082d77047e364d51e2c87d0596db7afa2dbd0356b75421bbb842696d91`.
See the sole [results file](43-c17-credit-signal-results.md) for regimes, account
risk and receipts. **Hold in backtest, actual $0**; no funded promotion.
