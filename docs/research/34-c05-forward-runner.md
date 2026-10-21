# C05 durable forward paper contract

Frozen 2026-10-01 before activation. Bead `tradingbot-dk3`.

Status: implementation complete; source admission held before activation.
The [machine-readable decision](34-c05-forward-runner.json) records failed
preparation **5311**, using committed runner `6e921b5`: zero orders/fills, null
performance metrics, no activated allocation and no new historical result.
The historical evidence and account-risk review in [report 27](27-c05-forward-readiness.md)
remain binding. Training 3959 and consumed final 3964 are never replayed.

The unchanged `CommodityTrend` reactor remains SHA-256
`66da5a97b2d40138a578198c331f5fcad774cc912944b5d7633624db53321778`.
Its five funds, 126-session positive total-return signal, monthly decisions,
five 19% sleeves, 5% reserve, $140 slot, fee reserve and quantity floor stay fixed.

## Observation and execution windows

- A close observation is admitted only from the regular close through 15 minutes
  after that close. A complete fresh 127-session adjusted vintage replaces each
  fund's previous adjustment basis; it is never appended across stale vintages.
  The final daily close is then delivered once to the unchanged reactor.
- Completed-close equity uses the same observation's complete portfolio marks.
  A source observation is not backdated to the exchange timestamp. Monthly
  signals and targets persist before the opening execution session.
- Opening decisions and submissions occur in `[regular open, open + 60 seconds)`.
  Every quote must be from the current regular session and at most 30 seconds old
  at the common decision time and again under the connector lock. The submission
  deadline is the earliest of this window and any required quote's expiry.
- Reductions precede buys. Every submitted reduction must be terminal with
  complete fill receipts before buy sizing. Unknown or still-active execution
  holds the phase; partial/rejected reductions require review. No off-window
  catch-up, quantity top-up, or uncertain POST retry is allowed.
- A missed close never creates a retrospective monthly decision. A missed open
  is recorded once; ordinary pending targets can wait until the next regular
  opening under the unchanged reactor's cash-delay semantics. Forced exit
  failure/dust, partial/rejected fills or a late/conflicting action holds new
  decisions for review. Existing known orders remain explicitly pollable.
- Experiments have an explicit terminal session. Its first-minute opening
  reduction liquidates owned shares, with no terminal buy. A missed/vetoed exit
  remains unresolved inventory and an incident; it is not reported as flat.

## Source and action admission

Each admitted observation binds raw calendar, adjusted price, independent close,
issuer-watch and broker-action receipts and their actual first-seen times.
Every fund must have a documented issuer review, including ordinary income;
an empty broker action page cannot act as issuer clearance. Conflicts, changed
receipts, unsupported actions and gaps stop admission before signals.

C05 uses its own Amendment 21 action schedule: decision at the close two regular
sessions before ex-date, exit at the preceding session's open, remain flat through
the latest ex/effective/share-exchange/payable/expected-delivery date, and re-enter
using the latest completed monthly signal and preceding-close equity. Actual
payable remains nullable and can precede ex-date for supported historical action
types. The generic split scheduler is not substituted. A notice first observed
after the causal decision window cannot be backdated.

Ordinary distributions use actual ledger ownership immediately before ex-open,
an issuer-backed receivable, and modeled cash at the first regular open strictly
after payable. Those records are distinct from actual broker nontrade credits.
Missing paper dividends do not invalidate an admitted issuer entitlement; they
also do not become actual cash. Share conversion and cash-in-lieu require actual
broker evidence before treatment fidelity can be certified.

## Shared cash and durable execution

The existing venue-wide $140 book remains the only virtual funding source.
SPY trial 3298 and C08 share its cash, pending reservations, account fee accumulator
and complete portfolio risk marks. Margin buying power cannot supply cash.
Sale proceeds require documented settlement completion and a subsequent regular
opening; calendar T+1 alone is insufficient. Modeled income can affect strategy
equity while transport cash remains capped by the uncredited shared cash book.

Each decision, target, attempt, request ID and receipt persists independently of
the reactor. A durable attempt is written before calling the connector; the
connector separately persists the reservation before POST. Restarting does not
submit an uncertain attempt again. Known-order polling is explicit, not startup
account reconciliation; accepted PRD §9 behavior remains intact.

The shared evidence guard must be supported by every active Alpaca consumer
before the account is opted in. Implementation tests are not execution evidence.
Actual fractional opening fills, costs, partial/forced exits, dated cash release
and announced-action/share/cash treatment remain required before live review.
Quiet periods and empty activity responses cannot establish action fidelity.

## Promotion and account-risk review

This implementation changes no promotion criterion, allocation or PRD §6 limit.
The existing 10 bp historical scenario, diagnostic final after prior USO inspection,
training 35.24% drawdown relative to the initial slot, regime breakdown and null
final luck estimate remain disclosed in report 27. No AI 7-day/30-trade quota or
new p-value gate applies to this deterministic rule.

