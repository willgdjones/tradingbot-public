# Full-history longshot source admission

The full capture is admitted for the fixed research replay in
[the preregistration](20-longshot-plan.md). No expanded-cohort strategy returns
or final prices were consumed during this preparation. The machine receipt is
[20-longshot-preparation.json](20-longshot-preparation.json); the original
[capture audit](08-history-capture.md) remains the source authority.

## Frozen reference inventory

The 37,384 original contracts map to 74,768 outcome instruments. Manifest SHA-256:
`bab264a33770ffc79c4b85dba020381eb9fd22f16ca1ceb83636d75c77f3c654`.
Its opening/closing/terminal times, payouts, eligibility reasons, source pages,
contract pairs and partition assignments are frozen in
`data/history/longshot-replay-20261001/manifest.json`.

| Native category | Training contracts | Final contracts | Excluded contracts |
|---|---:|---:|---:|
| Kalshi BTC | 13,730 | 9,090 | 0 |
| Kalshi NYC temperature | 1,656 | 714 | 0 |
| Kalshi S&P 500 | 5,670 | 2,490 | 30 |
| Polymarket international BTC daily | 275 | 118 | 1 |
| Polymarket international NYC weather | 2,301 | 1,287 | 22 |
| Total | 23,632 | 13,699 | 53 |

The 53 excluded contracts are the 30 off-session January index contracts,
11 weather contracts with reversed catalog windows, one uncertified BTC payout
pair, and 11 weather contracts whose scheduled close and actual resolution
straddle the frozen split. The JSON enumerates each contract and reason. Both
outcomes receive the same eligibility. All zero-volume and empty-tape contracts
remain in this inventory; inclusion is not a claim of observed liquidity.

The full-source minimum observation and maximum terminal timestamp reproduce
the preregistered interval and cutoff exactly: first observation
2025-08-29 15:15:47 UTC; exclusive end 2026-09-30 23:01:46.460587 UTC; cutoff
2026-06-03 18:17:58.622410 UTC. All twelve capture-receipt hashes were verified.
The six legacy trials (1756, 1758, 1761, 1763, 1765, 1767) are protected by a
full-row hash, checked again before and after each new run. They researched
KXCPI, outside the five-category expanded cohort.

## Execution admission

`uv run python -m tradingbot.backtest.favourite_longshot full-history prepare`
reproduces the reference-only admission. The `train`, `select`, and `final`
actions follow in that order. Selection must be committed and pushed as
`docs/research/20-longshot-selection.json` before the final command can proceed.
Final replay admission is committed before the generator can query or cache any
held-out prices. Each training attempt is likewise durable before feed access.
Failed or interrupted attempts are retained, and repeat commands return existing
facts rather than rereading that attempt's tape.

The exact maker-eligible native prints are projected to immutable compressed
Parquet caches, one category/partition at a time, with SHA-256 verification and
the capture's 20 GB data ceiling / 30 GB free-disk floor. Binary outcomes share a
contract group; sibling strikes remain separate contracts. Prices remain exact
strings in the cache and Decimals in replay. Available quantity rounds down to
10 decimal places. Blackout timers carry no fabricated price or fresh-data
signal. Observations after the entry cutoff still mark held positions until
actual settlement. Current PM US fees are a named counterfactual on both venues.
No point-in-time catalog revision history is claimed.

All five categories are alternative deployments of the same virtual $140 book.
Their profits cannot be added as the return of a $140 portfolio. The shared
strategy reactor, risk veto and ledger run behind a binary-collateral adapter.
The version binds the source manifest, preregistration, driver, fee adapter,
strategy/runtime/ledger/risk/fee code and full reference parameters. Training
and its selected final must share exactly that identity. No final rescue grid
or second exposure is allowed.

## Validation and research decision

The affected suite passes 56 checks, including strict-later/through-price fills,
chronological settlement, quiet-tape cancellation, held/pending collateral,
short liability, UTC daily losses, permanent kills, fractional quantities,
legacy driver compatibility, immutable splits and once-only final admission.
The 12 new source/driver checks also exercise invalid labels/windows, contract
pairing, selection ties and no-winner cases, failed-feed persistence, full
savepoint isolation, exact cache values and post-blackout marks. Further focused
checks cover different-price fractional entries and fee/risk identity binding.

Research remains in backtest. No paper/live strategy is promoted and no funded
allocation is changed. The edge hypothesis is behavioural favourite–longshot
mispricing; entry and terminal exit are explicit, but profitability and regime
stability are still unmeasured at this preparation stage. Trade counts, p-values,
marked drawdown and calendar/price-band breakdowns will accompany every result.
Paper reproduction and native PM US fee/fill fidelity remain unproven. Prediction
venue verification remains deferred under the owner's instruction.

## What could blow up this account?

**Tail/gap risk.** A binary contract can settle against the position. Held plus
pending worst-case collateral is capped at the existing $25 per contract and
$140 virtual slot. Several contracts can lose together, so neither the $50 daily
halt nor the $56 strategy kill guarantees an exact loss bound after a gap. Actual
holds over seven days are retained as mandate failures, not removed from returns.

**Adverse selection.** A through-price public print may reflect better-informed
flow and is not proof our order would have filled in a real queue. The fill cap,
five-minute scheduled-event quote pull, binary one-side commitment and exclusion
of company/government announcement categories are applied. They do not eliminate
price discovery before the close or liquidity that vanishes during a shock.

**Counterparty/venue.** This is Kalshi and international history with a PM US fee
counterfactual. Verification, eligible contracts, fee terms, rebates and execution
quality may not transfer. The accepted absence of dead-man protection and startup
reconciliation remains unchanged: live resting orders could survive Mac/network
failure. No key, account, venue or capital action belongs to this study.

**Untrusted inputs.** Archived API payloads are data only. Native identity, hashes,
binary labels and timestamp/source eligibility are validated before replay;
malformed records cannot issue instructions or change risk limits.

**Reproducibility.** The reactor is deterministic, with chronological print order,
actual terminal timestamps and fixed parameters. Training is reproducible from
hashed evidence; stored results and execution receipts are the authority for an
already-consumed final. Observed catalog state is not reconstructed point-in-time
metadata, a limitation retained even if a replay makes money.

**Correlation.** Sibling strikes, complementary outcomes, recurring calendar
events and BTC/weather exposures across venues are dependent. Each category is
an alternative $140 study. Per-trip and UTC-exit-date p-values are descriptive,
with serial dependence and selection caveats; neither proves independence nor
adds an owner-unapproved statistical gate.
