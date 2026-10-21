# C19: Correlation-conditioned stock/bond/gold allocation — preregistration

2026-10-02, OrangeCove. Parent `tradingbot-y74`; candidate bead `tradingbot-n7j`.
**Status:** rules frozen before new candidate outcomes; actual allocation $0.
Research rank/priority **3 / P2**, rubric E/P/C/R **1/2/3/1** (0–3, higher better).
Gates 1/2 pass (concrete rule/testable mechanism); gate 3 is conditional on free
price evidence and eventual fractional eligibility. Verdict: **pursue bounded
research**, with no profitability, paper fidelity or live-readiness claim.

## Hypothesis, universe and fixed rules

**Hypothesis and distinction:** bonds' diversification role may depend on stock/bond co-movement; when that role deteriorates, gold may be a better defensive allocation. Neither positive correlation nor gold's hedge role predicts certain profit. This selects the hedge using cross-asset covariance, not C03's return ranking or C04's SPY variance scaling.

**Universe:** traded SPY, IEF, GLD; cash only for warm-up, risk vetoes and execution constraints.

**Signal and ordered variants:** **63**, then **126** completed daily returns. At each month's final regular-session close compute ordinary Pearson correlation of SPY and IEF simple adjusted returns over exactly L aligned observations (L+1 closes), all inside the partition. Both sample standard deviations must be positive. Target B/2 in SPY and B/2 in **GLD if correlation > 0, otherwise IEF**; equality selects IEF. No smoothing, correlation threshold search, trend filter, risk parity or vol targeting. Before warm-up, or if mathematically undefined, target cash and record the reason. Rebalance monthly; no daily signal updates.

**Failure and diagnostics:** trailing correlations are noisy and can change after the decision. Compare initial 50/50 SPY/IEF buy/hold, 50/50 SPY/GLD buy/hold, SPY buy/hold and cash on the same partition. Keep the 50/50 benchmark weights fixed at inception; no hindsight best-hedge comparator. Report bond/gold state counts and turnover. This is a diversification hypothesis whose acceptance still uses the owner's after-fee profit rule, not a newly invented drawdown gate.

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
**one final at 10 bp** in canonical family `c19`. Failed/interrupted
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

Stocks, bonds and gold can all fall during a liquidity or inflation shock. A hedge switch can sell low and buy high; settlement delays can leave temporary cash. The permanent equity half concentrates losses with C01/C02/C03/#6, and the chosen defensive fund can correlate with other bond/gold sleeves. Correlation estimates are not guaranteed protection.

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

