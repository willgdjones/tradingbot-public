# C14 source and cash-collateral feasibility plan

2026-10-01, OrangeCove; `tradingbot-ddw`. This is the authorized bounded
source/capital task, with alpha replay parked. The hash-bound
[batch 2 specification](25-candidate-shortlist.md) remains binding.

- Keep F/NOK/OPEN/PLUG/SNDL, the weekly positive 63-session/negative 5-session
  total-return rule, lowest-five-session-return ranking and ticker tie break.
- Keep next-open entry S, expiry first (21–35 days, nearest 28, earlier tie),
  then highest listed strike at or below 95% of the decision raw close.
  No lower-strike or next-symbol fallback rescues an unaffordable selection.
- Keep S+5 then S+10 exchange-session exits, at least two sessions before
  expiry; no overlapping option/assigned-stock cycle, wheel, roll or averaging.
- Keep 2024-02-01 to 2026-10-01 exclusive and 2025-12-13T02:24Z holdout start.
  Both $0.01/$0.02 adverse per-share costs yield four planned training cases.
  Source failure leaves every case and the final unattempted.
- Standard American USD contracts must deliver exactly 100 shares. Full
  `100 * strike` plus all fee/assignment/stock-exit reserves must fit
  `min(0.95 * decision equity, 140)` and settled cash before premium credit.
  Derive this necessary bound without screening quotes or counting events.
  Unknown reserves or missing chains mean unknown affordability, never zero.
- Re-audit the eight original options queries, eleven raw pages and 38,823
  records. Reuse C13's twelve immutable primary-documentation/current-paper
  capability receipts by exact hash and original timestamp. No new account
  GET or quote/bar/trade probe is needed to restate their existing limitation.
- Review level-1 cash-secured-put permission and assignment semantics for this
  candidate. A paper permission observation is not live approval, settled
  slot cash or historical eligibility. DNE for a held long option cannot
  protect a short writer against someone else's exercise.
- If historical executable BBO/chain admission still fails, stop before
  signal/return calculation. Explicitly leave historical action/deliverable
  chronology, exact fees/reserves, settlement, assignment/notification timing,
  liquidation and underlying-price admission incomplete. Never assume no
  early assignment or substitute a stress scenario for historical proof.
- Apply Amendment 21 to option deliverables and assigned stock; causal notices
  and executable pre-action exits are prerequisites, not inferred from current
  metadata. All PRD6 limits and accepted PRD9 risks remain unchanged.

Monid discovery returned paid chain/transaction tools; none is used. Current
primary web documentation may cross-check mechanics, but only verified archived
bytes support the stored source decision. No paid data, new account/venue/key,
permissions, capital movement, public post, forward activation or order.

Commit the audit implementation/evidence before recording one idempotent failed
source trial with null performance and the four unattempted cases. Verify prior
finals, SPY paper 3298, source failures, venue metadata and risk-limit bytes remain
unchanged. Complete the hold/account-risk review; idea/$0 is the disposition if
the frozen prerequisites fail. A source failure is a valid completion, not a
profitability or zero-affordable-events result.
