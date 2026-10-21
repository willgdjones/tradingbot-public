# C05 forward execution and distribution preparation

Date: 2026-10-01. Bead: `tradingbot-ggg`.

**Decision: hold before ordering paper; not ready for live.** The profitable
historical study remains intact. This preparation provides read-only account,
source and quote probes, plus tested trade-cash and ordinary-distribution
accounting helpers. Opening fills, an admitted source/action watch, durable
execution state and integrated cash/fee/risk accounting are still required.

The [machine-readable decision](27-c05-forward-readiness.json) binds both
immutable captures, source hashes, unchanged training/final rows and failed
preparation **trial 4579**. It contains zero orders/fills and null result
metrics; the strategy remains in backtest status with $0 activated.

## Frozen evidence

The [historical report](23-c05-blackout.md) and its source/selection/final
receipts remain authoritative. Training **3959** and permanently consumed final
**3964** share version
`de0dad8696f3603a0ebcde01bbe2f9333e037db5a22d03b4e7c01f8336924320`.
The preparation reads stored rows; it does not run a strategy, compute a new
signal, replay a final or select another cost case.

| Existing 10 bp evidence | Net after fees/income | Round trips | Maximum marked drawdown | Monthly-block luck p |
|---|---:|---:|---:|---:|
| Selected training | +$30.42 | 57 | $49.33 / 26.75% from peak | 0.264 |
| Single final | +$47.08 | 34 | $30.31 / 18.25% from peak | null |

Training drawdown equals **35.24% of the initial $140 slot**, close to the
unchanged −40% strategy-loss budget. Final's 34 trips produce only 26 exit-month
clusters. Prior USO outcome inspection makes this diagnostic historical evidence,
not untouched confirmation. No p-value/Sharpe threshold or AI-strategy
7-day/30-trade quota is added to this deterministic rule.

| Calendar regime | Training marked net | Final marked net |
|---|---:|---:|
| 2008–2009 | −$4.52 | outside partition |
| 2010–2019 | +$15.24 | outside partition |
| 2020–2021 | +$19.69 | +$0.13 |
| 2022 | outside partition | +$9.44 |
| 2023–2026 | outside partition | +$37.51 |

The 2020–2021 entries cover only their respective sides of the February 2021
cutoff. UNG loses in both partitions; metals supply much of the historical
profit. Full sleeve, yearly and benchmark diagnostics remain in report 23.

Preserve `CommodityTrend` in `strategy/c05_commodity_trend.py`, SHA-256
`66da5a97b2d40138a578198c331f5fcad774cc912944b5d7633624db53321778`:
GLD, SLV, USO, UNG and DBA; strictly positive 126-session adjusted total return;
127 completed closes; monthly rebalance. Each active sleeve targets
`min(0.19 × current equity, $28)`; inactive sleeves stay cash. Preserve the
5% reserve, $0.01 entry-fee reserve, nine-decimal quantity floor, reductions
before proportional cash-limited buys, and original targets during cash delay.
Equality goes to cash. Do not substitute C08's different rounded-limit sizing.

## Probe contract

The collector uses existing paper credentials, GET requests and a read-only
database transaction. Its paper transport explicitly refuses submit/cancel.
It binds the account to the existing cash-book fingerprint, checks USD/active/
unblocked status and all five assets' eligibility/fractionability, and saves a
calendar, sanitized nontrade activities, corporate-action pages and public
documentation. Account identifiers, free-text activity descriptions and remote
exception bodies are excluded. A single capture-wide five-errors/60-second
budget stops further API requests using the unchanged PRD constants.

Quotes are re-aged at a common batch timestamp. All five must be within the
same regular session and at most 30 seconds old; a fresh premarket quote cannot
be called an opening quote after 09:30. Full spreads are reported. Neither a
fresh IEX quote nor a daily opening bar is an opening fill or evidence of the
historical 10 bp cost assumption.

Each ETF's 127-close coverage is checked against the captured calendar from
one current adjusted-history response. Historical exchange close time and
actual source observation/availability are separate fields. This verifies
coverage only: adjustment continuity, independent prices and issuer events
still need admission. Appending today's adjusted closes to an older adjustment
basis would corrupt the 126-session comparison.

Successful and failed bounded captures retain immutable, hash-bound files.
The recorder checks complete source universes, nested page references,
raw/metadata hashes, derived coverage/counts, failure summaries and original
historical-row hashes. It can append only an idempotent **failed preparation**:
zero trades, null P&L/fee/drawdown/luck results, no final consumption or promotion.

## Cash, income, fees and full portfolio marks

The existing Alpaca paper book is venue-wide, with $140 virtual funding and
SPY trial 3298 already attached. C05 cannot create another independent $140
balance or reset the broker account. A future adapter must cap available cash
by the conservative C05 book, shared reservations/book, broker cash/buying power
and remaining strategy cash after modeled costs.

