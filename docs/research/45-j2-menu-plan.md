# J2 numeric-feature menu trader — prospective paper plan

Owner-authorized J2 (`tradingbot-pxk`), frozen before any J2 model request or
order, 2026-10-02. No historical LLM replay establishes an edge. This is the
single plan and completed paper-admission review; forward results belong in
the trials ledger and weekly report.

## Fixed policy

- Use the existing 40-symbol IEX universe and official regular-session
  quarter-hour boundaries, starting at 09:45 ET. The shared runner owns the
  original 30-second deadline, actual fill ledger, T+1 cash, one entry attempt
  per symbol per day, and liquidation beginning five minutes before the actual
  close. No J2 price stop is added; its exits are model EXIT or the code close.
- Numeric observations only: returns, trend, RSI, volatility, volume, market
  and sector context, clock, scheduled-event timing and execution quote. J2
  excludes headline text from the model request. Unknown features remain null.
- Four equal position slots within the arm's $35 simulated ceiling: a full
  slot is $8.75. At each boundary, review each holding and up to the remaining
  number of entry slots. Rotate the fixed universe by four symbols per
  quarter-hour, scan in that order for eligible flat names, and stop when the
  free slots or settled full-slot cash capacity run out. This code selection
  occurs before any model response; no outcome-based reranking or top-ups.
- Flat menu: Choice **ENTER / SKIP** and Score conviction **weak / fair /
  strong / overwhelming** (indices 0/1/2/3). Enter only when the choice is
  ENTER, P(ENTER) >= 0.60 and expected numeric conviction score >= 2. Score is
  the probability-weighted ordinal value returned by the validated wrapper,
  not confidence or the modal label. Size is slot share times
  `max(0.5, score/3)`; strong = two-thirds and overwhelming = full slot.
- Holding menu: Choice **HOLD / EXIT**, with the same conviction question for
  audit. A validated EXIT closes the confirmed residual regardless of entry
  conviction/probability thresholds. A missing/invalid answer holds; code
  close and risk controls remain independent of model availability.
- Code entry vetoes: source quote older than 30 seconds or from the future,
  crossed/nonpositive quote, spread > 10 bp, absent/currently incomplete bar
  state, unknown macro coverage, event-collection halt, or a scheduled macro
  release within 15 minutes either before or after the observation (inclusive).
  Require two contiguous complete current-session intervals and finite 15m
  return/current close; other warmups remain explicit. Macro/spread entry
  filters do not prevent model exit consideration with a valid fresh quote.
- Every question requires the proposed ticket's expected move to beat the
  runner's spread + regulatory fees + conservative model-cost hurdle. Typed
  calls go only through `ai/jev.py`, alias `jev-latest` pinned to reviewed
  `jev-1.13.0`, within its unchanged global $20/month cap. No discretionary
  retries, historical questions, external model calls, or paid data.

## Control and evidence

One virtual random twin has its own holdings, entry reservations, settled
cash, memory and trial row. It uses the identical candidate policy and costs,
matches real decision pass rates separately for entries/exits, and shuffles
the passing size-factor distribution. Model outages produce no random passes.
Different holdings/cash and actual versus modeled partial fills remain visible;
virtual BBO fills are diagnostics and never enter the real Alpaca ledger.

Forward qualification is the owner's J1–J4 rule: at least seven calendar days
from first observation, at least 30 completed real round trips, and positive
P&L after all fees and actual/reserved model costs. Flatness, pending orders,
code/source integrity and unchanged risk controls must also pass. Rejudge
weekly while paper continues; readiness only queues `ready-for-live`. Twin
outperformance, p-values and calibration are informational, not added gates.
At freeze: no J2 trades, no return/drawdown estimate and p-value null. Market
regime coverage and real-fill fidelity are unmeasured, to be reported as
forward data accumulates. Every changed variant requires a new trial identity.

## What could blow up this account?

**Tail / gap risk.** Long stocks/ETFs can gap or halt. No price stop is part of
J2. The $35 arm ceiling and unchanged -40% allocation kill bound intended
exposure but do not guarantee fills or maximum realized loss. The risk veto,
stale feed, outage or process death can prevent closing; residuals are incidents.

**Adverse selection.** Free IEX is partial market coverage, and marketable
limits may fill against informed flow. Ten-bp entry spread and the symmetric
15-minute macro exclusion reduce known exposure, not unscheduled announcements.
There is no claim of queue priority or trade-through maker fills.

**Counterparty / venue.** Alpaca paper fills differ from future live fills.
One broker/feed, a local Mac and trade-only credentials remain dependencies.
The owner's accepted absence of dead-man cancellation/startup reconciliation
and permission to run checked-out code remain unchanged. No new venue or key.

**Untrusted inputs.** Model input contains numeric data and bounded labels,
not headline text. Typed outputs cannot invent symbols, sizes, prices or tools.
Source values remain untrusted observations; missing or invalid inputs fail
closed and execution always passes the code-owned risk checks.

**Reproducibility.** The provider is nondeterministic. Frozen code/parameters,
immutable observations, provider answer/probability/cost receipts and saved
control seeds reproduce the recorded choice, not an invented historical
forecast. A mixed source identity cannot qualify the original experiment.

**Correlation.** J2, the other Jev arms and TOM share long equity exposure,
Alpaca and the existing $140 simulated cash book. The real account-wide -$50
daily halt includes all costs. Four J-arm ceilings do not fund separate cash
books or reserve cash ahead of TOM. Settled cash and actual commitments win.

## Admission decision

Paper evidence collection only, reviewed by OrangeCove on 2026-10-02 under
the owner's explicit AI-forward amendment and J1–J4 authorization. The older
checklist's structural-only/historical-profit requirements are superseded for
this class by current PRD §§3–4; no historical profitability is asserted.
Same pure policy callbacks serve replay/paper/live, but no live transport is
activated. Historical fidelity is inapplicable; future live fidelity remains
unproved. Requested simulated allocation $35 within the existing $140 book;
actual capital added $0. Per-strategy -40%, global -$50/day, equity allocation
cap, 30-second freshness and five-errors/minute limits are unchanged. No
account, venue, credential, funding change or public post is made. Admission
and its virtual twin are logged after the implementation passes focused tests.

Validation: 85 distinct policy/event/state checks plus one complete runner /
fake-broker round trip. Entry probability and expected-score boundaries,
source timestamps versus actual quote receipt, the unchanged original
deadline, symmetric macro exclusions, outage/coverage unknowns, numeric-only
model input, matched random sizing, actual fill accounting and an
unscaled exit are covered. Database integration uses rollback-only isolated
state and fake model/HTTP responses; it creates no forward performance evidence.
