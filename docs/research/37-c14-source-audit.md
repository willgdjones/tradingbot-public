# C14 cash-secured put: source failure; historical affordability unknown

2026-10-01, OrangeCove; `tradingbot-ddw`. **DATA_FAIL; hold at idea/$0.**
The approved source bundle cannot establish historical executable option
quotes or full decision-time chain membership. The required early-assignment
and stock/cash lifecycle model is also unadmitted. Both holding variants,
all four training cases and the final remain unattempted. This completes the
bead's permitted source-feasibility route; it establishes neither a return
result nor zero affordable events.

[Machine-readable audit](37-c14-source-audit.json),
[C14 source review](37-c14-source-review.json),
[frozen plan](37-c14-source-plan.md),
[original specification](25-candidate-shortlist.md).

## Frozen scope and evidence reuse

F/NOK/OPEN/PLUG/SNDL and the weekly positive 63-session/negative 5-session
total-return rule remain fixed. Rank the weakest five-session return, then
ticker; choose the expiry before the strike; use the original next-open entry
and S+5/S+10 exits. An unaffordable selection cannot be replaced by another
ticker or farther-out-of-money strike. Source interval remains February 1,
2024 through October 1, 2026 exclusive, with the December 13, 2025 02:24Z
holdout cutoff. The $0.01/$0.02 cost cases and sole higher-cost final policy
are unchanged. No signals, underlying returns or option outcomes were computed.

The local audit rechecks all **eight queries, eleven raw pages and 38,823
records** from [harness 10](10-options-data-harness.md), plus all twelve C13
documentation/capability captures against their raw, manifest and capture-code
hashes. Original retrieval timestamps and the C13 interpretation are preserved;
the separate C14 review states their applicability here. No new quote/bar/trade
or account query ran. These are the approved bundle's limitations, not a claim
that no free historical source could ever exist.

| Reused evidence | What it establishes | Remaining C14 requirement |
|---|---|---|
| Current F/SPY catalogs and indicative chains | Archived response shape/current metadata | Historical membership across all five names, including expired/delisted series and deliverable changes |
| Two SPY contracts' February 2024 bars/trades | Bounded real observations | Candidate executable BBO, sizes, exit prices and liquidation marks |
| Indicative latest quotes | Timestamped modified observations | Historical tradable quotes; prints and midpoints are insufficient |
| Current primary trading/fee documentation | Present documented mechanics | Historical ticks/eligibility and a complete assignment/cash/fee implementation |