- [Lombardi and Sushko, BIS, The correlation of equity and bond returns](https://www.bis.org/publications/correlation-equity-and-bond-returns): discusses inflation-related changes in stock/bond co-movement and their implications for diversification. It does not validate selecting GLD, a zero cutoff or our 63/126-session estimators; those were independently frozen before this source review. Gold is an unproven replacement hedge in this specification.

Before execution, verify source coverage, chronology, formula/tie behavior,
settled cash, unchanged risk vetoes and durable single-use final admission.

## Source and implementation freeze before outcomes (NavyLantern)

All **5,218** sessions per fund, 2006-01-03 through 2026-09-30, pass full primary
calendar coverage. The original C03 Yahoo captures are reused unchanged for
SPY/IEF/GLD; no new candidate price endpoint or paid data was needed. SPY/IEF use
Nasdaq split closes times Alpaca-only all/split factors; GLD uses independently
adjusted Alpaca SIP closes directly. No primary factor or price repairs are made.

| Fund | Paired returns | Within 5 bp | Discrepancies | Unpaired earlier returns |
|---|---:|---:|---:|---:|
| SPY | 2,512 | 99.880573% | 3 | 2,705 |
| IEF | 2,512 | 100% | 0 | 2,705 |
| GLD | 2,700 | 99.037037% | 26 | 2,517 |

Paired SPY/IEF returns start 2016-10-03 and GLD 2016-01-05; all end 2026-09-30.
GLD passes narrowly, with all 26 disagreeing days retained. Earlier years have no
independent comparison; the full registered sample/cutoff remain unchanged.
Every discrepancy, unmatched date and all **27 input hashes** remain in
`data/research/c19-total-return/source.json`:
`65e1fa75f5fd805fc7528eb83fbd536ccd0f8e1e2de304d6bac33188dc2da93b`.

- Canonical 22-dependency-map SHA-256: `b05b4512b5288c76643cc95355441941617073a8f0e1c5f5bb0cdb1243d6c876`.
- Reactor `src/tradingbot/strategy/c19_correlation.py` SHA-256:
  `14474a0335bb4f424e6d950e4fecded956011f58cdc5e757ddc90e1c8feb5eba`.
- Replay `src/tradingbot/research/c19_total_return.py` SHA-256:
  `b11726966a33e199216551efd4ebcfbc4111a97061a3e3d14fd852b99851d212`.

**47 focused checks pass**: ordinary return correlation including positive,
negative, zero and undefined branches; exact 63/126 lookbacks; partition-local
warm-up/intraday cutoff; frozen equal halves/reserve; pro-rata settled cash;
obsolete-hedge reduction before delayed replacement; adverse-price full-target
cap; undefined correlation returning to cash; atomic cross-fund marks; terminal
liquidation; unchanged kills retaining rejected exits; pre-feed final admission,
selected-version mismatch and repeated-final/family-window refusal. Tests use
synthetic observations and isolated trial rows; no real C19 strategy outcome
has run. Shared risk/ledger code and all earlier family finals stay unchanged.

The original allocation/cost/rule sections above remain authoritative. Execution
is the registered adjusted-unit/current-account fee and settlement scenario;
exact broker fractional fills/actions and full advance-notice calendar provenance
are not established. One exact training selection must be committed here before
one canonical `c19` final at 10 bp. Actual allocation **$0**.

## Exact selection committed before the single final

Four fixed trials **5642–5645** completed positive, flat and rejection-free. All
have the identical dependency map frozen in `1963400`; the last trial's commit
is `0af26b5`, an unrelated C16 claim/log update with unchanged research code.
The prescribed highest positive complete 10 bp training net selects **126
sessions**, trial **5645**, strategy **10567**, net **+$143.02660090059157671**:

- Selected version: `0e30d4d2c81c95d15c4e6381716f3fab97eaf4f51a40883fbe83ce7d5d731f57`.
- Selected training artifact: `9417d48a87b7aef2d840955bc5af017bbba6b8571661778e4aab3bca0a10107f`.
- Selection receipt `data/research/c19-total-return/selection.json` SHA-256:
  `fbbb75631a1035e1402666f7b700a63f40a2f02e032fca20571e28effbe16d21`.
- Stored-only training reconciliation SHA-256:
  `417da91c5cf2f6a1f743bacd57c8378238b8fc422167d24410608d2c12eec014`.

Stored fills independently reconcile adverse prices, full-target/slot caps,
frozen cash reserves, unsettled sale proceeds, fees, net, flat holdings and
monthly marked totals/drawdown. Canonical **c19 has zero final receipts** at this
point. Exactly this selected version may consume one 10 bp final; failed or
interrupted admission remains spent. No parameter was added or tuned. Actual $0.

## Final disposition

The sole canonical `c19` final was admitted as **trial 5646**, strategy **10568**,
under exact selection commit `1a1e833` and the selected version above. It completed
at **+$81.704996** net with **19.28%** peak drawdown, 11 round trips / 102 fills,
flat ending and zero rejected orders/halts. The final is permanently consumed.
Artifact SHA-256 `1a038d1266625a09c445a5fdb2e9718932d7b22c506ed7be2c6d7bdab4ae6ba5`.
The sole [results file](43-c19-correlation-hedge-results.md) records full regimes,
benchmarks, sparse-cluster limitation, fees/execution and account-risk review.
Historical after-fee profit criterion met; remain in backtest pending paper
fidelity, actual **$0**, with no funded promotion or live activation.
