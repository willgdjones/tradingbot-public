# PM US liquidity-rewards research — 2026-09-30

Bead `tradingbot-8r4`. Structural hypothesis: eligible maker rewards plus spread
capture exceed fees and adverse selection under the existing risk limits. No
strategy promotion, capital, venue, key or order is authorized by this document.

The deterministic candidate ranks reviewed markets daily by the eligible period's
pool divided by competing qualifying raw depth. It joins the BBO with maker
limits, uses a five-contract maximum clip, and caps signed binary inventory at
$15 of payout-risk capital. A long uses ask-valued inventory; a short uses
`1 - bid`. At the cap it quotes only toward flat and cannot cross through flat.
The runtime's unchanged $25 market cap and all other §6 vetoes remain final.

Adverse-selection guards are mandatory inputs: explicit non-sports/insider review,
a reviewed event calendar covering the period, a five-minute pre-event blackout,
and one actual fill per rolling 60 seconds per market. Missing execution receipts
or position/receipt disagreement stop quoting. Cancellation must be acknowledged
before replacement; pending and canceling orders count as resting. Full book data
is required to evaluate the aggregate Target Size and Max Spread rules. A BBO or
sampled historical price is insufficient to infer qualifying reward seconds.

One baseline variant is preregistered: join best (`offset_ticks=0`), five-contract
clip, $15 cap, one fill / 60 seconds, 300-second blackout. No parameter search has
been performed. Variants and failed evidence checks go into the trials ledger.
A profitable fee-only historical backtest and credible reward evidence are needed
before any promotion; complete `docs/promotion-checklist.md` at that time.

## Current evidence

The public [rewards page](https://polymarket.us/rewards) snapshot fetched at
2026-10-01 approximately 02:16 UTC contains 139 program groups: 118 sports and
21 non-sports, with 76,220 program-symbol occurrences. Sports are excluded. The
non-sports rows include crypto, climate, macro, politics, culture, technology and
science; many are nevertheless exposed to private company/government information
and remain excluded unless specifically reviewed. These are discovery groups,
not an authenticated active-period/account-eligibility response.

HTML SHA-256: `ab32e3aa2bced226f8f18b8b84659d4afa736617f6da7c9aefcd7dea013b06b1`.
Do not multiply a template's displayed pool by its symbol count or book estimated
incentives as revenue. Confirm the market-period scope and dates using the
[Incentives API](https://docs.polymarket.us/api-reference/incentives/overview).
Current configured authentication returns 401 (deferred bead `tradingbot-31w`).

The [scoring rules](https://docs.polymarket.us/incentives/liquidity) require a
random book snapshot each second. Raw size determines the complete eligible
price-level range; within it, distance in ticks discounts size. Optional Max
Spread compares the two target-depth prices, not the BBO. Missing qualifying
seconds are forfeited. A score fraction is an estimate, not a payout; the minimum
payout and confirmed account credit must be handled separately.

The existing recorder retains top-of-book observations, not complete depth, and
there is no historical sequence of dated incentive terms plus full qualifying
books. A current public snapshot cannot prove historical returns. Initial work
therefore implements and tests the rule, ranking and evidence contract, and
records the historical-data readiness failure rather than inventing returns.

## Implementation and runtime contract

`tradingbot.strategy.liquidity_rewards.LiquidityRewards` is the one strategy
class in backtest, paper and live. `Terms`, `side_depth` and `qualifying_book`
implement exact-decimal eligibility/scoring inputs; `score_share` gives only an
instantaneous **per-side fraction**, never a USD reward estimate or credit. It
recomputes the cutoff when adding hypothetical own size. To evaluate a complete
hypothetical two-sided book, add both orders and rerun `qualifying_book`, including
Max Spread, before interpreting any fractions.

`tradingbot.research.liquidity_rewards.rank_markets` consumes dated, reviewed
market-period terms and fresh complete books. It excludes unknown pool scope,
sports/unreviewed insider exposure, stale/future data and books failing the
initial two-sided qualification. It selects the highest pool/depth period per
market and uses stable tie-breaking. Save each daily ranking with its input
snapshot, then include that day's `ranked_at`, `selected` and terms in the
strategy's recorded parameters. Daily validity uses Eastern Time; yesterday's
ranking cannot silently keep quoting today.

`WithFillReceipts(inner_strategy, session, strategy_id=...)` is the runtime
adapter around the pure strategy. Pass it as the strategy to the existing
Backtester or PaperEngine. It reads that strategy/mode's ledger fills before
reacting and passes exact identifiers, signed size and timestamp. Recent fill
history also survives a new flat start; restored running state must retain its
receipt cursor, seen IDs, positions, quote generations and rolling window.
Keep one active runtime per strategy/mode book. No shared StrategyContext, ledger,
paper engine or risk-limit file was modified.

Every input quote used for quoting must include `event.meta.full_book` with
`state: open`, `observed_at`, and complete `bids`/`asks` lists of `[price, size]`
strings. `book_from_response` converts the documented public `/book` response.
The current BBO recorder alone cannot supply this contract. Historical input must
preserve when each book/period became known; do not attach today's depth or terms
to old prices. Never pass sampled prices as fill-eligible trades.

The active runtime must invoke the strategy promptly after an actual fill and
on clock callbacks before scheduled events, including when no price update
arrives. The adapter is a ledger reader, not a live loop installer. The live
connector records executions; a future live Strategy driver must connect those
notifications and explicit timers to the same reactor. Asynchronous pending and
canceling orders remain in `resting_tags` until acknowledged. Cancellation races
can produce additional venue fills before acknowledgment; record them and retain
the guard rather than claiming the requested count is a venue-enforced limit.
A process exit still leaves GTC orders unmanaged, as deliberately accepted in
PRD §9. No watchdog, automatic restart reconciliation or expiry was introduced.

Tests cover full-level target walks, independent sides, Max Spread equality and
units, hypothetical score fractions, all three mode labels, exact fill receipts
(including offsetting and duplicate fills), rolling history, daily rank validity,
future/stale evidence, reviewed event blackouts, cap-constrained reducing orders,
cancel acknowledgment sequencing, public JSON decoding, trial idempotency and
real Postgres/PaperEngine trade-through integration. The failed readiness trial
will keep returns, drawdown, regime results and luck odds unknown until a real
historical dataset supports them.
