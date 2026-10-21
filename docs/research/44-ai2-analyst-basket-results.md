# AI-2 daily analyst basket — implementation and prospective evidence

2026-10-05; tradingbot-cvm; RusticElk. Plan:
[44-ai2-analyst-basket-plan.md](44-ai2-analyst-basket-plan.md).

**Implementation validation; forward performance is pending.** This is a daily
20-stock Jev/Claude comparison. No historical model backtest or historical
holdout is used. The fixed observation window is October 6–23, with decisions
at open + 45 minutes and code-owned exits five minutes before the close.

**Current cohort:** Jev **8774**, Claude **8775**, virtual random **8776**, virtual
benchmark **8777**, under plan **Amendment 1** (snapshot validity on free IEX data),
admitted from `bae3637` (hwm repair). Admissions 6888–6891, 7508–7511, 7846–7849,
8373–8376, 8747–8750 and 8755–8758 are preserved as abandoned; see the transitions
below. **No AI-2 arm has
made a decision yet.**

## Implemented behavior

The pure `AnalystBasket` policy selects every validated probability >= 0.5 and
produces code-owned equal dollar targets. Both providers receive identical
numeric state-builder observations/questions, with raw headlines excluded.
Each daily turn retains the full source evidence, pre-answer random seed,
provider order/receipts, probabilities, selected stocks and execution outcomes.
Missing required data, stale quotes, insufficient paired settled cash, residual
exposure or a changed frozen identity consumes the turn without model calls.
A provider refusal leaves its arm flat. A durable claim prevents replay after
process failure; uncertain broker submissions retain their original identities.

The two real Alpaca paper arms have $35 ceilings. The matched-count random twin
and 20-stock equal-weight benchmark use isolated $35 virtual books. Actual
broker activities alone enter the real arms' fill ledger. The shared fee/risk
and T+1 cash machinery, original quote deadline, close exits, entry cancellation
and provider spend cap remain in force. Claude's adapter requires the existing
subscription and no tools; its list-price estimate is a separate sensitivity,
not an invoice or an extra subscription purchase.

The report records costs, fills/round trips, exposure, turnover, unknown marks,
marked max drawdown, benchmark-up/down regimes, weekly-cluster luck, Brier and
fixed-bin reliability, skipped/interrupted turns, entry outcomes and model
latency. The weekly review includes both arms and controls. Read-only status:
`uv run python -m tradingbot.forward.ai2_basket --status`.

At the fixed end date the code can mark an arm **eligible for review**, never
automatically live: >=7 observed calendar days, >=30 completed real round trips,
positive after-cost net strictly above the complete virtual benchmark, flat
holdings, no pending orders, complete costs/receipts, unchanged identity and no
risk halt. Random-twin results and calibration are descriptive. A virtual
comparator does not establish real execution parity.

## Verification and admission

**31 focused checks passed** (`tests/strategy/test_ai2_basket.py` and
`tests/forward/test_ai2_basket.py`). Rollback-only Postgres tests and fake
broker/provider transports cover equal targets and shared inputs, isolated
controls, actual-fill exits/calibration, durable daily claims/restarts, unknown
POSTs, entry cancellation, the existing five-error halt, stale/missing data,
insufficient settled cash, late/wrong/incomplete provider replies, admission
refusal, source drift with retained exits, unknown marks and final-review gates.
Python compilation, shell syntax and diff checks also pass. Admission and service
receipts follow the committed implementation.
Read-only preflight found all 20 equities already registered, initial shared
paper cash $140, unchanged $35 allocations and matching frozen identities for
J1 6343, J2 6166, J3 6162 and J4 6346. TOM 3298 remained running at $140. No new
capital, account, venue, credential or risk limit is needed.

Forward observations, model requests, fills, net P&L, trade count, drawdown,
regime performance, calibration and luck are **not yet measured**. Seven days
and 30 trades cannot be inferred from implementation tests. If cash contention,
latency, missing data or few selected longs leave too little evidence, this
version remains inconclusive at its fixed end; it is not silently extended.

