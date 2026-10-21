# AI-1 daily gate — implementation and forward evidence

2026-10-05, `tradingbot-efn` / `tradingbot-3l9` / `tradingbot-mna` / `tradingbot-36r`.
**Current Alpaca paper cohort: 8770–8773, under plan Amendment 1 (model-input scope
and deadline), from the hwm shared-source repair. Earlier cohorts are preserved as
abandoned after explicit source-version transitions:**
- **6748–6751:** the original observed cohort.
- **7857–7860:** unobserved.
- **8369–8372:** observed on October 6–7.
- **8743–8746:** no decision.
Prospective qualification remains pending. This is not a profitable-strategy
result or a live promotion.

The [plan](48-ai1-gate-plan.md) was first frozen in `f033032` before any AI-1
model decision or broker order. Execution-window cancellation and strict matched
share-quantity qualification were clarified before admission and before outcomes.

## Implementation

`strategy/ai1_gate.py` supplies deterministic first-hour relative-strength
signals and the fixed p >= 0.55 gate. `forward/ai1_gate.py` subclasses the
J-suite runner for the daily cohort, reusing its actual paper execution,
settled-cash checks, full-account risk/cost overlay, point-in-time state builder,
continuous management and code-owned close exits. Its separate code version
and service cannot be discovered as J1–J4 arms.

The real ungated, Jev and Claude variants have equal $15 paper ceilings. Their
informational random control has a separate virtual book. One daily claim,
immutable common inputs, pre-call RNG seed, bounded concurrent providers,
receipts before orders and fixed quote deadlines prevent duplicate/catch-up
decisions. Jev uses only its existing capped wrapper. Headless Claude uses the
existing subscription with typed output, no tools, no project context and no API
credentials. Failed calls and selected execution gaps remain visible.

Both daily experiments now have continuing performance/calibration tables in
the weekly report. AI-1's Brier requirement applies only to AI-1; AI-2's existing
calibration remains diagnostic. Unknown Claude list-price estimates remain
unknown, with no invented zero-cost sensitivity.

## Validation

**107 distinct checks passed** across the new provider/policy/cohort/weekly tests
and the existing J-suite runner, state and shared cost tests. Meaningful cases:

- Three equal real tickets versus a separate virtual control; only actual broker
  activities create ledger fills; no duplicate day or uncertain-POST retry.
- Provider-specific outages, malformed probabilities, fixed deadline expiry,
  paired cash refusal, risk halts and missing entry windows.
- Known entry cancellation, model-independent close exits, actual round trips,
  rejected-forecast labels, Jev outcome synchronization, fees/provider charges,
  unknown cost estimates and failed matched-execution qualification.
- Environment isolation, existing subscription requirement, exact model receipt,
  typed schemas, no tools/MCP, bounded timeout and no model fallback.
- Weekly real/virtual distinctions, control nonqualification, HTML escaping and
  explicit missing calibration/cost evidence.

The PostgreSQL tests used outer rollback transactions, fake broker/model calls
and isolated venue state. They created no lasting synthetic trials or orders.
Shell syntax and whitespace checks also passed. The dependency deprecation
warning from `websockets.legacy` is unchanged.

A separate harmless **fair-coin adapter contract check**, not a trading signal,
returned p = 0.5 from `claude-sonnet-5-5` in 3,579 ms, receipt
`cf4555c5-ad8d-4d07-b57e-189ad50b8c59`. CLI usage reported first-party access,
zero web searches and a **$0.005346 list-price estimate** (`costBasis=list`).
Primary accounting assumes included Max-subscription usage has zero incremental
cash cost; this is not a claim that the estimate is an actual invoice.

Read-only pre-admission checks found the existing Alpaca paper book at **$140
initial/$140 available**. All four deployed J-suite trials (6162, 6166, 6343,
6346) retained their **$35 allocations and matching frozen identities**.

## Forward status

Implementation commit **`62a3d53`** was pushed before admission. Admitted trials:

| Arm | Trial | Strategy | Real paper ceiling |
|---|---:|---:|---:|
| Ungated | 6748 | 14602 | $15 |
| Jev gate | 6749 | 14603 | $15 |
| Claude gate | 6750 | 14604 | $15 |
| Random control | 6751 | 14605 | $0 (separate $15 virtual book) |

