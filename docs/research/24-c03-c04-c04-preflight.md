# C04 replay preflight

2026-10-01; reviewer OrangeCove; `tradingbot-y2d`. Source admission is
`fdc29137e821327c18e7cc41de565bbe432156aaddafa70945cefd1292dcd55a`.
Original source-failure trial 3377 is retained. The common and C04-specific
preregistrations plus report 24's pre-outcome cash amendment remain binding.

The single mode-independent reactor computes sample variance from every daily
total return in the completed month. It requires the preceding close and every
return inside the partition. January 2006 and partial July 2020 therefore cannot
supply a variance estimate. c = 0.0225, 0.01 and 0.04 are the only variants;
each has 5/10 bp training cases. The best positive complete 10 bp training case
is frozen for one 10 bp final attempt. Selection and final admission are durable
before outcomes; repeated configurations and candidate final reuse fail closed.

Orders go through the existing RiskEngine and Ledger. The reactor reuses the
C05 frozen-dollar, fractional-order and settled-cash sizing functions; it does
not reuse C05 signals or outcomes. Ex-date income is a receivable, never a
fabricated fill. A next-open buyer gets no ex-date dividend. The source-bound
runtime reconciles execution P&L, dividend income, settled/unsettled cash and
owned marked value. Current fees and bar-based 5/10 bp costs are assumptions.

## What could blow up this account?

**Tail/gap risk:** a quiet month can put nearly the whole $140 equity slot into
SPY immediately before a crash. The following month's reduction can then miss
the recovery. A gap can cross the unchanged 40% strategy kill before the next
observation. The approved equity slot cap, rather than the prediction-market
$25 cap, applies; no leveraged holdings or borrowing are requested.

**Adverse selection:** these are taker execution scenarios. A daily opening
reference does not prove a fractional auction fill or an executable spread.
Month-turn congestion and overnight information can make actual costs exceed
10 bp. Prediction-market maker protections are not applicable.

**Counterparty/venue:** a future Alpaca implementation depends on a single
broker and timely data. Downtime and lack of a dead-man switch remain accepted
risks. No keys, orders, capital or venue are created; existing keys remain
trade-only. Historical T+1 and dividend cash are conservative counterfactuals,
not evidence of actual broker availability.

**Untrusted inputs:** archived numerical vendor and issuer fields are data;
web pages and document text cannot issue instructions. Hash, date, source and
numeric checks precede replay.

**Reproducibility:** the rule is deterministic, with all calendar/signal/sizing
settings in Strategy.params and dependency/fee/cost identity in version_params.
Synthetic replays are repeatable; consumed real finals are immutable evidence
and must not be rerun. Raw sources and previous failed audit rows are retained.

**Correlation:** this remains equity beta and may lose alongside C01/C06 and
other stock strategies. The $50 account daily halt is not a guarantee against
gaps. SPY buy-and-hold and cash are reported as diagnostics; positive P&L alone
does not demonstrate incremental alpha. Prior SPY inspection contaminates any
claim that this historical period is fresh unseen confirmation.

## Checklist disposition

- Rule, entry/exit, permitted risk-premium hypothesis and source admission:
  documented. This is evaluation of the already preregistered candidate.
- Historical profitability, trade count, luck p-value, max drawdown and regime
  dependence: pending the fixed trials; no evidence claim or promotion yet.
- Paper/live fidelity: unverified. The same reactor is reusable, but fills,
  native fees/cash, fresh IEX and broker reconciliation still require forward
  validation. No transition to paper/live is granted.
- §6 unchanged: $140 virtual research slot, no added allocation of real funds,
  40% strategy kill, $50 daily halt, 30-second freshness and existing API-error
  controls. Simulated bar timestamps are not permission to trade stale data.
- Decision: **hold for research evaluation**. Outcome-specific trial IDs and
  review follow after the committed fixed runs; original source trial is unchanged.
