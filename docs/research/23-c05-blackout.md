# C05 commodity trend: profitable historical study; forward evidence pending

**+$30.42 in training and +$47.08 in the single final run**, after fees at 10 bp per side on separate $140 virtual allocations. The frozen rule is positive 126-session total return, rebalanced monthly across five 19% commodity ETF sleeves. Both partitions finish flat with zero rejected orders and no risk halts. **No paper/live promotion or ready-for-live status.**

Date: 2026-10-01. Completed bead: `tradingbot-qdd`. Forward evidence: `tradingbot-ggg`. This is a diagnostic historical result: prior USO outcome inspection and the explicit execution/action/cash assumptions remain limitations. It does not establish incremental alpha or an untouched holdout.

## Fixed experiment and selection

The source interval is 2008-01-01 through 2026-10-01 exclusive; the elapsed-time cutoff is **2021-02-14 14:24 UTC**. Training has 3,303 sessions, final 1,413. Each starts flat and keeps its warm-up inside the partition. Inactive sleeves stay cash; targets freeze at decision time; sales cannot fund same-day buys. Cash has no yield. The final run uses exactly the selected strategy version `de0dad8696f3603a0ebcde01bbe2f9333e037db5a22d03b4e7c01f8336924320`.

| Signal | Cost per side | Trial | Net P&L | Fees | Fills / round trips | Max marked drawdown | Monthly-block p |
|---|---:|---:|---:|---:|---:|---:|---:|
| 252 sessions | 5 bp | 3954 | $-0.61 | $2.82 | 215 / 48 | $80.98 (41.31%) | 0.492 |
| 252 sessions | 10 bp | 3955 | $-2.04 | $2.82 | 215 / 48 | $81.84 (41.80%) | 0.505 |
| 126 sessions | 5 bp | 3956 | $+32.30 | $3.06 | 250 / 57 | $48.63 (26.33%) | 0.251 |
| 126 sessions | 10 bp | 3959 | $+30.42 | $3.09 | 251 / 57 | $49.33 (26.75%) | 0.264 |
| Above SMA200 | 5 bp | 3960 | $+11.61 | $2.98 | 237 / 56 | $68.99 (34.56%) | 0.384 |
| Above SMA200 | 10 bp | 3961 | $+9.67 | $2.99 | 235 / 56 | $69.88 (35.04%) | 0.398 |
| **126 sessions — final** | **10 bp** | **3964** | **$+47.08** | **$1.74** | **161 / 34** | **$30.31 (18.25%)** | **null** |

The [selection receipt](23-c05-selection.json) was committed and pushed as `0ae082f` before the sole final invocation. Source admission was `36eb391`; tested replay code was `12e8e94`. Selection used only highest profitable complete 10 bp training net in the preregistered variant order. No changed-cost final replay, sibling sweep, version recycle or retuning occurred.

Training net return is 21.73%; final is 33.63%. Final execution P&L before fees is $46.45 at adverse fill prices; $1.74 fees leave $44.71 execution net, plus **$2.36 ordinary DBA income**. The two entitled payments become spendable on 2023-12-26 and 2024-12-30, after their documented payment dates. No execution fill is fabricated for a dividend. Full source and accounting precision remain in the [final receipt](23-c05-final.json).

## Drawdown, regimes and uncertainty

The selected training curve ranges from $117.32 to $184.39; max marked drawdown is **$49.33 (26.75% from peak)**, a material decline equal to 35.24% of the initial slot. Its daily-close drawdown is $48.81 (26.47%). Final max marked drawdown is **$30.31 (18.25%)**, versus $29.63 (17.91%) at daily closes. The absolute −$56 strategy-loss veto and −$50 daily halt remain unchanged; neither fired.

| Calendar regime | Training marked net | Final marked net |
|---|---:|---:|
| 2008-2009 | $-4.52 | not covered |
| 2010-2019 | $+15.24 | not covered |
| 2020-2021 | $+19.69 | $+0.13 |
| 2022 | not covered | $+9.44 |
| 2023-2026 | not covered | $+37.51 |

Each column covers only its own partition; 2020–2021 therefore ends in February 2021 for training and starts there for final. Calendar-year results, turnover, skips, exposure, fees and completed trades are in the machine receipts. Average owned exposure is 37.39% in training and 51.01% in final.

The fixed one-sided circular-block bootstrap uses three-month blocks and 10,000 draws. Training p≈0.264 uses 38 distinct exit-month clusters and is descriptive, unadjusted for selection. **Final p is null:** 34 completed round trips collapse to only **26 exit-month clusters**, below the predeclared evidence-sufficiency guard. Simultaneous ETF legs are not treated as independent observations. This is a reporting limitation, not an extra p-value promotion gate.

