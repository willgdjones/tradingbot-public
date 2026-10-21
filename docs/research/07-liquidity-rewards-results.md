# Liquidity-rewards implementation and readiness result

Decision on 2026-09-30: **hold; no promotion**. Strategy #2's core is implemented,
but the historical evidence required by PRD §4 is unavailable. Bead
`tradingbot-8r4` remains deferred, dependent on `tradingbot-e3t` (dated period/full
book capture), which depends on `tradingbot-31w` (existing account authentication
and trading-only key verification).

Trial **1811** records the preregistered baseline as **failed data readiness** on
code `e41b96b9d6096d44998a267770d59db3691b1b48`. It is not a losing backtest: no
returns were calculated. P&L after fees, trade count, drawdown, regime breakdown
and luck odds are unknown, not zero. No allocations, promotions, actual orders or
reward-income credits were made. See the [plan](07-liquidity-rewards-plan.md) and
[discovery snapshot](07-liquidity-rewards-discovery.json).

The public snapshot identifies non-sports candidates and an example executable
book. It cannot establish an authenticated eligible period, payout scope, the
historical sequence of competing depth, our own historical queue/exposure, or
confirmed payments. Extrapolating one snapshot into a historical reward return
would manufacture evidence. The next data task must preserve when each input
became known and retain real trade prints for strict trade-through fills.

Validation: **36 focused tests pass**, including the actual Postgres/PaperEngine
path and no residual test rows. The final repository suite passes **476 tests**,
with five optional database-loader tests skipped and one existing SDK
`websockets.legacy` deprecation warning. Tests use rollback transactions and send
no venue orders. PRD §6 values and §9 accepted risks are unchanged.

## What could lose money before a future promotion

A scheduled announcement or informed counterparty can fill a stale quote before
cancellation arrives. A complete event/insider review, exact execution receipt
counts and timer callbacks are required; the strategy's requested one-fill guard
is not a venue-enforced cap on cancellation races. The $15 inventory rule bounds
requested signed exposure and the runtime retains the absolute $25 market veto.

Rewards can disappear when competing depth changes, a cutoff moves ahead of our
order, a second fails the depth-adjusted spread test, a period changes, or the
confirmed payout falls below the minimum. Fee rebates and estimated score shares
must not be confused with paid incentives. Returns must be checked without
optimistic reward assumptions and across market regimes before any promotion.

The accepted Mac/connection risk remains: GTC orders stay live when the process
dies; there is no startup venue reconciliation or dead-man protection. The same
venue/data shock can affect several strategies at once. No code here changes the
owner's accepted risks, risk thresholds or permissions for funding/accounts/keys.
The future promotion decision still needs the full promotion checklist.
