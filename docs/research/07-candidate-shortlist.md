# Alpaca strategy sweep: eight preregistered candidates

Desk review: 2026-09-30 America/Los_Angeles / 2026-10-01 UTC. Parent bead:
`tradingbot-cfe`. This follows the owner's new **Current priorities** and PRD
§3–§4. No candidate returns were calculated, no holdout was consumed, and no
orders or capital transfers were made. Rankings describe research value, not
expected investment returns.

## Decision and ranking

Pursue eight bounded research candidates, each as a P2 `strategy,sweep` bead
depending on `tradingbot-zgn`. Four use equity/asset-allocation effects, two test
commodity exposure, and two test institutional flows/liquidity provision.
Options and AI ideas were considered but do not yet have adequate executable
data or a frozen decision rule. Existing #6 belongs to `tradingbot-gat`; failed
#5 is not recycled into this list.

Rubric: [strategy intake](../strategy-intake/README.md), in its stated order.
Gates 1/2/3 mean concrete rule / plausible mechanism / account-data feasibility.
All eight have specified rules and testable mechanisms. Gate 3 is conditional
on the data checks below; a failed check parks that candidate before a replay.
For gates 4–7, scores are **0–3**, higher better: evidence quality (E), ability
to evaluate with available history (P), low implementation/data cost (C), and
manageable failure exposure (R). Scores are judgments, not statistical results.

| Rank | ID / bead | Candidate | Gates 1/2/3 | E/P/C/R | Total | Research verdict |
|---|---|---|---|---|---|---|
| 1 | C01 / `tradingbot-8yz` | SPY monthly trend | pass/pass/conditional | 3/2/3/2 | 10 | Pursue; simplest reusable baseline |
| 2 | C02 / `tradingbot-7l3` | Sector relative momentum | pass/pass/conditional | 3/2/3/2 | 10 | Pursue; fixed nine-sector ETF universe |
| 3 | C03 / `tradingbot-wn9` | Cross-asset relative momentum | pass/pass/conditional | 3/2/3/2 | 10 | Pursue; same momentum family, different exposures |
| 4 | C04 / `tradingbot-wri` | Cash-capped inverse-variance SPY | pass/pass/conditional | 3/2/3/2 | 10 | Pursue; no leverage or fitted full-sample scale |
| 5 | C05 / `tradingbot-9ri` | Long/cash commodity ETF trend | pass/pass/conditional | 2/2/3/1 | 8 | Pursue; actual ETF roll/holding effects matter |
| 6 | C06 / `tradingbot-kc4` | Month-end stock/bond underweight flow | pass/pass/conditional | 2/1/3/2 | 8 | Pursue; long-side proxy, not paper replication |
| 7 | C07 / `tradingbot-a9d` | Weekly sector loser reversal | pass/pass/conditional | 2/2/2/1 | 7 | Pursue; high turnover may erase the effect |
| 8 | C08 / `tradingbot-m2d` | USO inventory scarcity | pass/pass/conditional | 2/1/1/1 | 5 | Pursue data audit first; stop if vintages fail |

Ties favor simpler implementation. C01/C03/C05 share trend exposure; C02/C03
share relative momentum. These are eight candidate families, **not eight
independent diversification sources**. The 23 signal variants and two training
cost cases below are 46 planned training configurations, including failures.
Log any additional diagnostic or changed parameter set as another trial.

## Common preregistration: binding on all eight beads

### Data and account feasibility

- Free daily ETF data: Yahoo raw OHLC plus split/distribution events and adjusted
  close; Stooq daily history is a cross-check, not an assumed total-return
  substitute. Existing free Alpaca IEX data supplies an independent overlap
  check from 2016 and forward quotes. Do not silently switch feeds or join
  mismatched adjustments. Archive responses, retrieval times, adjustment rules,
  missing sessions and hashes before calculating strategy returns. No premium
  endpoint, subscription, new account or key is authorized.
- Dataset intervals below are **UTC, end exclusive**, fixed before fetching
  candidate outcomes. Validate coverage without inspecting return summaries.
  Missing corporate actions, unresolvable source disagreement or inadequate
  history means a recorded data failure; do not move the start/end or swap
  tickers to rescue a result. Any necessary revision gets a written amendment
  before outcome inspection. No synthetic pre-inception ETF history.
