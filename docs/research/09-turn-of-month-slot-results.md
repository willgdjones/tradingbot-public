# #6 at the $140 slot: historical profit, no holdout calendar premium

2026-09-30 (America/Los_Angeles), OrangeCove, `tradingbot-gat`.

**Continue forward paper execution measurement; not ready-for-live.** The
frozen primary is profitable after modeled costs in both partitions, meeting
PRD §4's owner-selected historical criterion. The holdout does **not** show a
positive calendar premium over random ordinary SPY windows. Its profit is
concentrated in three entries below the prior 200-session trend. Neither
finding is hidden behind the positive aggregate. No timing or regime filter
was changed after seeing the holdout.

## Evidence and locked evaluation

The [preregistered plan](09-turn-of-month-slot-plan.md) fixed the rule, $140
settled-cash-aware entry budget, $0.01 entry fee reserve, 2 bp primary and
random-window comparison before new returns. The [frozen selection](09-turn-of-month-slot-selection.json)
was committed as `bfe724e` before either final evaluation. The 5/10 bp training
scenarios were not run on the holdout.

The free archived source contains 260 pages / 8,664 records, SHA-256
`83501d8e59ae95b128481d26228722f00514f26b4cdb388462edb70908e4f5a9`.
Full bounds: 2016-01-04 05:00 UTC through 2026-09-30 20:00:00.000001 UTC
(exclusive); locked cutoff: **2023-07-12 01:06 UTC**. Only wholly observed
calendar cycles enter each replay. The unfinished September 2026 cycle and
cross-boundary cycle are excluded.

The old $24.90 study had already inspected the whole historical sample. This is
chronological revalidation with newly enforced access, **not fresh unseen
evidence**. Revised bars, partial corporate-action references and assumed
execution prices remain limitations. No full-sample replay is substituted for
the locked results.

| Evaluation | Trial | Round trips | Net after fees | Fees | Max marked drawdown | One-sided t p-value |
|---|---:|---:|---:|---:|---:|---:|
| Training, primary 2 bp/side | 3277 | 90 | $63.483911 | $3.60 | $15.713869 | 0.0175 |
| Training, 5 bp/side | 3279 | 90 | $55.885888 | $3.60 | $15.9401 | See machine results |
| Training, 10 bp/side | 3280 | 90 | $43.158389 | $3.60 | $16.3111 | See machine results |
| **Single final holdout, 2 bp/side** | **3282** | **38** | **$11.409438** | **$1.52** | **$23.734629** | **0.2642** |

Training and holdout share strategy version
`b9cc835353e8dd7c004a8d172b301c63203cd2f574a08021756412b9e8bd64da`.
There is one final attempt for this version. The final's source commit is
`bfe724e`; subsequent work adds reporting and forward preparation, without
changing the evaluated strategy. Final win rate is 57.89%; 76 fills, zero order
rejections, zero risk halts and no ending position. $140 starting cash ends at
$151.409436424799136 before six-decimal ledger aggregation; the $0.0000015752
rounding difference is below the recorded tolerance. Gains above $140 remain
cash; losses shrink subsequent entries. These isolated partitions are not one
compounded portfolio.

The $23.73 drawdown is **16.95% of the allocation**, below the $56 strategy kill
but material for $11.41 net profit. Marks use daily closes and execution events;
they cannot bound intraday or overnight-gap losses. The p-value is a test against
zero mean under its assumptions, not a posterior probability that the edge is
real. It is displayed without adding a significance gate.

## Calendar timing versus equity drift

Trials **3278** (training) and **3281** (single final control) use the same
nonexecution diagnostic version
`9f143edaf9851d1e5fe2e544872b7893fd7230b079c760046226368178b32118`.
They place no orders and claim no ledger P&L. Each duration has 10,000 fixed-seed
random draws, one eligible ordinary window per matched TOM entry month. Both
compare dividend-adjusted close ratios with 2 bp per side and $0.04 round-trip
costs on independent $139.99 notionals.

| Partition / control duration | TOM mean net | Random mean net | TOM minus random | Random draws at least as good |
|---|---:|---:|---:|---:|
| Training / 5 intervals | 50.04 bp | 0.86 bp | +49.18 bp | 0.37% |
| Training / 6 intervals | 50.04 bp | 4.96 bp | +45.08 bp | 0.46% |
| **Holdout / 5 intervals** | **20.61 bp** | **35.50 bp** | **−14.89 bp** | **73.37%** |
| **Holdout / 6 intervals** | **20.61 bp** | **41.28 bp** | **−20.67 bp** | **81.53%** |

The six-interval control matches the actual TOM holding duration. Five intervals
satisfy the requested comparison. Positive training timing premium reverses in
the final period; ordinary SPY exposure explains at least the observed mean in
this comparison. The randomization assumes eligible dates are exchangeable;
serial dependence and different exposure dates limit causal interpretation.
Daily-close control returns and final-minute ledger trades measure different
execution assumptions and must not be added together.