**What could blow up this account?** Correlated commodity gaps, concentrated
metals gains, futures roll changes, fractional opening spreads, data/issuer delays
and an incomplete forced exit can consume the slot. A risk-vetoed sell may leave
inventory; neither the kill threshold nor a limit order guarantees a loss ceiling.
Alpaca/IEX/source outages and Mac downtime remain accepted operational exposures.
Complete shared marks, observed fees/income, causal source reviews and conservative
cash gates provide evidence, not guarantees. Paper omits actual dividends/fees and
does not prove live fills or share conversions. No live keys or orders are added.

## Implementation validation and remaining evidence

The 2026-10-01 bounded watch retained 33 original files and reused three USCF
receipts with their original hashes and observation times. All five funds have
127 completed closes through October 1, with independent raw IEX prices inside
the original 1% audit bound. No historical or current strategy signal was run.
DBA's issuer product request returned HTTP 406 with no body. USCF's observed
dynamic notice scripts returned HTTP 500 in the companion C08 diagnostic capture.
Linked issuer documents remain unreconciled; no fund is declared action-cleared.
The broker action query contains one prior DBA ordinary payment (ex December 22,
2025; $0.91237; payable December 26), which does not establish complete issuer
coverage. No nontrade activity was returned. These are a failed source admission,
not execution, dividend-credit or share-treatment evidence.

The immutable negative review is `data/forward/c05/review-20261001-held.json`.
It binds every captured file and the issuer notice inventories. The implementation
passes 66 focused checks: 17 runner, 11 source, six state, 29 shared-account and
three C08 income-queue tests. The 23 existing C08 runner tests also pass. Earlier
21 SPY compatibility tests cover the optional shared guard and unchanged default.
Tests use synthetic broker fixtures inside rolled-back Postgres transactions;
none count as actual execution evidence.

Every admitted ordinary event is queued before ex-open under the venue lock.
All consumers then derive each owner's receivable from pre-ex fills before the
first risk check, even if C05 is offline. Same-ex buyers gain no entitlement;
pending pre-ex orders prevent known ownership. Later reviewed receipts reconcile
with the queue without double counting. These records never credit actual cash.

## Operator runbook

1. Capture a fresh five-fund watch with `uv run python -m
   tradingbot.forward.c05_sources --output data/forward/c05/<new-watch>
   --through YYYY-MM-DD`. Preserve any reused public receipt's original time.
   Resolve linked issuer announcements and every broker/nontrade discrepancy.
2. Create dated immutable issuer-action reviews with `review_action`, then a
   complete daily `review_watch`; admission must succeed without overriding a
   missing source. A first review is retained on later daily watches. Do not
   reinterpret the negative October 1 review as approval.
3. Prepare a disabled finite experiment with `uv run python -m
   tradingbot.forward.c05_runner prepare --through YYYY-MM-DD --review-ref
   <receipt-reference.json>`. Every rejected preparation remains in the ledger;
   no preparation initializes another cash book or activates orders.
4. Review the account identity from `paper_evidence.migration_identity`, stop
   active account consumers, and use `enable_account_guard` with its exact
   immutable review. Its process locks refuse an active runner or changed
   identity. SPY3298 remains the existing trial. This migration has not been run.
5. Complete a current promotion/account-risk decision before `activate` with
   the prepared trial and decision receipt. Run only that trial with `run`; its
   process lock prevents duplicate workers. Bind fresh admitted watches using
   `use-review` before their expiry and before opening decisions.
6. Import actual dated sale-completion proof with `record-completion`; a nominal
   settlement-date label cannot release proceeds. Preserve each execution's
   decision/submission/fill time and cost, actual versus modeled fees/income,
   partial/forced exits and action share/cash credits. Holds preserve prior
   attempts and require explicit reviewed resolution; never delete or retry them.

The next possible new monthly decision after this capture is October 30 close,
with a November 2 opening attempt if all admission gates pass. No earlier signal
is reconstructed. Completion requires flat terminal inventory; timely executions
discovered after the opening window can close the experiment without new orders.
The runner exits after recording completion, which still requires a separate
fidelity and promotion review. No scheduled order worker is installed by this slice.

## Ledger verification and hold decision

Stored-only verification matches every implementation dependency to its committed
bytes and the failed trial to its full-row hash. Before/after comparison retains
training3959, all seven existing final rows, SPY3298, preparation4579 and C08
preparation5195 unchanged. The venue metadata and sole $140 cash book are
identical; no guard is opted in and there are zero account orders/fills/positions.
C05's existing strategy status/allocation remain unchanged. These checks do not
rerun a historical test or submit another preparation.

The promotion checklist decision is **hold**, dated October 1, reviewer
OrangeCove. The deterministic rule and stored positive after-fee training/final
results are retained, with the drawdown/regime limitations above and in report27;
the final luck estimate remains null. The same evaluated reactor is used. Source
admission, actual execution and share/cash fidelity are incomplete, so the
implementation itself grants neither paper activation nor live readiness.
No additional allocation, capital, account, key, venue or public post is requested.
The PRD6 limits and all accepted PRD9 operational risks remain unchanged.

Implementation bead `tradingbot-dk3` is closed with this explicit hold.
Conditional source repair, account admission and actual scheduled forward
evidence remain in **`tradingbot-lsr`**, labelled `blocked:source-evidence`.
That follow-up preserves the October30/November2 earliest new monthly cycle and
all remaining execution/action/cash requirements; it cannot clear itself using
unit tests, empty notices or an uneventful period.
