# Paper / PM US / rewards correctness review

Reviewed `e41b96b` and `ad2b446`, plus the shared risk/ledger paths they call.
Reviewer: NavyLantern, 2026-09-30. Work item: `tradingbot-b64`.

Three confirmed defects, all priority 1:

| Bead | Finding | Reproduced consequence |
|---|---|---|
| `tradingbot-1oh` | `RiskEngine.daily_pnl` filters unrealized holdings to positions opened today | Three $25 overnight positions lose $17 each today; the $50 global daily halt does not fire. Each separate $140 strategy remains above its 40% kill. Applies to paper and connector callers. |
| `tradingbot-27p` | `live_events` truncates each recorder channel before combining them | With batch size 1, an earlier cancellation quote is skipped after the next trade advances the global event watermark. Two contracts falsely fill at the old bid. |
| `tradingbot-vzf` | `PaperEngine.tick` never invokes the rewards strategy | Both resting quotes survive entry into a reviewed event's five-minute blackout while the engine is running and the feed is quiet. |

Repros: `tests/reviews/test_paper_pmus_review.py`. All writes use a rolled-back
Postgres transaction on the configured port 5433. `--runxfail --tb=short`
confirms each fails at the final behavioral assertion, not fixture setup.
At the original review all three defects were strict expected failures; repairs
remove the corresponding marker and retain the regression test.

The second defect concerns sequencing of real trade-through events, not touch
fills: the runtime can fill an order that should already have been canceled.
The third requires scheduled pre-event cancellation (PRD §5), not a dead-man
switch or cancellation on process exit. PRD §9's accepted risks remain intact.

PM US submission identity/reservations, uncertain POST handling, execution
deduplication, actual commission recording, fractional wire precision and
fill-before-callback behavior were inspected. No additional connector-specific
defect was confirmed in this review. Authentication remains a separate tracked
blocker; no PM US live order was submitted. This is a bounded code review, not
proof of production correctness.

Review complete. Follow-up `tradingbot-1oh` is repaired: daily P&L now uses cash
flows plus closing marked inventory minus UTC-start marked inventory. It counts
overnight losses and avoids counting prior-day changes again when holdings are
sold. It also handles partial exits, shorts/flips, unattributed fills, fees and
rebates, multipliers, past-day requests and non-UTC runtime clocks. Marks never
look beyond the event clock; absent feed history falls back to the last known
execution (or average cost for a position-only import), not an invented price.

The overnight repro is now a passing regression. Dedicated accounting/repro
suite: 13 passed. Affected risk, paper, forward, Alpaca/PM US connector and
rewards runtime suite: 188 passed, with the two remaining defects as expected
failures. Synthetic FX fixtures are isolated inside their rollback transactions
so real ECB reference rows from paper preparation cannot contaminate them.

At that accounting repair, `tradingbot-27p` and `tradingbot-vzf` remained filed. No §6 constant or cap-selection
logic was changed in this repair; the owner's subsequent asset-class cap change
is the coordinator's separate `tradingbot-h2i` task.

Follow-up `tradingbot-27p` now returns the earliest **global** batch from the
two recorder channels. Each bounded channel head, the merged prefix and its
payloads are read in one SQL statement/snapshot. Only returned/committed events
advance their channel cursors; a later trade cannot overtake an omitted earlier
quote. The existing trade-before-quote equal-time convention is unchanged.
The original cancellation/fill repro passes after consuming all three events,
and ten feed checks cover page sizes 1/3/500, backlogs in either channel, equal
timestamps, source/time/instrument filters and the single-statement read.

This preserves the recorder's existing ordered-writer contract: IDs within each
channel follow received time. Late commits behind a consumed ID remain excluded,
and the engine still refuses to rewind its observed-time state. No risk limit,
trade-through fill rule, dead-man choice or venue activation changes here.
`tradingbot-vzf` remains the scheduled-blackout follow-up.

Validation after the feed repair: 11 targeted checks passed; the affected paper,
review and rewards-runtime suite passed 59 tests with one expected failure for
the separately tracked blackout timer. No broker orders were sent.