- A [read-only asset snapshot](sweep-sources/2026-09-30-alpaca-assets.json) found
  all 18 named ETFs active, tradable and fractionable on the paper API. This
  establishes present paper metadata, not historical or live-account
  eligibility. Recheck at execution. Alpaca documents fractional DAY orders and
  per-asset eligibility; its Basic plan has IEX equities and indicative options.
  [Fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading),
  [market-data plans](https://docs.alpaca.markets/us/docs/about-market-data-api).
- Simulate **$140 starting allocation**, target at most **95% ($133 initially)**
  in owned long ETF shares, and keep the rest as non-interest-bearing cash.
  Weights use current strategy equity, subject to the actual allocation cap,
  settled cash, fees and the unchanged risk engine. No leverage, short sale,
  inverse ETF or assumed cash yield. Fractional quantities round down to venue
  precision; orders below $1 are skipped and counted. This sizing is a strategy
  parameter, not a change to §6.

### Causal execution, fees and cash

Signals use only completed observations. Monthly rules decide after the final
regular-session close unless a candidate specifies a different decision date
(C06). The next eligible regular-session open is the historical
execution reference, with **5 bp and 10 bp adverse cost per side** as the two
fixed training cases. They are assumptions, not measured spreads or promises of
fractional auction fills. Use the existing `EquityFeeBook` dated September 17,
2026 as an explicit current-fee historical counterfactual, including rounding;
never call it recovered historical actual fees. ETF operating expenses and roll
effects are already reflected in actual ETF prices and must not be subtracted
twice. Credit dividends only when entitled, with spendable cash on payment date;
adjusted closes used for signals are not executable prices or a second dividend.

At rebalances, submit reductions at session S's reference open. Use only cash
already settled before S for same-day additions; cash from those reductions
funds remaining additions at the next settlement-eligible session's open. Freeze
the signal and dollar targets using decision-time marked strategy equity;
delayed purchases do not recompute targets from later equity. At each execution,
subtract already owned value from each frozen dollar target. Ration spendable
cash pro rata across positive target gaps, after estimated fees and the 5% of
decision-equity cash reserve. Skip sub-$1 orders without redistributing their
allocation. Actual quantity uses available cash and execution price. Retain
unchanged quantities unless the fixed weight rule requires a rebalance. Unknown
settlement calendars, missing execution bars or cash shortfalls are reported,
never filled with future values. Model T+1 throughout as a **current-account
counterfactual**, not the settlement rule that prevailed in every historical
year. Real forward orders require fresh IEX observations under §6; a daily bar
cannot override the 30-second stale-data rule.

### Locked 70/30 evaluation

The [candidate index](sweep-sources/2026-09-30-candidate-index.json) records these
exact UTC boundaries computed with `HoldoutSplit`; warm-up stays inside each
partition. All datasets end at `2026-10-01T00:00:00Z`.

| Candidates | Full source start | Holdout starts |
|---|---|---|
| C01–C04, C06–C07 | 2006-01-01 00:00:00Z | 2020-07-10 14:24:00Z |
| C05 | 2008-01-01 00:00:00Z | 2021-02-14 14:24:00Z |
| C08 | 2018-01-01 00:00:00Z | 2024-02-15 12:00:00Z |

1. Use `HoldoutSplit(dataset_key, full_source_start, exclusive_end)` from
   [the shipped holdout API](../../src/tradingbot/backtest/README.md). Its boundary
   is 70% of **elapsed UTC time**, not row count, trade count or a shuffled split.
   The dataset identity covers all ETF/macro sources and adjustment policies.
   Store the exact computed cutoff in the manifest before any return analysis.
2. Only the first 70% may be used for development and the listed variants. Start
   each partition flat; keep its warm-up bars inside that partition and remain
   in cash until the required history exists. No open trade, outcome label or
   full-sample normalization crosses the boundary. Drop a planned round trip if
   its exit would be outside the partition. Standing allocations are liquidated
   at the final eligible reference open, with fees, as a fixed terminal rule;
   do not open a new position there. Report terminal liquidations separately.
   Timestamp a daily bar at its actual session close/availability, not a vendor's
   midnight date label; an intraday cutoff cannot admit that day's later close
   into training. Each decision's required observations must be in its partition.
3. Record every attempted configuration, data failure and code/parameter change
   in the trials ledger. Select **one variant per candidate** using highest
   training net dollar P&L in its **10 bp** case; ties use variant order below.
   If none is profitable after fees, record the family as failed and do not
   consume a holdout. Training 5 bp results are sensitivity diagnostics only.
4. Commit the strategy, source manifest, training results and frozen choice.
   Put all signal/calendar/sizing settings in `Strategy.params`, and costs in
   `version_params`. Run that frozen choice **once on the last 30%, at 10 bp**.
   No second cost replay, sibling-variant sweep, renamed run or cosmetic version
   change may recycle that holdout. Failed/interrupted final attempts remain
   consumed; the engine refuses reuse and records an incident. Positive net P&L
   is required in both partitions under PRD §4.
5. Be honest about prior inspection: SPY/QQQ history used by earlier #5/#6 work
   is not fresh unseen evidence merely because it is put in a new archive.
   Record overlap with previously inspected data and published sample-selection
   bias. A mechanically correct 70/30 run on contaminated data is diagnostic;
   it does not justify claiming an untouched holdout or promotion. Preserve a
   genuinely unseen subsequent period for confirmation when needed.

Predeclare daily marked-equity drawdown, gross/net P&L, all fees, turnover,
completed round trips, exposure, cash delays, rejected/skipped orders and luck
p-value. Report calendar years plus 2006–2009, 2010–2019, 2020–2021, 2022 and
2023–2026 where covered, without tuning against them. Benchmarks are diagnostic
returns computed from the same replay observations, not executable strategies
eligible for promotion: SPY buy-and-hold, equal-weight buy-and-hold of the fixed
universe, and zero-yield cash. They expose market beta; positive raw P&L does not
establish incremental alpha. Cluster inference by week/month and account for
serial dependence; do not count simultaneous ETF legs as independent bets.
Insufficient independent trades means a null/unreliable p-value, not fabricated
precision. No additional p-value or Sharpe promotion gate is imposed.

At mean/standard-deviation = 0.10, a simple independent-observation approximation
needs `(1.96 / 0.10)^2 ≈ 384` observations for a two-sided 5% test. This is a scale
illustration, not a power guarantee. Twenty years gives only about 240 months;
two months of forward observation cannot establish a slow factor's edge. The
60-day objective is to finish a historical evaluation and execution check, not
promise statistical certainty or manufacture trades.

## Candidate specifications

### C01 — SPY monthly trend

**Hypothesis:** gradual adjustment creates persistent equity trends; a long/cash
monthly rule can retain positive net returns while avoiding some prolonged
declines. Faber's monthly SMA rule motivates this test, but his index results
do not establish actual SPY next-session returns after our costs.
[Author paper, pp. 20–21](https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf).

**Rule / variants:** SPY only. At month-end, hold target weight 95% if adjusted
close exceeds the arithmetic mean of the last L month-end adjusted closes,
including that close; hold cash otherwise. Equality retains the previous state.
Variant order: **L=10, 8, 12 months**. Retain a held position between decisions;
execute entries, exits and weight adjustments under the common cash rules.
**Data:** free daily SPY bars/actions, **2006-01-01 to 2026-10-01**.
**Failure:** whipsaw costs, crash before monthly exit and missed rebound. Long
holding spells mean few independent round trips. Compare exposure/drawdown with
SPY, and do not call simple market appreciation timing alpha.

### C02 — Sector relative momentum

**Hypothesis:** industry-level slow adjustment makes relative winners persistent.
The academic industry effect and Faber's top-N rotation motivate an ETF
adaptation, not a reproduction of a long/short stock portfolio.
[Moskowitz–Grinblatt](https://onlinelibrary.wiley.com/doi/full/10.1111/0022-1082.00146),
[Faber, pp. 5–6](https://mebfaber.com/wp-content/uploads/2018/12/SSRN-id1585517-Relative-Strength-Strategies-for-Investing.pdf).

**Rule / variants:** fixed XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY. Rank at
month-end; hold top three equally within the 95% total weight. Alphabetical
ticker order breaks ties. Replace names leaving the top three; rebalance weights
monthly. Scores, in variant order: **12-month total return; 6-month return;
mean of 1/3/6/9/12-month returns**. No skip month or extra trend filter.
**Data:** free daily nine-ETF bars/actions, **2006-01-01 to 2026-10-01**.
**Failure:** momentum crashes, sector concentration and turnover. The fixed
legacy nine-fund universe excludes later XLRE/XLC and is not today's complete
sector set; disclose classification changes without retroactively adding funds.

### C03 — Cross-asset relative momentum

**Hypothesis:** relative trends across risk exposures persist long enough to
justify infrequent rotation. Faber applies relative strength to multiple asset
classes; using GLD instead of broad commodities is our explicit adaptation.
[Author paper, pp. 12–17](https://mebfaber.com/wp-content/uploads/2018/12/SSRN-id1585517-Relative-Strength-Strategies-for-Investing.pdf).

**Rule / variants:** fixed SPY, IEF, GLD, EFA, VNQ. At month-end rank mean
1/3/6/9/12-month total return; alphabetical ties. Variants: **top one at 95%;
top two equally at 47.5% each; top two with each selected half held in cash unless
that ETF exceeds its 10-month SMA**. A failed filter does not promote rank three.
Rebalance monthly and apply common settlement delays on replacements.
**Data:** free daily five-ETF bars/actions, **2006-01-01 to 2026-10-01**.
**Failure:** winner concentration, duration shocks and simultaneous stock/bond/
REIT losses. C02/C03 share selection risk; GLD is not a diversified commodity
basket. No claim of independent alpha from the extra candidate family.

### C04 — Cash-capped inverse-variance SPY

**Hypothesis:** reducing exposure when realized variance is high can improve
the return/drawdown profile because risk and expected returns need not rise
together. Moreira–Muir studies inverse-variance portfolios, including leverage
constraints; our fixed scale and cash cap deliberately differ from full-sample
risk-normalized academic results.
[Author paper, §II.C](https://law.yale.edu/sites/default/files/area/workshop/leo/leo17_moreira.pdf).

**Rule / variants:** after month-end compute `v = 252 * sample_variance` of SPY
daily total returns in that completed calendar month, requiring 15 observations
and a **full month's required closes/returns inside the partition**. Skip a
partial first month after an intraday cutoff rather than annualizing its subset.
Next-month target `min(0.95, c / v)`; invalid/nonpositive v means cash.
Variant order: **c=0.15², 0.10², 0.20²**. These are scaling constants, not promised
target volatilities. Rebalance monthly using settled cash; never estimate c from
the whole sample. **Data:** free daily SPY bars/actions, **2006-01-01 to
2026-10-01**. **Failure:** maximum exposure before a surprise crash followed by
de-risking before recovery; reduced market exposure can explain apparent gains
in risk-adjusted statistics. Shared SPY losses correlate with C01/C06.

### C05 — Long/cash commodity ETF trend

**Hypothesis:** commodity own-return persistence may survive in unlevered ETF
long legs. Time-series momentum evidence comes largely from futures portfolios;
ETF trading, long-only exposure and embedded roll costs are a substantive test.
[Moskowitz–Ooi–Pedersen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum).

**Rule / variants:** fixed GLD, SLV, USO, UNG, DBA. Five equal 19%-of-equity sleeves
inside the 95% aggregate target; inactive sleeves remain cash. After month-end,
each holds its ETF if its signal is positive. Variants: **252-session total
return >0; 126-session return >0; adjusted close above 200-session SMA**.
Equality means cash; no reallocation from inactive sleeves or parameter product.
Rebalance monthly. **Data:** free actual ETF bars/actions, **2008-01-01 to
2026-10-01**, with warm-up within each partition. Never use spot oil/gas as ETF
returns. **Failure:** roll losses, commodity gaps, reverse splits and changes in
fund holdings. Report USO's 2020 dislocation and later benchmark transition
separately; gas can lose quickly despite long-only sizing.

### C06 — Month-end stock/bond underweight flow

**Hypothesis:** scheduled balanced-fund buying supports equities when stocks
are underweight. Harvey–Mazzoleni–Melone documents rebalancing price pressure;
the widely quoted negative return for overweight stocks is not direct evidence
for this long-only proxy.
[Authors' paper](https://doi.org/10.2139/ssrn.5122748).

**Rule / variants:** SPY traded, IEF reference. At the **penultimate session's
close**, compute month-to-date total returns R_SPY and R_IEF from the previous
month's last close, then `w = .6*(1+R_SPY)/(.6*(1+R_SPY)+.4*(1+R_IEF))`.
If `w < threshold`, enter SPY at the final session's reference open with 95%
target weight. Exit at the first session's reference open next month. Variants:
**threshold=0.600, 0.595, 0.590**. Otherwise cash. No short overweight leg;
no use of the final day's close to choose that morning's trade.
**Data:** free SPY/IEF daily bars/actions and exchange calendar,
**2006-01-01 to 2026-10-01**. **Failure:** few qualifying months, institutional
timing drift, overnight gaps, and overlap with #6. Report qualifying versus
all-month-end benchmark windows to distinguish a flow condition from ordinary
calendar exposure. This scheduled-flow hypothesis does not revive the dead
unconditional overnight-drift strategy.

### C07 — Weekly sector loser reversal

**Hypothesis:** supplying liquidity after temporary industry selling pressure
may earn a short-lived premium. Nagel links short-term reversals and liquidity
provision, particularly in stress; the paper does not establish unconditional
profits for this long-only ETF rule.
[Primary research record](https://www.nber.org/papers/w17653).

**Rule / variants:** C02's fixed nine sector ETFs; SPY is the reference. Weeks
are Monday–Sunday in New York time. Each week's final exchange-session close
ranks `sector trailing 5-session total return minus
SPY trailing 5-session return`. Buy the three lowest **negative** residuals
(alphabetical ties), at 95%/3 each; missing eligible slots stay cash. Variant
order: **5-session lookback/top three; 10-session/top three; 5-session/top one
at 95%**. Initial entry targets the next week's first exchange-session open.
Exit at the first-session reference open of the subsequent week, even if a
name repeats. A settlement-delayed entry retains that originally scheduled exit.
New signals are frozen on the prior week's last session; sales
cannot finance new positions until T+1. Thus replacement entries can occur on
the week's second session; skip if entry would reach the scheduled exit.
**Data:** free sector/SPY daily bars/actions and calendar, **2006-01-01 to
2026-10-01**. **Failure:** information-driven losses continue, turnover/spreads
erase reversal, and delayed cash entries miss the effect. Count weeks, not ETF
legs, for dependence-aware inference. No VIX filter added after seeing results.

### C08 — USO inventory scarcity

**Hypothesis:** low physical inventories can support commodity risk premia.
Gorton–Hayashi–Rouwenhorst studies that relationship in futures; year-ago stock
thresholds traded through USO are a new, weaker proxy hypothesis.
[Primary paper](https://www.nber.org/papers/w13249).

**Rule / variants:** from each dated EIA Weekly Petroleum Status Report obtain
US commercial crude stocks **excluding SPR** and its comparable year-ago value.
`scarcity = current / year_ago - 1`. At the next trading session after actual
publication, enter USO at 95% target weight if scarcity is below the threshold,
otherwise hold cash. Reconsider weekly: cash-to-long sizes the entry, long-to-cash
sells all owned shares, and an unchanged state retains shares **without weekly
resizing**. Variants: **threshold=0%; -5%**. Positive denominators and comparable
units/definitions are mandatory. A missing release produces no new signal;
after 14 calendar days without a usable publication, target cash at the next
session. **Data:** dated EIA release tables + free USO bars/actions,
**2018-01-01 to 2026-10-01**.

**Data gate / failure:** the [EIA archive](https://www.eia.gov/petroleum/supply/weekly/archive/)
has separate release/observation dates and dated tables, including the
[2020-09-10 release](https://www.eia.gov/petroleum/supply/weekly/archive/2020/2020_09_10/wpsr_2020_09_10.php).
Audit original current/year-ago fields, corrections and comparable stock
definitions before returns. Never replace missing first-release evidence with
today's revised bulk series or assume every report arrived Wednesday. For
date-only release evidence, wait until the next calendar day's eligible session.
Inventory can be backward-looking; ETF roll exposure need not reward scarcity.
Disclose pre-2020, changed-2020 holdings, September-2023–January-2024 transition
and later exposure regimes from [USO's prospectus](https://www.sec.gov/Archives/edgar/data/1327068/000207187626000128/i26211_uso-424b3.htm).

## Parked and excluded ideas

| Idea | Rubric disposition and reason | Existing work / revisit condition |
|---|---|---|
| Cash-secured put / covered-call wheel | Reject for this slot unless full assignment collateral/shares fit. A standard 100-share put needs strike ≤$1.40 before fees to fit $140; that shifts toward poor liquidity/distress. Short-vol/VIX ideas are also on the dead list. | No new strategy bead or account permissions. |
| Long calls/puts | Park at gate 3. Premium plus fees can fit $140, but free indicative quotes and delayed derived trades do not prove executable historical spreads/fills; options are indivisible. Long premium can lose 100%, overshooting the kill. | `tradingbot-lwv` audits chains/quotes; only then specify an affordable rule. [Alpaca data](https://docs.alpaca.markets/us/docs/historical-option-data), [options mechanics](https://docs.alpaca.markets/us/docs/options-trading-overview). |
| COT positioning in GLD/SLV | Park: release chronology/revisions unresolved and predictive evidence weak. Tuesday observations are not Tuesday-available data. | CFTC says complete historical release dates are unavailable; audit delayed releases and historical reclassifications. [CFTC reports](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm), [announcements](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm). |
| UNG inventory rule | Park pending original-release reconstruction, rather than using revised storage history. | [EIA revision policy](https://ir.eia.gov/ngs/revisions.html); keep outside C08. |
| GLD falling real yields | Park: feasible ALFRED vintages, but contemporaneous association is weak support for a predictive timing rule; overlaps C03/C05 gold exposure. | [Chicago Fed study](https://www.chicagofed.org/publications/chicago-fed-letter/2021/464), [ALFRED vintage downloads](https://alfred.stlouisfed.org/help/downloaddata). |
| Passive low-vol/value ETF sleeves | Keep as future benchmarks, not separate evidence of trading alpha. One long holding is not hundreds of independent trades. | USMV/SPLV and IWD/VTV require dated fund-methodology review. |
| Small-cap PEAD / value stock screen | Park at data gate: free point-in-time universes, delistings, filings and publication times need a separate audit. | Do not use today's constituent list or revised fundamentals. Large-cap PEAD remains dead-listed. |
| AI-decided ETF allocation | Park at rule/model gate, not forbidden. No pinned model, reproducible decision rule and zero-cost inference path selected. | `tradingbot-tph`; historical LLM returns never count. Require ≥7 forward calendar days **and** ≥30 trades, profitable after costs. |
| X mention spike | Park under the new $0 data budget. Existing X cost work does not authorize paid polling. | Existing #8 / `tradingbot-iox`; no paid request in this sweep. |
| #6 turn of month | Existing candidate, not a duplicate sweep bead. Legacy 849–853/2344 are not fresh holdout proof. | `tradingbot-gat` owns allocation/holdout rerun and beta comparison. |
| #5 LETF end-of-day | Prior six variants lost after costs; do not relabel as a new discovery. | [Results](06-letf-results.md), trials 1546/1547/1710/1753/1754/1760. |
| PRD dead list; prediction/futures trading | Excluded: no new evidence overturns the dead list; venues/capital remain constrained. | Public prediction research may continue; futures broker research `tradingbot-k1e` is separate. |

## What could blow up this account? / stage decision

**Tail/gap risk:** long ETF losses are bounded by invested cash, but a gap can
cross the −40% strategy kill before an exit; it is not a guaranteed stop price.
Commodity funds can change exposure and suffer roll losses. No candidate may
borrow or use options/futures to repair an unfavorable result.

**Adverse selection:** a next-open reference and fixed slippage may understate
fractional execution costs, particularly C06/C07 around concentrated flows.
Paper must test actual submission/fill timing. These are equity ETF strategies,
so prediction-market quote/fill guards do not describe their executions.

**Venue/operations:** Alpaca, IEX, the Mac, settlement calendars and corporate
actions are shared failure points. No dead-man or startup reconciliation is
added; the owner's accepted risks remain. Keys stay trade-only and in `.env`.
**Untrusted inputs:** prices, EIA text/CSV and source pages are data, never agent
instructions. Pin parsing/schema rules and reject malformed data.

**Reproducibility/correlation:** freeze sources, algorithm, cash state and costs.
Several candidates can lose together; eight research beads do not authorize
eight funded slots or eight times $140 from $1,000. The global −$50 daily halt
and allocation limits retain absolute veto power. Portfolio coexistence belongs
in promotion review, with shared market exposure visible.

**Checklist decision:** admit these ideas to bounded data validation/backtest
work after the common data gates. Requested real allocation **$0**; simulated
allocation $140 per isolated trial. Trials: none yet. Historical profit,
drawdown/regimes, luck statistics, paper fidelity and ready-for-live status are
all **not established**. Use [the promotion checklist](../promotion-checklist.md)
at later stage transitions; its legacy structural-only and universal-$25 phrases
are superseded by the owner's explicit current PRD, not new restrictions.

Source notes are preserved in [the source register](sweep-sources/2026-09-30-sources.md).