**Original admission October 5 from `af1e8b0`:** Jev **6888**, Claude **6889**, virtual
random **6890**, virtual benchmark **6891**. All four frozen code/plan hashes
match; each had zero turns, broker orders/fills and model requests, no integrity
errors and `ready_for_live=false`. The $140 shared book and every J-arm identity
and allocation remained unchanged after admission. These were prospective
trials at admission, not successful performance results.

Service registration `b6969b1` starts a separate singleton runner in tmux
`services` pane `%115`. At 14:16 UTC it reported two real arms/two virtual
controls with the frozen October 6–23 dates. Re-running the launcher created no
duplicate; a second runner refused the advisory lock. Existing TOM, J-suite,
IEX, event-feed, scheduler and AI-1 pane/process identities were preserved.

Promotion-checklist decision: **paper research only**, two $35 ceilings on
existing settled paper cash, reviewer RusticElk, 2026-10-05. The plan's written
risk review and fixed entry/exit/cost rule are complete, implementation/source
preflight passed and §6 limits are unchanged. The owner-authorized prospective
AI exception replaces a historical model backtest. Trade count, profitability,
drawdown/regime breadth, luck and live-fill fidelity remain pending; no live
promotion, funding or credentials were introduced.

## Shared-provider repair before the first observation

At 14:32–14:39 UTC the daily session corrected Jev's two-decimal score/probability
validation and added safe exception-class diagnostics (`692a39a`). AI-2 uses
Noul questions, but its frozen dependency identity includes the whole provider
module. Consequently the original admissions correctly vetoed entries after
that edit. Restarting a daemon alone cannot repair a frozen experiment identity.

Before replacement, an exclusive AI-2 service lock and database checks proved
that all four originals had **no observations, turns, provider requests, orders,
fills, positions, virtual fills or used daily entries**. They were marked
`abandoned` with an explicit supersession note; original parameters, source
versions, git commits and complete metrics were preserved byte-for-byte.
No historical outcome was replayed and no performance record was reset.

Replacement trials **7508–7511** use the same plan hash, October 6–23 window,
20-stock policy, $35 ceilings and existing $140 shared cash book. All new code
identities match and all counts remain zero. **51 provider/policy checks passed**
after the repair, in addition to the original 31-check implementation run.
Only the AI-2 worker was stopped for its locked transition; its existing `%115`
launcher resumed with two real arms and two virtual controls at 14:42 UTC.
The shared repair owner and AI-1 owner are handling their respective J-suite
and AI-1 transitions; this operation did not rewrite their trials or holdings.

## Shared failure diagnostics before the first observation

`tradingbot-by1` added sanitized stage/raising-frame diagnostics to the shared
Jev runtime in `f641cb3`. This changed AI-2's dependency identity again before
its first scheduled day. At 15:29 UTC, an exclusive service lock and fresh
database checks confirmed that 7508–7511 had no observations, turns, requests,
orders, fills, holdings, virtual fills/attempts or consumed entries. They were
explicitly abandoned; every original trial field except status, completion
time and the explanatory note was verified unchanged after the transition.

New trials **7846–7849** have matching executable and plan hashes, zero activity
and no readiness claim. The October 6–23 window, twenty symbols, two $35 real
ceilings, two virtual controls and $140 shared initial cash are unchanged.
All existing paper allocations and other active trials' frozen parameters,
versions and commits were verified unchanged. **93 focused/regression checks
passed** for diagnostics, J-suite execution, AI-1, AI-2 and shared costs.
No observation or model call was replayed. J/AI-1 observed cohorts remain
preserved; their source-version transitions require their existing review.
The existing AI-2 launcher resumed with two real arms/two virtual controls at
15:31 UTC; a fresh stored-state audit confirmed all four identities match,
activity remains zero and integrity-error lists remain empty. The J daemon
also reports four running arms after its diagnostic reload. AI-1's existing
worker and the other service launchers were not restarted by this change.

## Request-size check and third pre-observation rollover — 2026-10-06 (`tradingbot-mna`)