| Sleeve marked contribution | Selected training | Final |
|---|---:|---:|
| GLD | $+25.26 | $+17.11 |
| SLV | $+23.73 | $+16.50 |
| USO | $-1.45 | $+20.94 |
| UNG | $-15.68 | $-19.28 |
| DBA | $-1.44 | $+11.81 |

USO contributes **−$4.53 during January–April 26, 2020**, then **+$8.23 from the April 27 benchmark/holdings transition through year-end**, and +$4.84 during the remaining training months. Its final contribution is +$20.94. These are marked sleeve contributions from saved executions, not another strategy replay. UNG loses in both partitions; metal exposure supplies much of the profit.

Diagnostic buy-and-hold comparisons use the same completed closes, reinvested distributions, full hypothetical exposure and no trading costs: SPY returns +253.35% / +109.93% in training/final; the fixed equal-weight universe returns −14.53% / +102.73%; zero-yield cash returns 0%. The strategy has less average exposure. Positive raw P&L alone does not show incremental alpha.

## Blackouts, source integrity and verification

All **12 training and two final blackout symbol-sessions** find the affected sleeve already flat. Consequently **forced-exit and re-entry fills, fees and adverse costs are all zero** in both selected runs (also all other training cases). The final window is UNG 2024-01-23/24. These omissions count even without an actual forced trade; synthetic tests exercise the forced paths. Actual broker action handling is still unproven.

Source receipt: `05774a5a2f1ccbfef2898471f32311874e67298fc2bbbb6efb39b1cda893cb7c` ([source audit](23-c05-source.json)). All 4,716 five-fund sessions are retained. The original failed strategy 6032/trial 3518 are unchanged: full-row fingerprint `8b9696d0de5dc85d159e7eec01a75512f216486b2e753e54aa207a2f07630f5e`. Raw histories, reference captures and exact pre-outcome amendment remain immutable under `data/research/c05-blackout/`.

Ten synthetic replay tests and twenty source/auction checks pass. The independent [stored-ledger audit](23-c05-ledger-audit.json) passes **all seven runs**, verifying every fill price/fee, settled-cash purchase, prior-owned dividend, blackout-flat holding, final inventory and daily close mark. There is exactly **one final trial (3964)**. Daily-mark reconciliation differs by less than $0.000001; aggregate execution P&L reconciles within the declared database rounding tolerance. Auditing saved evidence does not consume or replay the holdout.

## Completed promotion decision

**Hold in backtest; no funded allocation.** The deterministic rule and both historical net-profit gates pass under the declared counterfactual. Trades, drawdowns, regime losses and statistical limits are reported. The $49.33 training drawdown remains significant. Same-reactor event tests pass, but fresh fractional fills, actual cash/dividend timing and broker action treatment are not yet established. Prior overlapping USO outcomes require subsequent untouched confirmation; the seven-day/30-trade rule for AI-decided strategies is not imposed on this rule.

Follow-up `tradingbot-ggg` records the concrete forward execution, dividend/cash and action evidence required by Amendment 21 and the existing checklist. No new account, keys, capital, venue, public post or §6 change occurred.

## Idea → backtest checklist, before outcome inspection

Decision: research backtest only, $140 virtual allocation per trial, no funded
allocation. The fixed commodity trend hypothesis tests persistence associated
with hedger demand and slow repositioning; no LLM output supplies a signal.
Rules, costs, source identity, cash treatment and holdout are explicit.
Historical profitability, statistics and regime evidence are pending, so the
paper/live gates are not passed. The pure strategy uses the same event/intent
contract as other modes; actual forward fills remain unverified. All §6 limits
remain unchanged. No capital, venue, account, key or public post is added.

**What could blow up this account?** Commodity gaps, futures roll losses and
fund benchmark changes can produce correlated losses. Each active sleeve
targets 19% of equity, inside the strategy slot, but a gap can cross both the
$50 daily halt and $56 strategy kill before either can react. Blackouts avoid
the six known split entitlements; they do not insure against surprise actions
or prove the current broker's handling of shares.

Adverse selection arises when monthly public signals trade into opening gaps
or thin liquidity. The two adverse-cost assumptions are scenarios, not observed
fractional opening fills; this is taker research with no claimed maker edge.
Counterparty exposure remains concentrated at Alpaca, with Yahoo history and
limited independent venue overlap. No live keys are present. External source
content is treated as data, checksum-bound and validated, never instructions.

The reactor, source hashes, fee book and cash calendar make the experiment
deterministic; every real configuration must enter the ledger before prices are
iterated, and a final attempt remains consumed on failure. C01/C03 trend and
other commodity exposures can correlate with C05, so independent virtual
backtests do not establish safety for a simultaneously funded portfolio.
## Pre-outcome source and timing amendment

Written 2026-10-01 before any C05 signal or strategy-return computation, under
the revision rule in [07](07-candidate-shortlist.md). The source preparation
below remains part of the audit trail. This amendment changes research source
treatment only; the universe, interval, three signals, cost cases, cash sizing,
holdout boundary and §6 limits remain fixed.

