# C13 earnings straddle: source admission fails; affordability remains unknown

2026-10-01, NavyLantern; `tradingbot-0cm`. **DATA_FAIL, hold at idea/$0.**
The permitted evidence cannot support historical executable straddle prices
or decision-time option-chain membership. Neither entry variant was replayed;
all four training configurations and the final remain unattempted. This is a
source-feasibility conclusion, not a negative return or zero-affordable-events
result. [Machine-readable audit](36-c13-source-audit.json),
[source review](36-c13-source-review.json), [frozen plan](36-c13-source-plan.md).

## Evidence and scope

The original [batch 2 specification](25-candidate-shortlist.md) remains unchanged:
F/NOK/SNAP, entries three then five sessions before the announced release,
same-strike/expiry long call and put, original expiry/strike/exit selection,
$0.01/$0.02 adverse costs and $140 virtual cash. Source interval is
2024-02-01 through 2026-10-01 exclusive; the final starts
2025-12-13T02:24Z. No changed ticker, strike, horizon, cost case or permission
rescues admission. The roughly 9.6-month final is short even if sources improve.

Re-audited every original [harness 10](10-options-data-harness.md) request,
raw response checksum, record count and pagination chain: **8 queries,
11 pages, 38,823 records**, matching all published response-set hashes.
New work captured **11 primary documentation pages/PDFs and one current paper
capability projection**, each with retrieval time, URL and immutable hashes.
The account response is deliberately retained only as whitelisted fields;
its original response hash is recorded, but the full body is discarded.
No new candidate option quote/bar/trade query or earnings-event selection ran.

| Evidence | What it establishes | Missing C13 prerequisite |
|---|---|---|
| F/SPY current catalogs and indicative chains | Existing archive shape and current metadata | Full F/NOK/SNAP historical listings, delistings and deliverable chronology |
| Two SPY contracts' February 2024 bars/trades | Real bounded historical observations | Executable F/NOK/SNAP bid/ask, size, synchronized legs and liquidation marks |
| Current indicative quotes | Timestamped modified observations | Historical BBO or achievable opening/exit fills |
| Current primary documentation | Feed definitions and present trading mechanics | Evidence of past tradability and tick eligibility |