The eoz diagnosis found that Jev's documented limit is **32k tokens for state plus
the longest question** (64k per request). AI-2 already strips headlines and
receipts. It was rebuilt from each of the 64 stored October 5 observations that
cover all 20 stocks, using its own question builder. The worst case was **19.9k
estimated tokens for state plus the longest question, and 28.5k for the whole
request**, both within the limits, so no AI-2 code change was made. An oversized
request would fail closed in `JevClient` with no call or charge.

The eoz commits `a051de4`/`78ff973`/`8c181be` changed hashed shared dependencies,
so 7846–7849 could never qualify. They had no turns, requests, orders, fills,
holdings or virtual activity. At **04:01:55 UTC**, together with the AI-1
transition, both workers were stopped under their singleton locks. Local and
broker checks found no open broker orders and no positions. A rolled-back dry
run, followed by one atomic commit, archived 7846–7849 (only status, completion
time and note changed) and admitted **8373–8376** through this runner's own
`prepare()`. That reuses strategy rows 15002–15005, whose allocations are
unchanged; only the rows' AI-2 trial pointer moved. The plan hash
`1a1cae1e…b895e385` is unchanged. All four new identities match committed
source, and the old records, $140 book, allocations, shared costs and other
trials' frozen versions are verified unchanged. The restarted worker reports two
real arms and two virtual controls with the next boundary at 10:15 ET today.
Receipts are in `data/forward/ai-rollover/20261006/attempt-040149-392734/`.

The first observation is still October 6. The account-wide 24 uncertain Jev
reservations (`tradingbot-gdc`) must resolve before any AI arm can be
cost-complete for qualification.


## October 6–7: no valid snapshot, and the fourth rollover — 2026-10-07 (`tradingbot-36r`)

Cohort 8373–8376 made no decision, order or provider call.

**October 6, turn 547: `error` (`ValueError`).**
- It was raised after the observation was stored, inside the budget read
  (`common_budget`). The turn records only the exception class.
- The most likely source is the shared-cost view (`account_costs`), which hits
  the concurrent-receipt race at the 10:15 overlap with J1–J4. That race is
  recorded in `tradingbot-hwm`.

**October 7, turn 649: skipped as `incomplete_or_stale_twenty_stock_snapshot`.**
- **Quote timestamps:** NFLX and NVDA quotes were stamped 21–26 ms after this
  host's clock. The jsa repair now waits for the clock, and AI-2 inherits that
  through `Runner`.
- **Incomplete intervals:** 10 stocks had no complete 15-minute interval,
  because IEX printed no trade in at least one minute.
- **The October 6 snapshot** had already failed the second check for 7 stocks.

**The validity rule needs all 20 stocks complete, and that has never happened.**
Across the four captured sessions (October 2, 5, 6 and 7), only 12–16 of the 20
stocks had all 15 minute bars for 10:00–10:15 ET. COST, LLY, UNH, JNJ, HD and MA
miss most often. As pre-registered, AI-2 cannot decide on free IEX data. That
needs an AI-2-only amendment before any decision; it is tracked separately.

**The rollover.**
- **Why:** `f29a2ec` changed `forward/jev_intraday.py`, which AI-2's identity
  hashes.
- **When:** at **21:46:03 UTC**, together with the AI-1 transition, under both
  singleton locks, after broker and local checks found no open orders and no
  positions.
- **What changed:** a rolled-back dry run, then one atomic commit, archived
  8373–8376, changing only status, completion time and note. Both turns and all
  other records are byte-identical.
- **New cohort:** **8747–8750** through `prepare()`, on the unchanged strategy
  rows 15002–15005. Only the AI-2 trial pointer moved.
- **Identities:** the plan hash `1a1cae1e…b895e385` is unchanged. The new
  per-arm identities are Jev `4b5bfd52…`, Claude `961d7427…`, random `29603115…`
  and benchmark `e081f337…`, all passing the runner's `identity_ok`.
- **Restart:** the restarted worker (PID 51071) reports two real arms and two
  virtual controls.
- **Receipts:** `data/forward/ai-rollover/20261007/attempt-214546-319617/`.
  `result.json` has SHA-256 `a419bfcc…`.