Six Yahoo opens conflict with the archived primary NYSE Arca opening auction.
Use these actual-share auction prices: GLD 2016-08-12 **129.10**; USO 2016-11-30
**10.68**, 2017-01-12 **11.61**, 2017-02-09 **11.38**, 2017-10-30 **10.90**;
UNG 2017-02-09 **7.96**. Each falls within that session's source high/low. Keep
original bytes immutable, retain both values, and bind every correction to its
ten-second primary O/Q auction capture. Five discrepant closes confirm Yahoo
and require no correction. SIP open/close and IEX close checks retain the 1%
bound; IEX opens are venue diagnostics. SIP overlap begins in 2016; this does
not independently validate 2008–2015 prices.

For all six non-cash actions, exit at the open before the ex-date, decided at
the preceding close. The C05-local blackout ends at the maximum of the verified
post-split trading date, issuer effective/share-exchange date, actual payable
date when reported, and expected delivery date when reported. Re-enter at the
next regular session subject to the usual signal and settled cash. Missing
actual payable dates remain null. The model endpoint is an explicit research
assumption, not a broker payment date; no fractional entitlement is held.
The shared Amendment 21 helper is unchanged.

| Action | Announcement | Actual payable | Research end | Exit / re-entry |
|---|---|---|---|---|
| SLV 10:1 | 2008-07-11 | 2008-07-23 after close | 2008-07-28 expected delivery | 07-23 / 07-29 |
| UNG 1:2 | 2011-02-16 | unknown | 2011-03-09 post-split trading | 03-08 / 03-10 |
| UNG 1:4 | 2012-02-01 | unknown | 2012-02-22 post-split trading | 02-21 / 02-23 |
| UNG 1:4 | 2017-12-22 | unknown | 2018-01-05 post-split trading | 01-04 / 01-08 |
| USO 1:8 | 2020-04-22 | 2020-04-29 (broker field) | 2020-04-29 | 04-28 / 04-30 |
| UNG 1:4 | 2024-01-05 | 2024-01-24 (broker field) | 2024-01-24 | 01-23 / 01-25 |

The [SLV issuer release](https://www.sec.gov/Archives/edgar/data/1330568/000119312508149627/dex991.htm)
distinguishes its payable-before-ex ordering from later expected account
delivery. Five checksum-verified USCF releases cited in [15](15-c05-commodity-trend.md)
establish the other announcement and effective dates. UNG's 2024 opening
announcement and broker event prevail over the release's stray 2023 FAQ dates.
Actual broker availability remains a separate promotion requirement.

DBA has seven vendor distributions. Annual reports verify 2008/2018/2019
record/pay dates; issuer qualified notices verify 2022–2025. Use $0.45,
$0.17994, $0.25717, $0.09643, $0.96045, $1.08408 and $0.91237 respectively;
2018/2019 precision comes from the broker, with the annual report rounded.
Ex/pay pairs are 2008-12-15/12-30, 2018-12-24/12-31,
2019-12-23/12-31, 2022-12-19/12-23, 2023-12-18/12-22,
2024-12-23/12-27 and 2025-12-22/12-26. For 2008/2018/2019, ex-dates are
corroborated by applying the [NYSE historical ex-date rule](https://www.nyse.com/publicdocs/nyse/regulation/nyse/Changes_Related_to_the_Shortened_Settlement_Cycle_T%2B2.pdf)
to primary record dates and checking Yahoo; this is an explicit inference.
The broker's extra 2018-12-26 event is the record date of the same distribution,
not a second payment. Do not credit it twice. The inventory is the union of
the full vendor record and available broker history, reconciled to primary
evidence for every event; it is not a proof that every historical vendor
omission is impossible. The other four funds have no reported cash dividends.

Entitle cash using shares owned before the ex-date open. Recognize the
receivable then, but make it spendable only at the first regular-session open
strictly after the documented payment date (conservative unknown intraday
credit). Signals retain vendor adjusted closes; execution uses actual-share
OHLC, undoing all strictly later splits. No double dividend or split credit.
At a split re-entry, use the most recent completed monthly signal and resize
that sleeve from the preceding close's current equity; other sleeves retain
their existing frozen targets until the next monthly rebalance.

Where direct SEC/Invesco HTTP retrieval failed, archived primary-page text
extracted by the web provider is admitted with its own timestamp and SHA-256.
It is explicitly not an original HTTP response or a visually verified PDF.
Failed HTTP receipts remain preserved. No C05 outcomes have been examined;
earlier C08 outcomes overlap USO history, earlier C03 work overlaps GLD sources,
and issuer annual reports expose fund-level historical performance. These
limits preclude an untouched-holdout claim or automatic forward promotion.