[Alpaca's current data documentation](https://docs.alpaca.markets/us/docs/historical-option-data)
still identifies the free feed as derived indicative quotes and delayed derived
trades; subscribed OPRA access is a different feed. The historical bar/trade
endpoints in this archive expose no feed selector and remain labelled
provider-unspecified. A trade price is not a bid or ask. This audit establishes
failure of the approved source bundle; it does not claim that no free data
could ever exist anywhere. Monid discovery offered paid stock-history and
transaction products; no paid endpoint, subscription or new key was used.

## Capital and operational feasibility

For standard 100-share contracts, let the contemporaneous call/put asks be
`aC` and `aP`. Before tick rounding, the higher-cost opening debit is
`100 * (aC + aP + 0.04)`. Hence the initial $49 cap requires
`aC + aP <= 0.45` **before** fee reserves and tick rounding. Those requirements
reduce the allowance further. The implementation also applies the 35%-of-equity
cap and separately limits it to settled cash. This is necessary arithmetic,
not a pricing model, affordability screen or empirical event count. That count
is **null**, not zero. No farther-out-of-money strike or next ticker is tried.

The [September 17, 2026 fee schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf)
was preserved and pages 3–4 rendered and visually checked. Rates and daily
account-level rounding are transcribed in the source review. Its isolated
two-contract opening example costs $0.09 before exits or additional charges;
it is not a complete fee reserve. Exercise/assignment charges and a full
shared-account model remain unadmitted rather than being assumed zero.

[Tick guidance](https://alpaca.markets/support/options-pricing-increments-and-options-order-handling)
distinguishes ordinary and penny-program increments and special routing.
The [catalog's current `ppind`](https://docs.alpaca.markets/us/reference/get-options-contracts)
does not prove its value at each historical entry. Blanket penny rounding
would therefore violate the frozen execution rule.

The existing paper account returned ACTIVE/USD, approved/trading level **3**,
and false account/trading/user-suspension flags. That supports present paper
permission for level-2 long calls/puts under the
[Trading API rules](https://docs.alpaca.markets/us/docs/options-trading).
It does not certify live permission, settled strategy cash or historical
eligibility. No account capability was changed and no live account was queried.

[Individual-account DNE guidance](https://alpaca.markets/support/what-is-a-do-not-exercise-dne-and-how-can-i-place-a-dne-on-my-options-position)
requires a support email before 15:00 ET on expiry day. The
[Broker API partner DNE endpoint](https://docs.alpaca.markets/us/docs/options-trading-overview)
is not evidence that this Trading API account can call it. No email or exercise
request was sent. The original planned exit at least two sessions before expiry
remains mandatory; a failed exit cannot be treated as a guaranteed DNE.
[Automatic-exercise guidance](https://alpaca.markets/support/what-is-automatic-exercise)
also leaves the customer exposed when the broker cannot close an unfundable
long call. No broker sell-out or stock financing is assumed.

After the execution gate failed, this task did not complete the historical
earnings announcement/revision denominator, underlying price/action inventory,
causal OCC notices/Amendment 21 exits, per-series ticks, completed-cash settlement
model or exercise-failure implementation. A current contract's T+1 field does
not establish spendable cash completion for every historical lifecycle.
These prerequisites still apply if new source evidence permits reconsideration.

## Promotion decision and what could blow up this account?

**Edge/evidence:** the earnings-uncertainty hypothesis and fixed rule are
documented; published-result and fixed-survivor selection remain disclosed.
Profit after costs, trade count, p-value, marked drawdown, regimes, benchmarks
and live fidelity are **not established**. Their result fields remain null.
No AI-decided 7-day/30-trade replacement applies to this deterministic rule.
Forward or synthetic plumbing would not satisfy its historical proof rule.

**Tail/gap:** both premiums can vanish after an earnings release. A partial
pair carries direction; an unclosed call can create an unaffordable share
obligation, while a put can require shares the account lacks. Repeated losses
or operational failures can cross the strategy kill/global daily halt before
an exit is possible. The opening cap is not a guaranteed realized-loss limit.

**Adverse selection:** spreads, thin sizes, asynchronous legs and volatility
collapse can dominate the hypothesis. Indicative quotes, touching prints and
midpoints cannot prove fills. Missing exits remain failed runs with exposure.
Prediction-market maker guards are not a substitute for this option contract.

**Venue/operations:** the same Alpaca account, Mac and network are common
failure points. Broker liquidation and support DNE are not guaranteed automated
controls. The accepted no-dead-man/startup-reconciliation risks remain unchanged.
Existing keys stay in `.env`; no account, key, funds or subscription is added.

**Inputs/reproducibility:** external pages are evidence, never instructions.
Raw and manifest hashes, capture-code snapshots and audit dependencies bind the
decision. The public account receipt excludes identifiers, balances and secrets.
No theoretical quotes, retrospective event timing or current option metadata
are admitted as historical execution. The source audit can be repeated locally;
that does not authorize a historical final replay.

**Correlation:** earnings/volatility exposure can lose alongside the equity
families, and venue failures are shared. A $140 virtual allocation is not new
funding and cannot be stacked on the existing paper cash book. The unchanged
PRD6 limits retain veto power; this task does not edit accepted PRD9 risks.

**Decision:** hold at idea, real allocation **$0**, no paper/live activation or
ready-for-live claim. Reviewer NavyLantern, 2026-10-01. The source attempt is
complete under the bead's explicit parked/source-failure route. Reconsider only
with materially new free historical BBO/listing evidence for the unchanged
scope, then complete all remaining prerequisites before any outcome.

## Verification and ledger receipt

All **15 C13 checks and 12 existing options-archive checks pass**. They cover
archive corruption/relabeling, frozen rules and cutoff, necessary-capital
bounds, and idempotent null-result recording without final consumption.
Implementation **`8bafa91`** recorded failed source **trial 5322**, strategy
**10083**, after the implementation was committed and pushed. All eight stored
performance metrics are null; C13 has one source trial and zero orders, fills
or finals, with strategy status idea and allocation $0.

The [stored-only ledger receipt](36-c13-ledger-verification.json) verifies
eleven protected prior trial rows, including all seven consumed historical
finals, SPY paper 3298 and recent C05/C08/C03 source failures. Venue rows and
risk-limit bytes are unchanged. All 22 recorded code/policy dependencies match
both the working files and the recorded commit. No strategy or final was rerun.

```sh
uv run python -m tradingbot.research.c13_source_audit
uv run pytest -q tests/research/test_c13_source_audit.py tests/data/test_alpaca_options.py
```

The audit command is local/read-only with respect to the ledger. Its explicit
`--record-ledger` switch only records this source failure, requiring committed
code/evidence and the designated local database; it never runs a strategy.