All four share frozen executable version
`edc40ae878b6dce5a89cf06a3d04668b82485bffc2c48ea4519fff6667ad9c9c`
and plan SHA-256
`be79cf2c0b875a7e24068a2052961f9334cf43941b50923371fd000049935b44`.
Read-only post-admission checks matched both on every trial; the four J-suite
versions still match, and the shared initial cash remains $140.

The committed launcher initially hit a real tmux layout limit: its default
target had only one row. The startup fix selects the tallest existing pane and
logs success only after a successful split. AI-1 now runs in pane **`%114`**;
the five existing services kept the same pane IDs and process IDs. Logs show
`running`, `active_arms: 3` on recurring 15-second polls. A concurrent worker is
refused by the singleton database lock. Re-running the service launcher creates
no duplicate AI-1 pane.

At the pre-window deployment audit, all four trials are `running`, none is ready
for live, and there are **zero AI-1 turns, orders and fills** before the first
10:30 ET daily entry window. A zero balance change here is absence of trading,
not profitability evidence. Actual P&L, drawdown, per-regime performance, Brier
scores and luck statistics await prospective observations. The
7-calendar-day/30-real-trade minimum, 30 base signals
per five sessions, positive P&L beating ungated, and better-than-always-yes Brier
requirements remain pending. No live keys, actual capital or risk limits change.

## October 5 shared-provider change after observations

The shared Jev rounding repair **`692a39a`**, owned by the daily session, changed
AI-1's executable identity after its first decision. The original frozen records
must remain intact: turn **258** at 14:30 UTC had eight candidates; ungated trial
6748 has an actual fill and, at 14:49 UTC, still holds **0.0044775520 TSLA** at
$376.078. There were no active paper orders at that audit. Jev request
`283a59bf-3862-42cc-99b1-7140b24ad788` remains **uncertain**, with
**$0.002752512 reserved**, which must not be reset or treated as zero cost.
Claude rejected all eight candidates; its receipt
`60e44ff1-f485-41d8-9491-ad65a5a19620` retains the **$0.17868 list-price estimate**.

This cohort is already observed and cannot be replaced as unused. Source
identity checks block new entries and qualification. The restarted service
continues known-order/risk management and the code-owned close exit; recurring
14:52 UTC logs still report three active arms. No original trial identity,
parameters, turns, fills or provider records have been rewritten.

Follow-up **`tradingbot-3l9`** is deferred until after the October 5 close. It
requires a verified flat book and no active or unknown broker orders before
explicitly archiving the interrupted comparison and admitting a fresh cohort
under stable committed source. The new cohort must retain the old accounting
obligations without pooling the old observations into its qualification sample.
The $140 shared book and all other strategy allocations stay unchanged. The
existing first-day claim must never be replayed.

## Verified-close source rollover review — 2026-10-05 (`tradingbot-3l9`)

At 20:15 UTC, the bound Alpaca paper account reported no positions and no open
orders. Both known AI-1 orders match their local quantities and broker terminal
status: buy 916621 filled 0.004477552 TSLA at 14:30:44 UTC; exit 916923 filled the
same quantity at **19:55:15 UTC (15:55 ET)**. The local strategy position is zero,
and neither order has an unknown-submission flag. The official session ended
at 20:00 UTC. This is an explicit transition check, not a new startup-reconciliation
policy or an assumed close based on elapsed time.

The interrupted sample remains evidence: ungated has one completed round trip,
**−$0.020311 after $0.03 modeled fees**, with $0.036582 observed drawdown. Jev has
zero trades and **−$0.002752512** conservatively including its unresolved reserved
charge. Claude has zero trades/$0 primary net and the separate **$0.17868**
list-price sensitivity. The random control has no virtual fills. One round trip
cannot establish an edge, calibration or a meaningful luck probability. These
observations cannot be pooled into the next cohort.

