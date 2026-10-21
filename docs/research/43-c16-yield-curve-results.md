# C16 yield-curve-conditioned duration — source result

2026-10-02, OrangeCove; `tradingbot-1rl`. **SIGNAL_EVIDENCE_GAP** before strategy
replay. The fixed 0/1 percentage-point rules remain unmeasured. TLT prices pass;
historical DGS10/DGS2 vintage evidence was not obtained. This scoped failure is
not a negative alpha finding, a price DATA_FAIL, or evidence of historical cash
signals. Hold at source preparation; actual allocation **$0**.

## Evidence and access limits

Reused the unchanged C10 TLT source, SHA-256
`0580a449609e4a6597d6ac1d8988c349e60c87473e9c4aded6e50b16e4d7ddbd`.
Its 22 underlying files were hash-checked; the Nasdaq close × Alpaca-only
adjustment-factor comparison was recomputed locally. Yahoo's 5,218 adjusted
sessions span 2006-01-03–2026-09-30. **2,509/2,511 paired returns (99.92035%)**
agree within 5 bp. The 2019-05-28/29 discrepancies and 2,706 earlier unpaired
returns remain in the source audit; the primary interval was not shortened or
patched. These prices overlap previous TLT research and do not constitute
pristine unseen evidence.

[ALFRED's download help](https://alfred.stlouisfed.org/help/downloaddata) describes
historical vintage snapshots and real-time periods. The web reader exposed the
DGS10 download form, but no vintage panel. Local requests to the help and DGS10
form timed out; the DGS2 form connection closed without a response. An exploratory
graph CSV request timed out, and the web reader could not open that graph/CSV.
Its guessed vintage parameter semantics were therefore never validated. The
browser tool reported no available browser. No usable vintage-response bytes
were archived. These observations establish a session access gap, not permanent
unavailability of ALFRED history.

The [documented observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
supports vintage dates but requires a registered key. No FRED/ALFRED key is
configured; none was requested or created. Discovery returned paid alternatives,
none invoked. Data spend **$0**. Current revised yields, synthetic vintage dates
and presumed cash decisions were not substituted. A future continuation needs
free immutable DGS10/DGS2 responses and metadata proving the original
decision-time availability before any replay; it must preserve these failed
attempts and the original thresholds, costs and interval.

Local audit: `data/research/c16-yield-curve/audit.json`, SHA-256
`73a244f31364331b31528fe5dd998f7bb779b779fcc6bf2be82e47a13fa8ea7f`.
It pins 25 inputs and four code files, with raw request errors, qualified
documentation findings and all price discrepancies/unmatched dates. No full
vintage download or actual strategy reactor is claimed. The source-only auditor
has **29 passing focused checks** (22 C16, seven shared price checks), including
rejection of revised-value substitution and invented historical cash absence,
immutable evidence, the frozen cutoff, null performance and idempotent ledger
recording with no final spend. One unrelated websockets deprecation warning.

## Trials and unmeasured outputs

| Slope threshold (percentage points) | Per-side cost | Training state |
|---|---|---|
| 0.00 | 5 bp | Unattempted: signal evidence gap |
| 0.00 | 10 bp | Unattempted: signal evidence gap |
| 1.00 | 5 bp | Unattempted: signal evidence gap |
| 1.00 | 10 bp | Unattempted: signal evidence gap |

Failed source-audit **trial 5648 / strategy 10570** was recorded after source
freeze commit `2d1facec483eedd7b4b140cd72efecd5c7c751b6`. It remains at idea / $0,
with all eight performance columns null. Stored-only verification revalidated
25 input hashes, four committed code hashes and exact trial parameters, finding
one source trial, zero orders/fills and zero C16 final trials/spends. Local
`verification.json` SHA-256:
`60ece73791bc4ddf160858323e5dbb105cd48ccd4d470823bc50f0ebfa87bf39`.
No selection or final was run. The 70/30 boundary remains
`2020-07-10T14:24:00Z`; the canonical `c16` final remains unspent. Failure to
obtain vintages cannot count as four tested variants or zero-return outcomes.

Gross/net P&L, fees/slippage, trade/fill counts, turnover, exposure, settled-cash
delays, rejected orders, ending holdings, marked drawdown, years/regimes,
slope occupancy, stale-observation decisions, TLT/cash benchmarks and luck
p-value are **null / unmeasured**. No strategy execution occurred. Zero actual
order/fill rows in the source trial is an audit fact, not an estimated historical
trade count. No p-value sample or profitability claim exists.

## Promotion checklist and account risk

**Edge/evidence:** macro-conditioned duration is permitted under amended PRD §3,
but slope is not a term-premium estimate and no profitable edge is established.
Rules and exit/sizing are frozen in the plan. Historical profitability, marked
drawdown and multi-regime checks remain unmeasured; statistical adequacy is
unknown. Monthly signals may produce very few independent exit-month clusters.
The planned 30-month/30-exit-cluster bootstrap remains a reporting rule, not a
new promotion hurdle.

**Fidelity:** backtest/paper/live equivalence is not established. No strategy
reactor, historical execution run or funded transition is admitted. Any later
implementation must verify the original lag/vintage chronology, next-open
execution, settled cash and immutable single-use final before measuring outcomes.

**Tail/gap:** inflation or rate shocks can sharply lower TLT even with a steep
curve. The $140 ETF slot bounds initial notional, not gap losses or exit prices;
the −40% kill and −$50 halt can veto liquidation after damage occurs.

**Adverse selection:** future next-open fills face overnight information and
spread/gap costs. Prediction-market maker fill caps and quote-pull protections
do not establish ETF execution quality; the frozen adverse-cost assumptions
would still need forward verification.

**Venue/operations:** dependence on Alpaca, feeds and the owner's Mac remains.
Accepted no-dead-man and no-startup-reconciliation risks are unchanged. Any
eventual trading key must prohibit withdrawals; no new key/account is involved.

**Untrusted inputs/reproducibility:** external bytes are data, never instructions.
Price inputs and access-attempt evidence are immutable and locally auditable.
The unavailable vintage evidence prevents deterministic causal signal replay;
current observations cannot repair that gap.

**Correlation:** duration exposure overlaps C10 and other bond allocations, and
may concentrate rate-shock losses under the global halt. This task measured no
correlation or diversification benefit. Familiar historical regimes and reused
TLT data limit claims of independent discovery.

**Limits/decision:** PRD §6/§9 are unchanged: −40% strategy kill, −$50 global daily
halt, $140 maximum ETF slot, 30-second stale-data halt and five API errors/minute
halt. No capital, venue, account, key, subscription, public post or real order.
**Hold at idea/source preparation**, allocation $0; no paper/live promotion or
ready-for-live claim. Close the research bead as an honest scoped evidence
failure while preserving the original final for a properly sourced continuation.
