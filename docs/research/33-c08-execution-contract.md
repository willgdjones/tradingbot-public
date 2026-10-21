# C08 durable forward execution contract

2026-10-01, NavyLantern; `tradingbot-5l3`. Written before activation, new
decisions or paper orders. This implements the
[readiness contract](26-c08-forward-readiness.md) under the unchanged
[historical evidence](22-c08-blackout.md) and Amendment 21.

The `InventoryScarcity` reactor remains byte-identical:
`599442d4d877d32c5a1a82edd0abcc1036cc2ff8b10f62ae00201dddd69f87cc`.
Training 3907, consumed final 3910 and preparation 4176 remain immutable.
Keep −5% scarcity, 95% target, $140 maximum slot, 5% reserve, $0.01 fee
reserve, 1e-9 quantity floor and the evaluated 10 bp comparison. No historical
replay, parameter tuning, additional luck filter or AI paper quota.

## Clock and durable decisions

Use an explicitly prepared finite official exchange calendar, bound to the
experiment. The opening submission window is **[regular open, open + 60
seconds)**. Decision and submission quotes must each be regular-session
observations, at or after that session's open, no later than observation,
and within the unchanged 30-second freshness limit. Obtain all held/pending
portfolio marks coherently before a new intent. Recheck window, cash, source
identity and fresh quote under the connector's reservation lock before POST.
A quote after the window cannot reconstruct an opening fill. Report this
first-minute execution approximation explicitly; it does not certify 10 bp.
Poll and cancel remaining known DAY quantities after the first minute; a cancel
acknowledgment does not release reservations until reconciled. Record any later
fill honestly as outside that first-minute observation. A complete pending
terminal exit may finish inside the window; partial/rejected/unknown exits hold.

Missed opening windows are recorded once. Never submit an off-window catch-up
order. At a later regular open the unchanged reactor may act on its retained
latest release/pending cash target, subject to all current gates. A missed,
partial, rejected, unknown or risk-vetoed mandatory exit creates an incident
and holds for explicit resolution. Do not extend an action's safe exit date.

Process a close observation once within **[regular close, close + 60 seconds)**.
Only notices observed and reviewed by the actual close may establish that
close's future blackout decision. A later review cannot backdate the decision.
A missed close needed for an action exit is an evidence failure. The close
callback submits no order. The final prepared session is a predeclared terminal
open for liquidation; residual shares or active/unknown orders prevent successful
completion and need explicit review.

Persist the reactor's latest release, Decimal pending target/reserve, attempted
tags, blackout decisions and forced-exit flag separately from execution receipts.
Persist each phase observation and intended order before crossing the network.
An interrupted claimed attempt is never re-run to infer whether POST happened.
Resume by polling only durable known connector intents; no account-wide startup
reconciliation. Unknown POST outcomes retain cash/share reservations. Do not
create a second strategy-specific virtual cash book or reset the existing one.

## Source and action evidence

Archive first-observed EIA page/CSV/PDF bytes, schema/units/definition checks,
notice review and actual validation time. A release is eligible at an opening
only when its availability precedes the scheduled open; a mid-window capture
waits until a later open. Availability uses the later of publication's next
New York midnight and actual validation/review. Later captures never erase the
earliest receipt. Observed current information can be causal even when original
first-release vintage is unverified; that limitation stays disclosed. Preserve
the original 14-day expiry and newest-observation rule.

Provide a bounded issuer-plus-exhausted-broker notice watch and explicit dated
review, binding raw hashes and observation/review times. A changed or unknown
notice is a hold for review, not automatic clearance from an empty vendor page.
Each watch is valid for at most 24 hours from capture start. Renewing a watch
requires a fresh byte-bound review; the report's 14-day lifetime is unchanged.
Validate action identity, symbol, announcement, ex/pay dates and session coverage.
Only advance notices can produce C08's own prior-close/pre-ex-open blackout.
Stay flat through payable, then permit the unchanged reactor and cash gate to
decide. Ordinary distributions require separate entitlement/payment accounting;
unknown share/cash events, late/conflicting notices and unmatched activities hold
admission. Model-only paper income and actual broker credits remain distinct.

## Shared cash, fees and risk

The existing Alpaca book is **one $140 virtual account**, shared with running
SPY trial 3298 and future C05. Preserve its funding, account identity, trial
parameters, orders and schedule. Derive fees across all account fills in a
deterministic order with the dated EquityFeeBook, rather than resetting daily
rounding per strategy. Keep omitted paper fees separate from broker-reported
fees; do not double count them. Report account-wide and strategy allocation
cash, reservations, unsettled sales, receivables and realized/marked P&L.

C08 sale cash releases at the first regular open strictly after documented
completion, never from a nominal settlement label or margin buying power.
Spending must fit both that conservative balance and the existing shared
connector, broker cash and remaining strategy balance after fees. Apply the
fresh target/cap at rounded adverse limits, including all pending exposures.
Model fees and entitled income must reach marked risk P&L consistently, using
the unchanged shared −40% kill/−$50 daily limits. No missing portfolio mark or
unmatched event can imply zero exposure or zero loss.

Coordinate generic connector/accounting changes with C05 `tradingbot-dk3`.
Any shared hook must retain the connector's existing reservation, idempotency,
unknown-POST and risk-veto behavior. Unchanged default consumers and the TOM
experiment need regression coverage; a partial integration cannot justify
activation of C08 or duplication of modeled cash.

## Completion and activation

Build and test the runner, durable state, source/action adapters, accounting
and reconciliation with synthetic and transactional fixtures before using
existing paper access. Record failed preparations and any separately prepared
experiment in the ledger. Activate only with complete current evidence and a
written promotion/account-risk decision. Actual future fractional fills,
achieved costs, cash credits and action/forced-exit evidence remain observations
to collect, never simulated receipts presented as real trading.

The accepted lack of dead-man/startup reconciliation, all PRD §6 limits and
trade-only/no-withdrawal policy remain unchanged. No new account, venue, key,
capital, paid service, live order or public communication is introduced.