Paper-review decision: archive the interrupted four trials as `abandoned`,
preserving every original field except status, completion timestamp and the
explicit transition note. Preserve all turns, fills, orders, provider records,
original strategy rows and allocations. Admit four fresh trial/strategy rows
using the unchanged plan and current committed execution identity, with the
same three $15 real ceilings and one independent $15 virtual control. New rows
start without trade history, observations or readiness; the active AI-1 real
ceiling remains $45 inside the existing $140 book. Archived strategy allocations
are historical records, not newly funded cash. All other allocations stay intact.

The original completed paper checklist and written **What could blow up this
account?** analysis remain applicable: correlated intraday longs, tiny-ticket
spread/fee costs, stale-feed/venue/Mac failure, model unavailability and shared
cash constraints. No entry, exit, model, threshold, risk limit, capital, key or
venue changes. Seven days/30 trades, positive matched P&L, calibration and regime
coverage remain unproved. Unknown provider charges continue reducing account
cash and blocking cost-complete qualification; a new trial does not erase them.
There is no live promotion and no replay of October 5's daily signal.

The transition will run under the exclusive AI-1 service/admission locks, first
as a rolled-back transaction and then as one atomic commit after renewed broker
checks. Source/plan identity and old-record fingerprints must match throughout.
Only the AI-1 worker will be restarted; its existing launcher and every other
service remain in place. The next prospective decision is October 6 at 10:30 ET.

### Committed transition and service verification

The transition committed at **20:22:17 UTC** under the AI-1 singleton, original
leader and admission locks. The prior worker (99198) was stopped only after its
close execution; its existing `%114` launcher restarted worker **62855**. J,
AI-2 and C05 workers retained PIDs 56839, 58967 and 65742 respectively.
No executable or plan source was changed by this transition.

| Current arm | Trial | New strategy | Active real paper ceiling |
|---|---:|---:|---:|
| Ungated | 7857 | 18293 | $15 |
| Jev | 7858 | 18294 | $15 |
| Claude | 7859 | 18295 | $15 |
| Random control | 7860 | 18296 | $0 (separate $15 virtual book) |

All four bind to executable identity
`403463c0b8df7ded2f4f8ebba623d57edf16f9cc9bbdf15304df3583baeb6061`,
unchanged plan hash
`be79cf2c0b875a7e24068a2052961f9334cf43941b50923371fd000049935b44`,
and reviewed admission commit `dd422d0`. The original source versions, complete
metrics, turns, orders, fills, provider records, original strategy rows and
allocations matched their saved fingerprints after the dry-run rollback,
atomic commit and restarted-service audit. Only the three explicitly reviewed
archive fields changed on the original trials. All other existing allocations
and frozen paper identities, the $140 initial cash book and account guard were
unchanged. Shared cost calculations still include the old $0.03 fee debit and
$0.002752512 uncertain Jev reserve, while the new trial-specific P&L/cost samples
contain neither.

Validation used a complete rolled-back admission transaction, renewed bound-
account broker checks, exact matching of both local fills to paginated broker
activities, preservation checks around the atomic commit, and a post-restart
singleton/state audit. At **20:24 UTC**, all four identities match, readiness is
false, and there are **zero new orders, fills, model requests and signal
observations**. `started_at` and `last_observed_at` remain unset. The unchanged
runner recorded one zero-candidate `missed_snapshot_or_entry_window` row (537)
for the replacement leader's already elapsed October 5 window; this is an
explicit skip, with no replayed signal, label, provider call or trade. Original
turn 258 is unchanged. First prospective entry remains October 6 at 10:30 ET.

Receipts and the exact transition script are archived beneath
`data/forward/ai1-rollover/20261005/`. The committed result is
`attempt-202129-482558/result.json`, SHA-256
`b16f927a58e8135b172eccbf59460e3004db7f9a9382b259aaea018b87c17944`;
post-restart `health.json` SHA-256 is
`c51f624b392182c38f365c7290cce9f37f0f6e86ae011768364fbf056f1b45d0`.
The attempted dry-run IDs were rolled back and never became a live cohort.
No historical test, model decision, capital movement or provider charge was
repeated, and no live qualification is claimed.

## Amendment 1 and unobserved-cohort rollover — 2026-10-06 (`tradingbot-mna`)

