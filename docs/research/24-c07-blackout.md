# C07 weekly sector reversal under Amendment 21

Date: 2026-10-01. Bead: `tradingbot-pdw`. **Training decision: no eligible
winner; final holdout unconsumed; no promotion.** All six fixed cases are logged
and independently reconciled. The original failed source trial 3548 and
[report 18](18-c07-source-audit.md) stay intact. The source amendment below was
frozen before any C07 rankings, strategy returns or training selection.

The [common specification](07-candidate-shortlist.md#c07--weekly-sector-loser-reversal)
and [Amendment 21](21-corporate-action-blackout.md) govern this new version. Keep
all nine sectors, SPY as reference, the 2006-01-01–2026-10-01 exclusive interval,
2020-07-10 14:24 UTC split, $140 virtual allocation, 95% target, 5/10 bp training
cost cases and the three ordered 5-session/top-three, 10-session/top-three,
5-session/top-one variants. Nothing changes PRD §6 or authorizes live keys.

## Explicit source amendment, before outcomes

The original immutable C02 Yahoo captures supply daily observations. All nine
retain 5,218 sessions. Open and close are converted back to actual-share units
by undoing subsequent vendor split normalizations. For XLF, undoing Yahoo's
1.231 normalization restores the quoted price basis only: **it never creates
extra XLF shares**. Actual corporate actions come from the issuer, not the
vendor's event label. High/low, volume and vendor adjusted close are excluded
from execution and reconstructed total-return signals.

The complete available raw SIP/IEX overlap is checked at the unchanged 1%
bound. All required disputed opens/closes have first-ten-second primary Arca
auction evidence. Seventeen of nineteen differences confirm Yahoo. Two derived
opens are corrected to the primary opening print: **XLK 2017-10-30 $62.56** and
**XLV 2016-11-09 $71.31**. Original responses remain unchanged. IEX opens are
diagnostic because a venue's first print is not the primary opening auction.
No independent price coverage before 2016 is claimed.

Ordinary dividends use the archived [SSGA historical workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx),
SHA-256 `51a16a450298a663b3fa088883a17c75f4464e87c911b0e83902a0ad46877c54`.
Read only the fixed universe and interval; reject duplicate, formula, negative
or inconsistent-date rows. Two explicit XLK zero distributions (2006-06-16 and
2007-03-16) produce no income. The XLF 2016-09-19 row's `0.139146` is **XLRE units,
not dollars**, as proven by [the primary action audit](17-xlf-action-amendment.md).
It is excluded from ordinary cash distributions.

Issuer amounts govern both signal income and actual-share entitlement. Archive
every disagreement with Yahoo, including material differences on 2006-09-15
for all nine sectors, XLF on 2016-03-18 and XLP on 2009-12-18. This is an explicit
source-precedence amendment, not a claim that the sources agree. The independent
broker action overlap corroborates ordinary amounts to the issuer's six-decimal
precision (three XLF 2020 rates differ by $0.0000001); its repeated action IDs
never multiply a distribution, absent payable fields never become ex-date cash,
and its mislabeled record dates do not supersede the issuer.

Cash is a receivable for shares owned before the ex-date open. Release it at
the first regular open strictly after the **latest documented payable date**
among the issuer and any matching broker records, never earlier. Keep the
issuer date and modeled availability separately. Sale proceeds follow the
already frozen SPY/calendar convention: first regular open strictly after
completed T+1 settlement. These are conservative current-account research
conventions, not actual historical broker-credit evidence.

For total-return signals, reconstruct daily economic returns from the verified
close, issuer ordinary distribution and actual split ratio. At XLF's in-kind
ex-date, add exactly `0.139146 × XLRE ex-date close` per old XLF share to the
signal numerator. The one-day XLRE close is independently checked against SIP
and the primary Arca closing print. It is an economic distribution value for a
total-return index; no XLRE position, trade, cash, ranking slot or tax-value
substitute is created. The same pure signal calculation will run forward.
Signal history and warm-up stay wholly inside each evaluation partition.

## Causal blackout evidence

The [shared C02 announcement audit](22-c02-amendment21-admissibility.md) supplies
the same six actions. Reverify its exact primary bytes on each source build.

| Action | Announced | Exit decision close | Exit open | Flat through | First eligible re-entry |
|---|---|---|---|---|---|
| XLF / XLRE in-kind | 2016-09-01 | 2016-09-15 | 2016-09-16 | 2016-09-22 | 2016-09-23 |
| XLB/XLE/XLK/XLU/XLY 2:1 | 2025-11-20 | 2025-12-03 | 2025-12-04 | 2025-12-05 | 2025-12-08 |

The 2025 splits are payable after the December 4 close and effective December 5.
Keep the actual payable date separate from the conservative December 5 research
endpoint; do not relabel it as broker delivery. This yields five training
blackout symbol-sessions and ten final symbol-sessions. Normal weekly rules,
original scheduled exits and settlement constraints still apply to re-entry.
Rank the unchanged universe first; an unavailable selected slot stays cash,
without promoting a different sector into that slot. A forced exit and any
subsequent entry pay normal scenario costs and fees and count as trades.

## Evaluation policy frozen before outcomes

Source checks, focused tests and immutable admission must finish before the
reactor is evaluated. All six training cases and the final were unattempted
when this policy was frozen.
Only a profitable complete 10 bp training winner can proceed to one committed,
unchanged-version final. Every attempted configuration belongs in the ledger.
Report all fees, turnover, fills, completed trips, marked drawdown, calendar
regimes, weekly dependence-aware inference and blackout-leg costs. No p-value
or Sharpe gate is added.

SPY overlaps earlier inspected #5/#6/C01/C06 history, and published fund data
has been seen during source review. Source reuse does not make that evidence
untouched. This version requires separate actual-action, fresh-price,
fractional-execution and cash confirmation before promotion.

## Implementation and pre-outcome review

Source slice `e7ee066` freezes admission receipt
`6c89c1cd4827a63fefffcb0ebe3e00be9dd8bae2631ec1d49632c5dbc4b214e7`.
The independent source reader verifies the admitted data and dependency hashes
before returning observations. The original source amendment is retained in
that immutable bundle even as this report gains subsequent results.

The pure `SectorReversal` reactor uses one rule in every mode. The candidate
adapter delegates orders, fills and all vetoes to the existing shared
backtester, ledger, fee book and risk engine. Simultaneous nine-sector marks
avoid transient, ordering-dependent risk decisions. Separate cash receivables
do not fabricate dividend trades. Buy quantities fit the submitted rounded
limit under the unchanged $140 cap. Existing settled cash can fund part of a
new cycle immediately; that day's sales cannot. A later addition retains its
decision-time dollars and original exit, and a repeated sector is still sold
at the old cycle's exit before any new entry.

Each attempted configuration is durably recorded before its lazy price feed
is consumed. A family guard and the shared single-version final claim prevent
recycling a final through renamed runs or source identities. A risk-vetoed or
sub-$1 exit is never forced past the shared checks. If such a position remains
on a blackout exit day's close, the attempt stops before an unsupported
corporate-action conversion and retains its partial fills, marks and failure.

For descriptive inference, aggregate marked changes by New York Monday–Sunday
week and use a fixed **four-week circular block**, 10,000 centered-null draws,
seed 7072026. Require at least 30 covered weeks and 30 distinct exit-week
clusters for a non-null estimate; this is an information-quality guard, not a
promotion gate. Simultaneous ETF legs are not independent observations. The
estimate is one-sided and not adjusted for selecting among variants.

The [promotion checklist](../promotion-checklist.md) is completed here for
**idea → backtest research only**, October 1, 2026, NavyLantern. The mechanism
is a test of liquidity supply after sector selling pressure; entry, exit,
costs, data and selection are fixed. Historical profit, measured drawdown,
regimes and inference were pending at this preparation boundary; the final
decision below supersedes that pending status. Actual forward fidelity is
untested. Allocation is **$140 virtual / $0 funded**.
No paper/live/ready-for-live promotion follows from source admission or tests.
All current PRD §6 values and §9 accepted choices remain unchanged.

## What could blow up this account?

**Tail and gaps:** temporary losers can keep falling, and several sectors can
gap together. The top-one variant concentrates its whole target in one fund.
The unchanged allocation cap, −40% kill and −$50 daily halt constrain order
admission but do not guarantee liquidation or bound losses through a gap.
Risk-vetoed exits remain explicit failures rather than simulated fills.

**Adverse selection:** the counterparty may know that a sector's decline is
permanent. These are long ETF taker scenarios, so prediction-market maker
guards do not apply. Stressed spreads or a fractional order filled away from
the reference open can exceed the 5/10 bp assumptions. Settlement delays can
miss a reversal, and no extra filter is added after observing performance.

**Venue and operations:** future execution depends on Alpaca, its fractional
eligibility, fresh observations and actual share/cash treatment. The owner's
accepted lack of dead-man protection and startup reconciliation remains. No
key, account, broker order, funding or live process is created in this study.

**Untrusted inputs:** issuer/vendor text is evidence, never an instruction.
Exact hashes, request checks and field/date validation bind the source bundle.
No model decides a trade, and no external text is executed.

**Reproducibility:** the reactor, source receipts, fees, parameters and random
seed are versioned. Synthetic tests can repeat; an admitted real final cannot.
Retain failed attempts and inspect their stored records instead of rerunning
them. Source precedence and current-account cash/fee assumptions remain visible.

**Correlation:** sector losers remain exposed to broad equity markets and can
lose alongside other Alpaca strategies. Nine tickers and multiple variants do
not provide nine independent sources of diversification. Report joint marked
losses, regime dependence and SPY/equal-weight diagnostics before any later
promotion decision.

## Recorded execution failures

The first training case, trial **4031** (5 sessions / top three / 5 bp), hit the
unchanged per-strategy kill on **November 20, 2008** at $80.589226 marked equity.
The shared risk engine vetoed later orders, including exits. The strategy
therefore stopped with a recorded failure at the **September 16, 2016** close
when XLF shares remained held on the mandated blackout exit date. It did not
simulate the unsupported September 19 distribution.

The failed run's marked equity subsequently recovered while positions remained
immobilized by the kill. That is passive exposure from vetoed exits, not the
intended weekly strategy or an eligible profitable result. Realized net,
unrealized P&L, retained shares, rejected orders, last processed time and marked
drawdown remain separately reported. Its regime, benchmark and bootstrap
diagnostics describe that **partial, failed path**; they do not establish an
active trading edge. The independent stored-fill/cash/mark audit passes without
rerunning strategy decisions. All six fixed cases are now recorded below.

## Six-case training result and frozen decision

Implementation and tests were pushed at `fa205b9` before the first outcome. The three variants and two costs were each attempted once. The frozen selector returns **`selected: null`**: every 10 bp case has negative realized net after fees and an execution failure. **No final was attempted.**

| Trial | Lookback / slots | bp/side | Feed / execution | Round trips | Fills | Realized net, USD | Fees, USD | Max marked drawdown, USD / peak % | Weekly p-value |
|---|---|---|---|---:|---:|---:|---:|---|---:|
| 4031 | 5 / 3 | 5 | failed / killed | 433 | 902 | -21.90 | 5.93 | 77.31 / 52.26% | 0.0579 |
| 4043 | 5 / 3 | 10 | failed / killed | 374 | 781 | -39.91 | 5.13 | 99.83 / 70.94% | 0.3130 |
| 4050 | 10 / 3 | 5 | failed / killed | 878 | 1869 | -42.63 | 11.81 | 83.64 / 52.88% | 0.5564 |
| 4057 | 10 / 3 | 10 | failed / killed | 434 | 902 | -20.88 | 5.89 | 83.65 / 54.01% | 0.0558 |
| 4064 | 5 / 1 | 5 | complete / clean | 755 | 2134 | -25.93 | 30.24 | 101.69 / 51.32% | 0.6011 |
| 4065 | 5 / 1 | 10 | complete / killed | 493 | 1078 | -56.01 | 19.75 | 91.83 / 52.23% | 0.7784 |

Realized net includes entitled ordinary distributions and all charged fees. The failed top-three cases still hold shares; their positive marked recoveries, where present, are separately identified below. Drawdown uses all open/close/fill marks and a running equity peak; it is not the initial-allocation loss used by the kill. Exact daily-close drawdowns, year-by-year results, quantities and cash balances are retained in the [selection export](24-c07-blackout-selection.json).

| Trial | First kill date (New York) | Last processed day | Rejected orders | Unrealized P&L, USD | Ending marked equity, USD |
|---|---|---|---:|---:|---:|
| 4031 | 2008-11-20 | 2016-09-16 | 8865 | +158.99 | 277.10 |
| 4043 | 2008-07-02 | 2016-09-16 | 10067 | +68.98 | 169.07 |
| 4050 | 2011-09-21 | 2016-09-16 | 5173 | +35.33 | 132.69 |
| 4057 | 2008-11-20 | 2016-09-16 | 8926 | +160.28 | 279.40 |
| 4064 | none | 2020-07-10 | 0 | +0.00 | 114.07 |
| 4065 | 2015-06-29 | 2020-07-10 | 1261 | +0.00 | 83.99 |

Trial **4064** is the only case with clean full execution, and it loses **$25.93**. Trial **4065** completes the feed but is not a completed executable strategy: its last sale left it flat at $83.989851 on June 29, 2015, triggered the unchanged kill, and 1,261 later entries were vetoed. Its empty ending inventory does not turn the kill into a pass. No risk limit or exit veto was bypassed.

## Regimes, costs and exposure

These are marked contributions of each recorded path, including immobilized exposure after a kill. Failed top-three paths end September 16, 2016; their 2010–2019 column is partial. The full-feed paths end at the July 10, 2020 training open, so the 2020–2021 column contains only the admitted portion of 2020. The 2022 and 2023–2026 regimes are **not evaluated**.

| Trial | 2006–2009, USD | 2010–2019, USD | 2020–2021 admitted portion, USD | Turnover, USD | Average owned fraction | Income, USD |
|---|---:|---:|---:|---:|---:|---:|
| 4031 | -4.86 | +141.96 | not reached | 34,778.92 | 81.94% | 32.82 |
| 4043 | -64.40 | +93.47 | not reached | 29,348.37 | 81.95% | 21.12 |
| 4050 | -37.14 | +29.84 | not reached | 66,391.96 | 72.04% | 25.77 |
| 4057 | -3.75 | +143.15 | not reached | 35,740.53 | 81.90% | 33.00 |
| 4064 | +30.01 | +11.65 | -67.58 | 208,083.00 | 54.18% | 51.88 |
| 4065 | -6.17 | -49.84 | +0.00 | 110,714.42 | 36.06% | 25.91 |

The bootstrap uses 559 covered weeks for the four partial runs (128–295 exit-week clusters) and 758 weeks for the two full-feed runs (755 and 493 exit-week clusters). It is descriptive, one-sided, serial-dependence-aware and unadjusted for selection. In killed runs it mixes active trading with later immobilized exposure or cash; it is **not evidence of a viable active edge**. No inference threshold is used to rescue or reject an otherwise eligible candidate.

For the two full-feed paths, no-cost reinvested total-return diagnostics over the completed training closes are **SPY +232.89%** and the fixed nine-sector equal-weight benchmark **+228.35%**, versus **0%** zero-yield cash. These full-exposure benchmarks are not executable strategies at the allocation cap. The partial-run benchmark fields remain in the export; their final interrupted close batch leaves the equal-weight benchmark one completed session behind SPY, so no matched-endpoint alpha claim is made from them.

Every training case has **five planned XLF blackout symbol-sessions**. Each top-three failure processed the first session before stopping; both top-one cases processed all five. There were **zero successful forced-blackout exits and zero blackout re-entry fills** in these runs, so their directly charged fees and modeled adverse-reference costs are $0.00. Vetoed exits were not fabricated. This does not estimate opportunity cost from staying in cash. The ten 2025 split-blackout symbol-sessions belong to the **unconsumed final**, and have no strategy outcome here.

## Verification and promotion checklist decision

All **38** focused source/blackout/reactor/replay/audit checks passed before real outcomes. The [independent ledger audit](24-c07-ledger-audit.json) then reconciled all six saved runs without invoking the strategy: exact source-priced adverse fills, dated fees, prior-owned dividend quantities, payment/settlement cash, weekly expiries, long-only inventory, open/close marks and final/partial balances. Audit PASS means the evidence reconciles; it is not a strategy PASS.

The audit checks 7,666 fills and 36,186 open/close marks. Original strategy 6080 and failed trial 3548 remain byte-identical to their saved JSON snapshot, SHA-256 `24490ad560e0330f755b4fd7f219026727754d138b4d5a053adbcde7b0199973`. The family final inventory is empty.

The committed selection is a review export of the immutable full selection. It omits only four duplicate full mark sequences nested in failed-run metrics; those sequences remain in the database and hash-bound local run artifacts. All other metrics and the null choice are unchanged. Original full selection SHA-256: `f809116749cd8294249cd1d2195d5716b7b622db9b923b8e37216ba36442799a`. Source receipt and execution dependency hashes remain frozen.

**Decision, October 1, 2026, NavyLantern:** hold/reject this preregistered C07 family at backtest research. The structural hypothesis and causal rule were testable, but no 10 bp training candidate is profitable with complete execution; drawdowns and kills also fail the account-risk review. The final, paper/live fidelity, fresh forward confirmation and live eligibility are unestablished. Allocation remains **$140 virtual per isolated trial / $0 funded**. Nothing is added to the ready-for-live queue. PRD §6, accepted §9 risks, accounts, keys and live processes are unchanged.
