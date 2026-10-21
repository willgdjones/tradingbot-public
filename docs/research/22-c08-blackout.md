# C08 USO inventory scarcity under Amendment 21

Date: 2026-10-01. Bead: `tradingbot-8lk`.

**The frozen −5% rule is profitable in training and its single final holdout.**
At 10 bp per side, training earns **$102.29** and the final earns **$7.67** on
$140 virtual capital. Final maximum marked drawdown is **$28.68 / 16.41%**.
Only seven completed trips support the selected rule across both partitions;
luck inference remains null. This completes the historical study, with separate
forward execution evidence tracked in `tradingbot-gx2` before any promotion.
Original failed source trial **3550** and strategy **6082** remain intact.
The [machine-readable source receipt](22-c08-blackout.json) binds inputs,
exceptions, code, review and original-row hashes. Immutable source receipt:
`63c4d561929099ae039a8a67a0deace1991b08d6e3dacef55c6c2de481b99ca5`.

## Training and frozen choice

The four fixed cases ran once from source/implementation commit `90fcde2`.
The [frozen selection](22-c08-selection.json) chooses **−5% at 10 bp**,
trial **3907**, version
`739e205972e6208c07c0fc0618946a1813a877e7c775d4d737237f54c9183376`.
All fills reconcile exactly to the frozen open-reference/cost rule; fees and
completed trips reconcile to the ledger. Original failed rows remain unchanged.

| Threshold | Cost/side | Trial | Result | Completed trips / fills | Fees | Net after costs | Max marked drawdown |
|---|---:|---:|---|---:|---:|---:|---:|
| 0% | 5 bp | 3904 | Failed, partial | 1 / 3 | $0.05 | Not a completed result | $157.78 |
| 0% | 10 bp | 3905 | Failed, partial | 1 / 3 | $0.05 | Not a completed result | $157.69 |
| −5% | 5 bp | 3906 | Complete | 3 / 6 | $0.12 | **+$102.88** | $54.88 / 26.55% |
| **−5%** | **10 bp** | **3907** | **Selected** | **3 / 6** | **$0.12** | **+$102.29** | **$54.80 / 26.61%** |

Both 0% cases hit the permanent −40% loss veto at the February 28, 2020 open.
The unchanged risk engine subsequently refused exits, including the April 28
blackout sale (33 rejected orders per case). The replay stopped at April 28
close before an unresolved conversion. Ending marked equity was $23.26 in each
case, approximately **−$116.74 marked from the initial $140**; this is partial
evidence with an open position, not a completed backtest return. A kill veto does
not guarantee liquidation or cap the loss of a retained position. No veto was
bypassed and no live state changed.

The selected rule was naturally flat during both blackout sessions, so actual
forced-sale/re-entry fees and adverse cost were **zero**. It had no halts,
rejections or cash-delay skips, and one terminal liquidation. Its net return on
initial virtual cash was 73.06%; gross P&L was $102.41 and turnover $911.91.
Daily-close maximum drawdown was $54.27. **Luck p-value is null:** only three
completed trips, with serial dependence and insufficient independent evidence.
For context, the same-period SPY close total-return diagnostic was +105.26%,
USO's split-continuous close diagnostic −25.90%, and cash 0%. These are not
matched executable portfolios and positive raw profit is not proof of alpha.

Training audit: `data/research/c08-blackout/runs/training-audit.json`, SHA-256
`6afe9c9b13b05cbdf579e44672c130c73973914663e4ef7306f12923d77acf41`.
Selection commit `ebba4b8` preceded the one permitted 10 bp final. No extra luck
gate or variant search was introduced after these results.

## Single final holdout and regime results

The [final receipt](22-c08-final.json) records **trial 3910 / strategy 6447**,
the same frozen version and −5% threshold, at 10 bp per side. It completed
**four round trips / eight fills**, earning **$7.67 net** (+5.48% of initial
virtual cash), with $7.83 gross P&L, **$0.16 fees**, $1,113.73 turnover and
$147.67 ending marked equity. Maximum marked drawdown was **$28.68 / 16.41%**;
daily-close drawdown was $28.43 / 16.29%. Exposure totaled 2,088 calendar hours.
There were no halts, rejected orders, cash-delay skips or remaining positions.
The rule was already flat at the terminal open. The final contains no blackout
sessions, and actual forced-exit/re-entry costs are zero.

The read-only final audit verifies exactly one family final attempt, unchanged
training/final version and dependencies, exact adverse-open price arithmetic,
ledger fees/trip reconciliation, and independently eligible, nonstale inventory
publications for every entry. Original failed trial 3550 and strategy 6082 still
match their original full-row hashes. Audit:
`data/research/c08-blackout/runs/final-audit.json`, SHA-256
`d89ec1f67f0052bdca3686cd97e85724823abfdb6bbbb6a51be47cf82bce9bf0`.