**The defect, from turn 258 (October 5).** Both providers received all 40
observations with headlines: about 50.5k estimated tokens. Jev's documented
limit is 32k for state plus the longest question, so Jev was refused and only
Claude answered. The turn deadline came from the oldest of all 40 quotes, a
16-second-old LLY quote that was neither a candidate nor shown. That left
13.8 seconds, and six of eight ungated entries ended `expired_or_missing_evidence`;
META was `held`. Only the TSLA round trip completed.

**The fix (`28fb006`, plan Amendment 1 in `f820772`).** Both providers now receive
the identical observations of the day's candidates plus SPY, about 16.1k
estimated tokens on the same turn. The deadline is fixed once, from those
symbols' quotes and the feature cutoff, through the shared J-suite
`turn_deadline`. Each turn records its deadline, observation scope and token
estimate. A request over the limit still fails closed in `JevClient` with no call
or charge. A new regression test, with a stale non-candidate quote and maximum
headlines on all 40 symbols, fails on the old code. **124 AI-1/AI-2/J-suite/Jev
checks pass.**

**The transition.** Cohort 7857–7860 had no observation, order, fill or provider
request; its only row is the zero-candidate missed-window skip (537). Its
identity was moved by the committed eoz shared-source repairs and by this fix.
At **04:01:55 UTC** both AI workers were stopped and their singleton locks held.
Local and broker checks then found no open broker orders and no positions. A
rolled-back dry run, followed by one atomic commit, archived 7857–7860 (only
status, completion time and note changed) and admitted:

| Arm | Trial | Strategy | Real paper ceiling |
|---|---:|---:|---:|
| Ungated | 8369 | 18677 | $15 |
| Jev | 8370 | 18678 | $15 |
| Claude | 8371 | 18679 | $15 |
| Random control | 8372 | 18680 | $0 (separate $15 virtual book) |

All four bind to executable identity
`a929afe7abf446af7b7512e5433ab89664bb8572a9cd6e4edd09a7bde0e0cbde`,
the amended plan hash
`c95b55e2a414406d803f8f5d148372c1deb443bb81cba0f6afce78b67b39ead8`
and commit `8ea595f`. Preservation checks confirmed:
- old records, the $140 book, every allocation and other trials' frozen versions are unchanged;
- shared account costs are unchanged;
- the new trials start with no trades, observations or readiness.

The restarted worker reports three active arms, with matching identities and no
integrity errors. Receipts are under `data/forward/ai-rollover/20261006/attempt-040149-392734/`:
`result.json` has SHA-256
`9342daaa918a4a1b0d626c3ea2957210510a2247c910890707dce505399587e2`, and the
script hash `be8f7dca…` is recorded in `script.json`. Two earlier attempts stopped
on over-strict self-checks of AI-2's expected strategy-pointer update, and a
third ran only the dry run. All three rolled back with no change. The first
amended decision is October 6 at 10:30 ET.

**Still blocking qualification.** Readiness also needs cost-complete evidence,
and 24 uncertain Jev reservations from the October 5 HTTP 400s remain
unresolved account-wide (`tradingbot-gdc`). The 7-day/30-trade, matched P&L,
calibration and regime requirements are unchanged and unproved.


## Shared-runner repair and observed-cohort rollover — 2026-10-07 (`tradingbot-36r`)

**Cohort 8369–8372, October 6 and 7.** Both turns (551 and 653) completed, and the
Amendment 1 checks held on both days:
- 15.0k and 17.3k estimated tokens for state plus the longest question, both
  under Jev's 32k limit;
- Jev and Claude receipts `ok`;
- deadlines 28 and 23 seconds after observation;
- 9 symbols shown each day: the candidates plus SPY.

Real outcomes before model charges:
- **Ungated:** 6 round trips (12 fills), +$0.046.
- **Jev:** 1 round trip, +$0.018.
- **Claude:** no trade.
- **Virtual random control:** 2 round trips, −$0.025.

These are two sessions of anecdote, not evidence. CyanDeer's `tradingbot-jsa`
audit found that most selected real entries were lost to shared execution bugs:
- 4 limits were non-marketable because they were priced at the observation ask;
- 6 were refused by future-dated portfolio marks;
- 1 was refused by a future-stamped order quote.

