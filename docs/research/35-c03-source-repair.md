# C03 older VNQ cash repair: partial recovery, admission held

2026-10-01; `tradingbot-2wh`; reviewer NavyLantern. **DATA_FAIL before any C03
ranking, signal, strategy return or final.** Four 2006 cash amounts and payment
dates now have corroborating records. A June 2009 entitlement-date conflict
remains unresolved. C03 stays at idea, with $0 allocation.

The SPY/IEF/GLD/EFA/VNQ universe, 2006-01-01 to 2026-10-01 exclusive interval,
2020-07-10 14:24 UTC split, original three variants and six training cost cases
are unchanged. The [repair plan](35-c03-source-repair-plan.md) was committed
before outcomes. Source trials 3516 and 4067 remain historical failed attempts.
Committed implementation `f3d1aa2` recorded failed source **trial 5314**.
The [stored-only ledger verification](35-c03-source-repair-ledger.json) confirms
null performance, zero C03 orders/fills/finals, unchanged idea/$0 strategy and
all nine protected rows (seven prior finals plus 3516/4067) unchanged. Every
recorded code dependency matches its committed bytes. Conditional follow-up
`tradingbot-h5b` is labelled `blocked:source-evidence`; this audit attempt is closed.

## What the new records establish

The original issue was not resolved by copying the ordinary dividend's payment
date onto an unexplained residual. [Dividend.com](https://www.dividend.com/etfs/vnq-vanguard-real-estate-etf/)
separately identifies $1.133 ordinary income and $0.361 long-term capital gain
on December 22, 2006. Their sum is $1.494.
[Stock Screener](https://stock-screener.org/vnq-dividend-history) explicitly
reports that full total with the December 29 payment date. Its four 2006 rows
also agree with Yahoo's original full amounts:

| Ex-date | Full cash/share | Reported record date | Full payment date |
|---|---:|---|---|
| 2006-03-20 | $0.404 | 2006-03-22 | 2006-03-29 |
| 2006-06-26 | $0.678 | 2006-06-28 | 2006-06-30 |
| 2006-09-25 | $0.678 | 2006-09-27 | 2006-09-29 |
| 2006-12-22 | $1.494 | 2006-12-27 | 2006-12-29 |

[Investidor10](https://investidor10.com.br/etfs-global/vnq/) corroborates all four
full amounts and payment dates. Its other date column is preserved under the
actual label `data com`; it is not silently treated as an ex-date.
[Marketlog](https://www.marketlog.com/symbol/vnq-arcx/dividends) corroborates the
dates and rounded totals. Its two-decimal prices are a coarse diagnostic, not
replacement amounts or a wider execution-price tolerance. The old
[DividendHistory](https://dividendhistory.org/payout/VNQ/) December amount
matches the ordinary component and has the same payment date.

These are independently published secondary records, with unproven upstream
independence. No original issuer event notice was recovered. The audit labels
the four rows **secondary corroboration**, not complete source admission or
proof of separate upstream providers. It preserves every original raw file.

## June 2009 still prevents admission

The amount is $0.485 and the reported payment date is June 30 throughout the
exact-amount/payment sources. Entitlement differs:

| Evidence | Reported date |
|---|---|
| Original Yahoo, DividendHistory | Ex-date June 24 |
| [DivvyDiary's June 30 calendar](https://divvydiary.com/en/calendar/2009-june-30) | Ex-date June 24; amount rounded to $0.49 |
| Stock Screener, Marketlog | Ex-date June 25; record date June 26 |
| Dividend.com | June 25 in its generic `Date` column |
| Investidor10 | June 26 under `data com`; payment June 30; no ex-date proof |

The full Stock Screener chronology has 83 in-interval events. Across matching
dates, its full amounts all pass the existing $0.0005 cash rounding bound.
The only missing Yahoo date is June 24, 2009; the only extra date is June 25.
An agreeing amount/payment does not decide which day's opening ownership earns
the cash. No majority vote, inferred settlement lag or strategy-position check
is used to dismiss this disagreement. No source date is changed.

## Primary search and remaining source work

Thirteen immutable public responses were captured, with URL, HTTP status,
retrieval time, length and byte hashes. Eleven succeeded; the direct 2007 SEC
report returned 403 and the indexed 2010 report mirror returned 404. Both
failures remain archived. The SEC web extraction shows an annual 2006 ETF cash
total of $3.254, but does not establish event/payment dates; it is supplemental
discovery, not original archived report bytes.

The current [issuer product page](https://advisors.vanguard.com/investments/products/vnq/vanguard-real-estate-etf)
limits distribution history to ten years. Four exact linked scripts were
followed to the distribution store. It fetches the existing fund endpoint with
a yield flag; no older-date query is exposed there. The previously archived
issuer response still covers 40 ex-dates from December 2016, so it does not
resolve June 2009.

The [NYSE Arca bulletin](https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/rule-interpretations/2008/NYSEArca-RB-08-95.pdf)
was archived and its first page visually verified. It identifies VNQ's
September 19, 2008 listing transfer from AMEX; it is not a cash-event notice or
a complete share-action inventory.

After the cash gate fails, full five-fund share-action admission and GLD's
2006–2007 independent price/action work remain unfinished. Earlier SPY repairs,
IEF/EFA distributions and seven primary auction reconciliations are revalidated
from their immutable bytes, without rerunning a strategy. An incomplete broker
history with no noncash rows cannot establish that no earlier actions occurred.
Amendment 21 still requires timely primary announcements for identified actions.

## Validation and decision

The machine-readable [audit](35-c03-source-repair.json) contains the row-level
checks, source hashes, June conflict, unchanged split and all six unattempted
configurations. The capture implementation snapshots match their recorded byte
hashes; additions to the source URL list are preserved. The code never generates
signals or invokes a replay engine.

**25 focused checks pass**, covering immutable archives, bounded requests,
headerless history continuation, component completeness, unreinterpreted date
labels, missing dates, source-only ledger guards and transactional idempotence.
The ledger test rolls back and verifies that neither strategy funding nor any
existing final row changes. P&L, fees, trade count, drawdown, regimes and luck
remain **null**, not zero. There is no selected winner or consumed C03 final.

Promotion checklist: the frozen hypothesis is relative momentum, permitted by
the owner's revised PRD §3. Entry/exit, sizing and costs are preregistered; source
feasibility fails. Profitability/statistics and backtest/paper/live fidelity are
unmeasured. Shared strategy execution remains a prerequisite, not a claim.
Decision: **hold at idea**, $0 allocation, no promotion. Every PRD §6 limit and
accepted operational risk is unchanged; no capital, account, key, paid endpoint,
order or public post was added.

### What could blow up this account?

**Tail and gap risk:** cross-asset concentration can still lose sharply in equity,
duration or REIT shocks. The owner-approved equity slot is up to $140; the
prediction-market $25 cap is not substituted. A gap can overshoot the unchanged
−40% strategy kill before an exit is possible.

**Execution and adverse selection:** monthly open-reference fills plus 5/10 bp
costs are research assumptions, not executable fractional auction quotes. Source
dates change entitlement and cash; a fabricated payment can fund an impossible
rebalance. Actual forward execution, fees and slippage must be checked later.

**Venue and operation:** an Alpaca/feed outage or Mac failure can interrupt
execution. The owner accepts no dead-man and no startup reconciliation. This
audit does not change those choices or activate an account; existing keys and
withdrawal restrictions remain as they are.

**Untrusted inputs and reproducibility:** external pages supply data only.
Parsers verify fields, components and raw hashes; agreement among websites does
not prove independent sourcing. The frozen source audit is deterministic, and
its genuine failures remain visible instead of becoming invented zero returns.

**Correlation:** C03 shares SPY and relative-momentum exposure with existing
candidates. Joint equity/bond/REIT losses can concentrate risk against the
unchanged −$50 daily halt. No diversification credit is earned by this failed
source attempt.

Recovery requires new primary or otherwise decisively reconciled June 2009
entitlement evidence, followed by the remaining full-period source checks.
Re-running these same pages or selecting whichever date favors outcomes is not
a repair. The original three variants and once-only final policy remain fixed.