## Plan Amendment 1 and fifth rollover — 2026-10-07 (`tradingbot-jxa`)

**The change (`5c26c93`):**
- The daily snapshot still needs, for every one of the 20 stocks:
  - a state;
  - a fresh, valid IEX quote;
  - live event collection.
- A stock whose most-recent 15-minute interval has a bar-less IEX minute no
  longer skips the day. Its price features stay explicit nulls from the shared
  state builder, shown identically to both models with the quality flags.
- Nothing is backfilled. Each turn lists those stocks under
  `incomplete_latest_interval`.
- The change is in `forward/ai2_basket.py` only. `ai/state.py` and
  `jev_intraday.py` are untouched, so the J-suite and AI-1 identities did not
  move.
- **Tests:** the new regression test (7 sparse stocks with null features) fails
  on the old rule. 20 AI-2 tests and 72 AI-1/J/cost tests pass.
- **Plan record:** the amendment is appended to the plan, whose new SHA-256 is
  `19327dd639653bb61e3f063bccf8d3a3e052372ce81ca9c6dd1574e15bf06e4e`.

**Cost of the change.** Before this, AI-2 could not run at all. After it, on a
day like October 7, about half the stocks reach the models with no
stock-specific price features, only market and sector context. Both models and
the random twin face the same inputs, and the benchmark holds all 20, so the
comparison stays fair. On those days, though, it tests less stock-level
judgement. Report the `incomplete_latest_interval` counts beside every result.

**The rollover.**
- **Previous cohort:** 8747–8750, admitted at 21:46Z, had no decision, order,
  fill or provider call. Its only turn was the restarted worker's missed-window
  skip (743) for October 7's past boundary.
- **When:** at **21:55:40 UTC**, under the AI-2 singleton lock only.
- **Checks:** broker and local checks found no open orders and no positions.
- **What changed:** a rolled-back dry run, then one atomic commit, archived
  8747–8750, changing only status, completion time and note. AI-1 8743–8746 and
  every other trial are checked unchanged.
- **New cohort:** **8755–8758** through `prepare()`, on rows 15002–15005, with
  unchanged allocations.
- **Identities:** Jev `653de837…`, Claude `15a4a2cc…`, random `b14fa3c6…` and
  benchmark `f4d2493e…`.
- **Receipts:** `data/forward/ai-rollover/20261007b/attempt-215526-654086/`.
  `result.json` has SHA-256
  `8144060743f69b85361196af5d5de390801a0fc2b8c1ebb628673046dcb6eb20`.
- **Next decision:** the first is due October 8 at 10:15 ET.

**What can still block that decision:**
- the cost-view race at the 10:15 overlap (`tradingbot-hwm`);
- a stale or missing quote on any stock;
- settled cash.

## Cost-view race repair and sixth rollover — 2026-10-07 (`tradingbot-5ag`)

The `tradingbot-hwm` repair (`bae3637`) changed `forward/ai_paper_costs.py`: a Jev
receipt or fill that lands within the 1-second tolerance after the account
snapshot is now left out of that view, instead of raising. That race most likely
caused the October 6 error in turn 547. The repair also changed
`connectors/alpaca_paper.py`, which now waits out a quote stamped up to 1 second
ahead of the host clock.

8755–8758 had made no decision; its only turn was the missed-window skip (744).
At **22:38:50 UTC**, together with AI-1:
- **Checks:** broker and local checks found no open orders and no positions.
- **What changed:** a rolled-back dry run, then one atomic commit, archived it
  (status, completion time and note only).
- **New cohort:** **8774–8777** through `prepare()`, on unchanged rows
  15002–15005.
- **Identities:** Jev `8b0b7627…`, Claude `e276260b…`, random `5b921f57…`,
  benchmark `8245941f…`, all passing `identity_ok`.
- **Unchanged:** the Amendment 1 plan hash `19327dd6…`.
- **Receipts:** `data/forward/ai-rollover/20261007c/attempt-223842-999111/`
  (`result.json` SHA-256 `87028a94…`).
- **Next decision:** the first is October 8 at 10:15 ET.