**The repair (`f29a2ec`, `forward/jev_intraday.py` only).** It fixes four things:
- broker-UUID instrument resolution;
- limits priced at the guard's fresh ask;
- a wait of up to 1 second for this host's clock to reach a quote's timestamp;
- a re-read after a concurrent-receipt race.

No stale limit, future-quote check or threshold changed. The file is part of
this cohort's frozen identity, so 8369–8372 could make no further decisions.

**The transition.** At **21:46:03 UTC**, after the close, both AI workers were stopped
and their singleton locks held. The checks found:
- no open broker orders and no broker positions;
- the account fingerprint matching the book;
- every cohort order terminal (14 orders, 14 fills, all filled) and every
  position row at zero quantity;
- no Jev request in flight, and all four turns of both cohorts terminal.

A rolled-back dry run, then one atomic commit, archived 8369–8372, changing only
status, completion time and an appended note. Every turn, order, fill, position
row and provider receipt was checked byte-identical before and after.
Observations are not pooled. New cohort:

| Arm | Trial | Strategy | Real paper ceiling |
|---|---:|---:|---:|
| Ungated | 8743 | 18952 | $15 |
| Jev | 8744 | 18953 | $15 |
| Claude | 8745 | 18954 | $15 |
| Random control | 8746 | 18955 | $0 (separate $15 virtual book) |

**Binding and receipts.**
- **New cohort binds to:** identity
  `b255b733458ea5b875ee4f64d38db8cc84f49bbda94adc399fdcdcb6a356f726`, the
  unchanged Amendment 1 plan hash `c95b55e2…b39ead8`, and commit `367baab`, whose
  `src/` is identical to `f29a2ec`.
- **Preserved:** the $140 book, every allocation, other trials' frozen versions
  and shared account costs are unchanged.
- **Restart:** the restarted worker (PID 51070) reports three active arms bound
  to these trials.
- **Receipts:** `data/forward/ai-rollover/20261007/attempt-214546-319617/`.
  `result.json` has SHA-256
  `a419bfcca6d11f241c8be7c707c352a0d86c341c27693384f41490b82d4850ad`, and the
  script hash `01e2553b…` is recorded in `script.json`.
- **Timing:** CyanDeer's J1–J4 rollover finished before this one. The first
  decision of the new cohort is October 8 at 10:30 ET.

**Still open.** These are unchanged:
- the 24 uncertain Jev reservations (`tradingbot-gdc`);
- the residual clock-skew and receipt races in files shared with C05/C08
  (`tradingbot-hwm`), which can still refuse a turn at the 10:15/10:30 overlap;
- the 7-day/30-trade, matched-P&L, calibration and regime requirements.

## Shared cost-view and quote-clock repair rollover — 2026-10-07 (`tradingbot-5ag`)

NavyHill's `tradingbot-hwm` repair (`bae3637`) changed two shared files:
- `forward/ai_paper_costs.py`: a Jev receipt or fill that lands within the
  1-second tolerance after the account snapshot is now left out of that view,
  instead of raising.
- `connectors/alpaca_paper.py`: a quote stamped up to 1 second ahead of this
  host's clock is now waited out.

AI-1 hashes the cost view, so cohort 8743–8746 could no longer decide. It had made
no decision; its only turn was the restarted worker's missed-window skip (742).

At **22:38:50 UTC**, under both singleton locks, the rollover ran with the
36r-pattern script:
- **Checks:** broker and local checks found no open orders and no positions.
- **What changed:** a rolled-back dry run, then one atomic commit, archived
  8743–8746 (status, completion time and note only). The fresh AI-1 cohort is
  **8770–8773** on new strategy rows 18963–18966, identity
  `21f4985d0b87942a0c03974438e9f347338ba2a63ced7bf2d7205b045cb7f897`.
- **Unchanged:** the Amendment 1 plan hash `c95b55e2…b39ead8`, the $140 book,
  allocations, shared costs and other trials.
- **Restart:** the restarted worker reports three active arms bound to these
  trials.
- **Receipts:** `data/forward/ai-rollover/20261007c/attempt-223842-999111/`.
  `result.json` has SHA-256
  `87028a94535c69cc7280af62e7fd885967da1c6f330bb79a0ab9671e6eae9610`.
- **Next decision:** the first is October 8 at 10:30 ET.