## Regimes

Use only closes strictly before entry to classify the prior 200-session mean.
No rule selects trades from these labels.

| Entry regime | Training trades / net | Holdout trades / net |
|---|---:|---:|
| Above prior 200-session mean | 63 / +$22.950405 | 35 / **−$1.471575** |
| Below prior 200-session mean | 18 / +$29.747360 | 3 / **+$12.881011** |
| Fewer than 200 prior sessions | 9 / +$10.786145 | 0 |

Final net by exit year: 2023 (5 trades) +$6.458220; 2024 (12) −$5.851665;
2025 (12) −$2.319543; 2026 (9) +$13.122425. The control groups by entry year,
so its year counts differ at year boundaries. The regime robustness item is
**not established**: three below-trend trades account for more than total net
profit. The strategy remains in paper, consistent with the promotion checklist's
one-regime caution.

## Promotion and account-risk record

- Fixed rule: buy SPY in the last minute of the fourth-last session, sell owned
  shares in the last minute of the next month's third session. Same pure
  `TurnOfMonth` code in research and forward paper.
- Edge premise: calendar flows. Historical absolute profit passes; a calendar
  advantage does not survive this control. The owner's updated PRD allows
  broader risk-premium research; no stronger structural claim is made.
- Statistics, drawdown and regimes: recorded above and in the
  [machine-readable evidence](09-turn-of-month-slot-results.json), including
  hashes of all six artifacts. Every fixed variant has its own trial.
- Fidelity: **pending** future paper fills, fees and slippage. Live comparison is
  unavailable. Ready-for-live is not set by this historical result.
- Risk and allocation: current §6 constants unchanged; up to $140 simulated
  settled cash, shrinking after losses, with no deposits or cash-book reset.
  The owner-approved equity slot cap applies; the older checklist's generic
  $25 language describes prediction markets, not this ETF.
- Decision: continue **paper measurement**, reviewed 2026-09-30; new trial must
  explicitly supersede unused trial 2344 while preserving its original params.
  Existing paper account/keys only. No live keys, live order or public post.

### What could blow up this account?

**Tail and gaps:** fully paid SPY can lose the entire $140 position. Overnight
gaps can cross the $56 strategy kill or portfolio $50 daily halt before an
executable observation. Losses correlate across equity slots; the $140 study
is not a concurrent portfolio test. Historical max drawdown is not a bound.

**Execution and adverse selection:** marketable fractional limits face spread,
latency, partial fills and rejects near the close. IEX quotes and simulated
Alpaca fills differ from the historical bar proxy and live consolidated fills.
Missing an exit can extend exposure; the runner records the incident and does
not invent an off-schedule liquidation. Passive rewards/event guards do not
apply to this fixed taker ETF rule.

**Counterparty and operations:** Alpaca, IEX, calendars, FX and the Mac are
single dependencies. Accepted no-dead-man and no-startup-reconciliation risks
remain: orders can outlive the process. Only durable owned order IDs are polled.
The existing paper-only adapter has no live/withdrawal transport; permissions
are not changed. Current checked-out code continues to run under PRD §9.

**Inputs and reproducibility:** external data are values, never instructions.
The fixed source, code hashes, calendar, seed and trial identities are recorded;
final historical access remains consumed and is not rerun. Source revisions,
model assumptions and future broker randomness still limit reproducibility of
actual execution. No LLM or headline chooses positions.

**Fees and cash:** broker paper receipts omit regulatory fees; a separately
labelled current-cost scenario subtracts them from forward net and sizing.
Fees must be compared to real receipts before live readiness. Shared settled
cash and hard risk vetoes prevent intended orders from exceeding available
funds; the experiment cannot allocate the same cash independently to each
strategy.

## Forward follow-through

Prepare a distinct trial with training 3277 / final 3282 and the frozen strategy
version as evidence. Use the official calendar through 2027-10-05. The first
scheduled entry is 2026-10-27 15:59 New York, first exit 2026-11-04 15:59.
Retain decision quotes, limits, quantities, broker fill IDs, actual timestamps,
fees, rejected/missed attempts and daily marked drawdown. Assess sizing and
fill/slippage differences against the historical 2 bp scenario after a complete
cycle; future observations are required before any fidelity or live-readiness
claim. No historical rerun is needed for that comparison.

Prepared and activated **paper trial 3298** from commit `bde64ce`. Trial 2344
is marked abandoned/superseded with its original $24.90 parameters intact;
both had zero orders and fills at transition. The local trial pointer now
selects 3298. A one-step paper runner check passed outside the scheduled window,
and `com.tradingbot.alpaca-tom-paper` is loaded in the user's LaunchAgent domain.
Forward fidelity is tracked separately in **`tradingbot-78y`**, deferred until
after the first scheduled exit. This activation does not imply an observed
fill or successful future cycle.