The shared connector currently releases sale proceeds at New York midnight
on its calendar settlement date. The evaluated C05 adapter waits until the
first regular opening **after documented settlement completion**. The tested
trade-cash bridge preserves that delay, immediate fee debits and reservations;
duplicate fill IDs or missing release evidence fail. A nominal T+1 label is
not actual settlement proof. A Friday October 9 sale labeled for Tuesday
October 13 settlement becomes eligible on October 14's open only **if**
completion on October 13 is documented.

Ordinary cash distributions require issuer rate, ex-date, payable date,
currency and a primary receipt observed before the ex-open. Entitlement uses
shares owned immediately before ex-open: an ex-open seller retains the right;
an ex-open buyer does not gain it. Recognize a separate receivable at ex-open,
then modeled cash at the first regular opening strictly after payable date.
Event identity is symbol/ex-date/ordinary-cash, independent of vendor record
date. Duplicate rows are corrections to reconcile, never a second payment.
There is no fabricated execution fill or verified broker credit.

Alpaca paper omits dividends and regulatory fees. Therefore modeled payable
cash cannot increase the existing shared cash book automatically; an empty
nontrade response cannot disprove a legitimate issuer entitlement. Nontrade
queries use creation-time filters and preserve settlement fields separately.
Share conversions and cash-in-lieu need separately observed broker evidence.
[Paper specification](https://docs.alpaca.markets/us/docs/paper-trading),
[account activities API](https://docs.alpaca.markets/us/reference/getaccountactivities-2),
[mandatory corporate actions](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions).

The unchanged dated `EquityFeeBook` scenario is calculated independently of
broker-reported zero fees. One accumulator spans all five sleeves; actual
account-day totals would also include other strategies. Partial fills retain
their actual timestamps, quantities, fees and fee-policy versions.
[Alpaca fee schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf).

The current connector refreshes risk marks for only the submitted instrument.
Before C05 execution, supply fresh simultaneous marks for **all owned/pending
portfolio exposures**, including other strategies, plus modeled fees and income
receivables in equity/P&L. Five source quotes alone do not prove global risk
coverage. No −40%, −$50, stale-data, API-error or allocation limit changes.

## Action and execution contract

1. Persist source observation, admission and monthly close decisions. Only
   completed sessions on a coherent adjustment basis may enter the unchanged
   reactor. Freeze the actual opening window and missed-window policy before
   activation; today's afternoon quote cannot become an earlier opening input.
2. Preserve Amendment 21 and the **C05-local** action schedule in report 23:
   decide at the preceding close, exit at the prior regular session's open,
   and stay flat through the latest applicable ex, effective/share-exchange,
   payable and expected-delivery date. Missing actual payment dates stay null.
   Do not substitute the generic split helper; the historical SLV action has
   a payable date before ex-date. After the endpoint, re-entry uses the latest
   completed monthly signal and preceding-close equity for the affected sleeve.
3. Archive issuer announcements and broker action pages with first-seen times.
   Review all five funds, including ordinary distributions. Alpaca provides no
   guaranteed advance data-creation time; empty action pages are not clearance.
   [Corporate-action API](https://docs.alpaca.markets/us/reference/corporateactions-1).
4. Persist each decision, pending target, attempted tag, forced-exit state,
   client order ID and receipt before/after submission. The reactor clears
   intent state before fill confirmation, so durable orchestration must track
   partial/rejected/unknown orders separately. Never resend an uncertain POST.
   Forced dust below the minimum order size remains unresolved inventory.
5. Require fresh full-portfolio risk marks, shared cash reservations and
   conservative settlement evidence before each intent. Capture fractional
   decision/submission quotes and actual fills; compare achieved opening costs
   with the frozen 10 bp assumption. Preserve the evaluated reactor and risk
   vetoes when cash or a forced exit fails.
6. Validate partial/forced exits and announced-action treatment before live
   readiness. Late/conflicting announcements, incomplete exits or unverified
   share/cash credits hold the experiment for explicit review. A quiet period
   with no action cannot establish conversion fidelity. Complete a separate
   promotion review when sufficient actual execution evidence exists.

## Promotion review and account-risk record

**Edge and rule:** the preregistered commodity trend/risk-premium hypothesis and
explicit monthly entry/exit pass the historical after-cost profit gate.
**Statistics:** trade counts, drawdowns, regimes and null final luck estimate
remain disclosed above. The training loss excursion is material; forward risk
and execution fidelity need review. **Fidelity:** incomplete; cash timing, full
portfolio marks, income/fees, source/action admission and durable orchestration
remain gaps. **Decision:** hold, $0 activated, unchanged strategy backtest status.

**What could blow up this account?**

- **Tail/gap risk:** correlated commodity futures exposure, roll changes and
  overnight gaps can consume the slot before an opening exit. The prediction
  market $25 cap does not apply to these ETFs. The −40% kill is a veto, not a
  guaranteed loss ceiling or liquidation price; a vetoed sell can leave stock.
- **Adverse selection:** fractional marketable limits at an opening can meet
  wide spreads and repricing. Simultaneous sleeves are not independent fills.
  The prediction-market maker/event guards are inapplicable; quote freshness,
  full portfolio marks, fee reservations and risk vetoes remain mandatory.
- **Counterparty/venue:** Alpaca, IEX, Yahoo and issuer publication can fail or
  lag, and the Mac can disconnect or sleep. Accepted lack of a dead-man and
  startup account reconciliation remains unchanged. Existing paper access is
  not proof of live withdrawal restrictions; no live key is requested.
- **Untrusted inputs:** JSON, pages and corporate announcements are data only.
  Unknown schema, dates, symbols, currencies, action types and timing stop
  admission. No remote content becomes code or a model-generated trade signal.
- **Reproducibility:** persist raw source vintage, decisions, fills, fees,
  entitlement/release evidence and state so the hashed reactor's decisions can
  be reconstructed. Retrospective adjusted data cannot be backdated as an
  earlier observable signal; historical final evidence remains consumed.
- **Correlation:** the USO sleeve overlaps C08; gold and broad risk premia may
  correlate with other Alpaca strategies. The shared cash book and aggregate
  daily P&L matter. Five sleeves do not prove diversification from the −$50 halt.

## Reproduce the preparation

```sh
uv run python -m tradingbot.forward.c05_readiness \
  --output data/forward/c05-readiness/UNUSED-CAPTURE-NAME
uv run python -m tradingbot.forward.c05_readiness \
  --record-failed-preparation data/forward/c05-readiness/UNUSED-CAPTURE-NAME/readiness.json
```

Capture creates bounded immutable local files and sends no broker mutations.
The explicit record command appends a failed preparation only. No new account,
key, venue, capital, live order, public post or risk-limit change is authorized
by this report.

## Execution handoff

**`tradingbot-dk3`** tracks the durable runner, full portfolio marks, shared
cash/income/fee integration and subsequent actual execution/action evidence.
Coordinate its shared-book changes with C08 **`tradingbot-5l3`** and the running
SPY trial. These are remaining implementation/evidence requirements, not a
reason to replay the historical final or place an off-cycle test trade.

The captured exchange calendar places the next monthly close decision at
**October 30, 16:00 New York**, with the next regular opening **November 2,
09:30 New York**. This is the unactivated monthly schedule implied by the
frozen rule. It does not backfill the missed September 30 decision or activate
an order; source/action admission and all execution gates must first pass.

## Observed capture and audit

The final capture under commit `adc52f4` completed at **19:18:01 UTC** on
October 1. The account matches the existing cash book; all five assets are
active, tradable and fractionable. The book still has $140 available, zero
orders/fills/positions/reservations, and running SPY trial 3298. No balance or
strategy allocation was changed.

All five free adjusted-history responses supply the required **127 completed
sessions, March 31–September 30**, each within its own single captured vintage.
Coverage passes; signals and source admission remain false. The bounded
400-day lookback/65-day lookahead corporate-action query returned one ordinary
DBA dividend: ex/record December 22, 2025, payable December 26, rate $0.91237.
This is a historical vendor record requiring issuer reconciliation, not a new
entitlement or assurance that future notices are complete. The exhausted
nontrade query returned one account activity, none belonging to C05.

At the common **19:17:21.926 UTC** quote timestamp, all five quotes were in
the regular session and fresh. These are IEX observations, not NBBO execution
guarantees or opening fills:

| ETF | Bid / ask | Age (seconds) | Full spread (bp) |
|---|---:|---:|---:|
| GLD | $382.77 / $382.80 | 12.62 | 0.78 |
| SLV | $54.97 / $54.98 | 9.54 | 1.82 |
| USO | $149.65 / $153.32 | 6.45 | 242.27 |
| UNG | $10.16 / $10.17 | 11.32 | 9.84 |
| DBA | $28.11 / $28.12 | 12.98 | 3.56 |

The first capture is retained: UNG was 52.86 seconds old and DBA 116.47 seconds
old, so its complete quote batch failed. A fresh later snapshot does not erase
that operational limitation. USO's wide spread in both snapshots also prevents
using these observations to certify the 10 bp historical execution scenario.
The final capture made 24 remote calls with no API halt or probe failure;
the readiness hold remains because the integration and execution gaps persist.

Before ledger recording, the first capture exposed a Decimal/JSON equality
mismatch in the stored training luck metadata. The exact-string fix and
regression test were committed before the new capture. No failed-audit row or
historical replay was created. The final stored-only audit verifies all 36
child receipts, derived source summaries, unchanged 3959/3964 row hashes and
exactly one canonical C05 final spend, 3964. Trial 4579 is the sole preparation
for the final receipt and has no orders, fills, P&L, fees, drawdown or luck result.

Validation: **132 affected checks passed**, followed by **45 readiness checks**
after additional receipt-reconciliation cases and the metadata fix. Independent
read-only reviews checked cash, quote timing, API halts and receipt integrity.
The existing SDK deprecation warning remains. This assessment is complete;
actual execution readiness remains tracked in `tradingbot-dk3`.