The archived [Alpaca feed definitions](https://docs.alpaca.markets/us/docs/historical-option-data)
distinguish indicative data from subscribed OPRA. Provider-unspecified
historical bars/trades cannot be relabelled as OPRA or treated as bid/ask.
Monid discovery found paid chain/transaction tools; none was run. No paid
source, new key or subscription is used.

## Capital constraint, fees and assignment

Let `E` be decision equity, `C` settled cash, `K` the selected strike and `R`
all required fee/assignment/stock-liquidation reserves. The frozen condition is:

```text
100 * K + R <= min(0.95 * E, 140, C), before premium credit
```

With initial `E=C=140`, the right side is **$133**. The necessary strike bound
is therefore **$1.33 before reserves**, reduced further by nonzero reserves.
Even with larger equity, the unchanged $140 slot caps this pre-reserve bound
at $1.40. A $1.50 strike obligates $150 and never fits. An illustrative $1.00
strike leaves $33 under the initial budget before reserves; it is not an
observed listing, acceptable quote, signal or admission decision.

These bounds establish no historical affordable-contract or event count:
both counts remain **null**, not zero. Premium income, margin buying power and
the rest of the account cannot fund this isolated collateral test. No contract
can be fractional, and an adjusted deliverable is not assumed to be 100 shares.

The archived [September 17 fee schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf)
and C13's fee-table review are preserved. A full C14 fee/reserve model remains
unadmitted, including selling, closing, assignment and stock liquidation with
account-level rounding. C13's two-long-contract example is not C14's cost.
An unspecified assignment charge is unknown rather than zero. A later model
must use the frozen dated schedule as an explicit current-fee historical
counterfactual and document settlement completion before cash becomes spendable.

The paper capability capture at **2026-10-01T21:55:30Z** has level 3 and no
blocking flags; level 1 includes cash-secured puts. It establishes permission
at that observation only, not live approval, historical tradability or settled
slot cash. [Trading API documentation](https://docs.alpaca.markets/us/docs/options-trading)
requires REST polling for assignment activities and says paper nontrade
activities appear the following day despite immediate position/balance updates.
That delay prevents assuming an assignment notification was available at a
desired next-open liquidation. A long holder's DNE cannot prevent assignment
of our short put.

Before P&L, a source-supported assignment/timing model must debit full strike
cash, book 100 shares, handle actual notification availability, and liquidate
at the next eligible supported open. It must cover unavailable exits, share
actions/entitlements and completed settlement. Neither a no-early-assignment
assumption nor a worst-case synthetic lifecycle proves historical execution.

After the execution gate failed, this task did not complete the five-name
underlying/action/delisting inventory, causal OCC notices and Amendment 21
exits, historical ticks, fee/reserve/settlement implementation, or strategy
reactor. Those gates remain prerequisites; they are not marked passed.

## Promotion review: what could blow up this account?

**Edge and proof.** The liquidity/insurance hypothesis and exact rule are
testable, but the equity-reversal motivation does not prove this option rule.
Fixed cheap-stock selection and previously inspected sources remain disclosed.
Profit after fees, trade count, dependence-aware luck p-value, marked drawdown,
regimes, benchmarks and execution fidelity are unmeasured. No AI 7-day/30-trade
replacement applies to this deterministic rule. The promotion checklist stays
incomplete; its older structural-only/$25 wording does not override current PRD.

**Tail and gap.** Cash security prevents borrowing; it does not prevent a cheap
stock from collapsing after assignment. Most collateral can be lost before
the −40% strategy kill or −$50 global daily halt can execute. Early assignment,
delayed notification, delisting or a halted share market can block the intended
exit. The [OIC mechanics](https://www.optionseducation.org/strategies/all-strategies/cash-secured-put)
likewise identify substantial stock downside and notification delay. Its
longer-term stock-acquisition examples are not C14's mandatory liquidation rule.

**Adverse selection.** Thin quotes, spreads, volatility changes and stale marks
can dominate premium income. Fills require genuine bid/ask and adequate size;
an indicative quote or touching print is insufficient. A failed exit preserves
exposure and fails winner eligibility; it cannot be replaced with a zero mark.
Prediction-market maker guards do not describe this option contract.

**Venue and operations.** Alpaca, the Mac, network and nontrade activity path
are shared dependencies. A sell-out or DNE instruction is not guaranteed
protection for the writer. The accepted no-dead-man and startup-reconciliation
risks remain unchanged. Existing keys remain in `.env`; no account permission,
capital or key is changed. There is no paper/live activation or option order.

**Inputs and reproducibility.** External pages are data, never instructions.
The audit binds the original specification, source review, raw archives,
capture/audit dependencies and unchanged risk bytes. Unknown or conflicting
action/timing evidence fails admission. The local source audit is repeatable;
it is not permission to rerun a consumed final.

**Correlation and allocation.** Assigned distressed-stock exposure can lose
with existing equity strategies, while shared venue failures affect all of
them. A separate $140 virtual simulation is not another funded paper cash book.
No reserve premium is counted twice. PRD6 limits retain their original veto,
including stale data and API-error halts; accepted PRD9 risks are not changed.

**Decision:** hold at idea, actual allocation **$0**. Reviewer OrangeCove,
2026-10-01. Reconsider only with materially new free historical BBO/listing
evidence for the unchanged scope, then satisfy all assignment/action/cash/fee
requirements before outcomes. No ready-for-live claim or public publication.

## Validation and ledger recording

All **46 focused checks pass**: 19 C14 cases, 15 C13 cases and 12 existing
options-archive cases. These cover frozen bounds/costs, full-collateral and cash
constraints, unknown affordability, changed receipt rejection, original archive
integrity, and idempotent null-failure recording without final consumption or
altering a funded strategy. Integration checks roll back their transactions.

```sh
uv run python -m tradingbot.research.c14_source_audit
uv run pytest -q tests/research/test_c14_source_audit.py tests/research/test_c13_source_audit.py tests/data/test_alpaca_options.py
```

The audit reads local evidence and writes its JSON report. Its explicit
`--record-ledger` mode requires committed code/evidence and the designated local
database, and records only the source failure.

Committed implementation **`3c07551`** recorded failed source **trial 5325**,
strategy **10085**, with all eight performance fields null. C14 has one source
trial and zero orders, fills or finals; its strategy remains idea/$0.
The [stored-only ledger verification](37-c14-ledger-verification.json) confirms
12 protected prior trials unchanged, including all seven consumed historical
finals, SPY paper 3298, C05/C08/C03 failures and C13 trial 5322. Venue records
and risk-limit bytes are unchanged. All 26 code/policy dependencies match both
the working files and the recorded commit; raw source/harness hashes also pass.
No strategy or recorder was rerun for this verification. The bead is closed
under its explicit source-failure route, with reconsideration conditions above.