Marked P&L is allocated by observation date; completed-trip counts and fees are
available separately in the receipts, so a position crossing a boundary does
not assign all its economic change to its exit regime.

| Frozen USO exposure regime | Training net | Final net |
|---|---:|---:|
| 2018–2019 | −$1.17 | Outside partition |
| January 2020–August 2023 | +$100.67 | Outside partition |
| September 2023–January 2024 | −$1.25 | Outside partition |
| February 2024–December 2025 | +$4.03 | +$19.70 |
| January–September 2026 | Outside partition | −$12.04 |
| **Total** | **+$102.29** | **+$7.67** |

Final calendar-year net was **+$17.46 in 2024**, **+$2.25 in 2025**, and
**−$12.04 in 2026 through September**. Training profit is concentrated in one
2021–2022 trip. Four final trips do not support a reliable luck estimate; the
p-value remains **null**, without adding an extra eligibility gate. Final
SPY close total-return and USO split-continuous close diagnostics were +56.88%
and +99.97%, respectively; zero-yield cash was 0%. These have different exposure
and no trading costs, so they do not establish risk-adjusted relative alpha.

## Frozen specification

Keep [C08's preregistration](07-candidate-shortlist.md#c08--uso-inventory-scarcity):
USO; commercial crude stocks excluding SPR divided by the same release's
comparable year-ago level, minus one; strict thresholds **0% / −5%**; both **5 / 10
bp per side** in training. Cash-to-long targets 95% of current equity, capped at
the $140 virtual slot, with the 5% cash reserve and fees. An unchanged long state
retains shares without weekly resizing. Long-to-cash sells all owned shares.

The interval remains **2018-01-01 through 2026-10-01 exclusive**. Training ends
at **2024-02-15 12:00 UTC**, 70% of elapsed time. Both partitions start flat, use
only publications becoming available inside that partition, and liquidate at
the last eligible open with costs; no entry occurs at that open. The best
positive, complete **10 bp** training result wins, with listed threshold order
breaking ties. Freeze and commit that choice before **one 10 bp final**. No
profitable training choice means no final. The 5 bp cases are diagnostics.

Date-only publication becomes available at the following calendar midnight in
New York, for the next regular-session open. Newest observation wins when delayed
reports share a publication date. Missing reports give no new signal; at the
next session more than 14 calendar days after the last usable publication,
target cash. Cash-delayed entries retain their original dollar target/reserve.

## Source admission and exceptions

All **457** actual dated EIA archive links in the fixed interval were captured.
**455 releases** pass observation/comparison dates, positive levels, crude-stock
components, million-barrel units, the unchanged commercial-stock definition,
PDF/CSV agreement and contemporaneous methodology/revision-notice review.
The two HTTP-200 EIA error pages, **2019-04-03 and 2019-09-11**, remain unusable;
no dates or values are invented for them. Delayed June 2022 and November 2023
reports use their actual publication dates. The September 30, 2026 release is
not actionable before the exclusive sample end.

This is a reconstruction from dated primary archives, supported by archived
revision policy and specific errata. We did **not** independently capture each
file on its original release day. That uncertainty remains explicit in every
record; admission is not a claim of cryptographic first-release proof. Revised
bulk series and differences reconstructed from later data are excluded.

| Exception | Evidence and treatment |
|---|---|
| January 9, 2019 observation heading omits its day | Attached CSV/PDF agree on the date; month/year and full page publication date must match. |
| July 3, 2019 links the prior week's CSV | Correctly dated June 28 Table 1 PDF supplies the fields; original CSV remains intact. |
| March 18/25 and April 8/15, 2020 CSV aggregate totals fail the component check | Original dated PDF supplies the stock fields after independent date/unit/definition/component checks. |
| June 24, 2026 page says June 14 publication, before June 19 observations | The exact archived full report explicitly says **June 24** on page ii. Its hash and the erroneous page hash are pinned; earliest execution is June 25. No URL-date inference. |

CSV fields retain 0.001-million-barrel precision when confirmed against the PDF.
The five PDF fallbacks retain their printed **0.1-million-barrel** precision;
no extra digits are reconstructed. Three independently rounded PDF components
permit at most 0.15 million barrels of sum discrepancy; the CSV gate stays at
0.002. Source choices were fixed before threshold or return calculations.
The July 2019 fallback was also visually checked against its rendered table.

The [2019 correction](https://www.eia.gov/petroleum/supply/weekly/archive/2019/2019_05_22/wpsr_notice_07252019.php)
explicitly excludes crude-oil errors. The
[2020 changes](https://www.eia.gov/petroleum/supply/weekly/archive/2020/2020_04_01/wpsr_notice_04012020.php)
concern propylene/oxygenates, and the
[2023 changes](https://www.eia.gov/petroleum/supply/weekly/archive/2023/2023_11_15/wpsr_notice_11132023.php)
add crude-supply flows and propane detail, without redefining this stock row.
The sole distinct archived Appendix E corrects propane/propylene; it explicitly
retains past editions. The December 2023 notice distinguishes revised future
comparisons from previously published levels. Other notices concern production,
imports, price displays or supplemental tables, not C08's two stock inputs.
All notice text and the four linked primary notices are retained with hashes.

## USO prices, action avoidance and exposure

Yahoo supplies all **2,198** regular sessions. Its split-adjusted open/close is
multiplied by **1/8 strictly before April 29, 2020** to obtain actual-share units.
Raw SIP covers all sessions and agrees within the unchanged 1% diagnostic bound
(maximum 0.8422%). IEX has 1,554 sessions; its April 21, 2020 close of $3.18 is
resolved by primary Arca closing prints at $2.81, matching Yahoo. **No price is
replaced.** Ten IEX opening differences remain separate-venue diagnostics.
This basis check does not establish fills within 5 or 10 bp.

The timely [April 22 issuer announcement](https://www.prnewswire.com/news-releases/uscf-announces-one-for-eight-reverse-share-split-for-the-united-states-oil-fund-nyse-arca-uso-301045001.html)
and archived Alpaca action record establish the unchanged
[Amendment 21](21-corporate-action-blackout.md) plan: decision **April 27 close**,
exit **April 28 open**, broker payable/ex-date **April 29**, re-entry **April 30**.
There are **two blackout sessions, both in training**. No fractional cash credit
is assumed. Both forced legs use normal fees, adverse cost, cash and risk gates;
a rejected exit stops the replay before carrying the unresolved conversion.

Yahoo and Alpaca action inventories contain no ordinary distributions in the
fixed interval. The [April 2026 prospectus](https://secure.alpsinc.com/MarketingAPI/api/v1/Content/uscfinvestments/united-states-oil-fund-pro-20260424.pdf)
also reports no prior cash distributions. Its exposure disclosures fix the
reporting buckets: pre-2020; calendar-2020 through August 2023 (including months
before the spring change); September 2023–January 2024 transition; February
2024–December 2025; and January–September 2026. The last boundary records the
change from a ten-day to a five-day monthly roll. No regime-specific rule is fit.

## Execution, accounting and evaluation controls

The shared Backtester, RiskEngine and Ledger execute all orders. The already
admitted SPY source supplies the common exchange/settlement calendar and the
SPY benchmark. T+1 is a current-account historical counterfactual; spendable
sale cash conservatively waits until the first regular open after documented
settlement completion. Nominal settlement, completion and cash release remain
separate evidence fields. Fees use EquityFeeBook's September 17, 2026 schedule
as a current-fee counterfactual. ETF expenses/roll effects are not charged twice.

Training attempts commit before event-feed iteration. Final admission uses the
shared durable guard plus a C08 Amendment21 family guard against changed
source/run/version names. Failed or interrupted attempts remain in the ledger;
failed replay keeps partial marks, fees, positions and processed-through time.
Fifty-six focused checks pass across source, reactor, ledger/cash/risk and
holdout suites, including a severe gap vetoing a forced sale before conversion.

Report net/gross P&L, fees, trades, turnover, exposure, cash skips, rejections,
all-mark and daily-close drawdown, calendar years and exposure regimes, and
both forced-leg costs. Descriptive luck inference uses monthly marked changes
and a fixed three-month circular-block bootstrap; fewer than 30 trips/months
means a null p-value. This adds no promotion gate. SPY and split-continuous USO
close benchmarks and zero-yield cash are diagnostics, not executable alternatives.

## Account-risk and promotion review

The idea-to-backtest source gate and historical after-cost profit gate pass for
this research version. The selected training result and single final are
profitable. No capital, live key, paper job, risk limit or live strategy state
changes. Earlier C08/C05 source inspection,
the published commodity hypothesis and prior SPY benchmark inspection remain
disclosed; a new dataset key does not make market history pristine.

USO's futures exposure/roll, price gaps, missed blackout exposure, uncertain
fractional fills, date-only macro evidence and delayed spendable cash can swamp
a $140 slot. Open-reference scenarios are assumptions; daily bars do not waive
the 30-second forward stale-data veto. Loss limits can veto a liquidation,
leaving an unfinished historical attempt; this is recorded, not bypassed.
Accepted PRD §9 operating risks remain unchanged.

Amendment 21 is a research counterfactual. Separate evidence of actual action,
cash and execution handling is required before forward promotion. Even a
profitable historical result does not by itself put this version in the
ready-for-live queue. No artificial Sharpe, p-value or deterministic-strategy
paper-minimum gate is added. Follow-up **`tradingbot-gx2`** covers the unchanged
deterministic rule's actual action/cash handling, fresh quotes, forward EIA
publication pipeline and promotion checklist using the existing Alpaca paper
account. It must preserve the evaluated rule and consumed holdout; this study
does not authorize new capital, accounts, keys or venues.
