# AI-1 daily trade-gate comparison

Pre-registration for `tradingbot-efn`, 2026-10-05. The owner explicitly undeferred
this daily experiment after J1–J4 were deployed. It reuses their state builder,
Jev wrapper, Alpaca paper connector, settled-cash ledger, fee overlay, risk checks
and coded close exits. Existing J-suite code, allocations and frozen identities
remain unchanged. This is prospective paper research, with no historical LLM
backtest or claim of an edge.

## Frozen design

- At 10:30 ET (broker open plus 60 minutes), once per session, rank the existing
  40-symbol liquid ETF/mega-cap universe by its complete first-hour
  `ret_session`, descending, ties by symbol. Take the strongest eight, including
  negative returns on broadly down days. Require four complete 15-minute bars,
  a known full-session return, fresh IEX quotes and a usable execution estimate.
  Fewer eligible symbols produce fewer signals; missing data is never filled in.
- This tests intraday continuation of relative strength, a behavioural hypothesis.
  Eight potential signals/session gives 40/week with complete data. The actual
  last-five-session count must reach 30 before qualification; missing/skipped
  sessions remain visible. This frequency has not yet been demonstrated.
- Three real Alpaca paper arms: **ungated, Jev-gated, Claude-gated**. Each has a
  $15 paper slot within the existing shared $140 book; no funds are added or reset.
  Each candidate receives 0.90/8 of its arm's allocation, about $1.6875 before
  fractional rounding. Rejected signals remain cash; there is no redistribution.
  All arms get the same candidates, input instant, quotes, quantity estimates and
  original deadline. Entire cohort skips before calls if full paired settled cash
  is unavailable, any real arm has unresolved positions/orders, or tickets are < $1.
- The fixed binary forecast is the probability that the **ungated** long makes
  positive P&L after execution costs by the coded exit. Jev `jev-latest` resolves
  through the existing wrapper to `jev-1.13.0`; Claude is pinned to
  `claude-sonnet-5-5`. Gate passes at p >= 0.55; absent, malformed, wrong-model or
  late replies do not trade. Numeric state and bounded headlines are untrusted
  evidence, never instructions. Models cannot choose quantities, symbols or tools.
- One informational virtual random arm draws exactly Jev's pass count without
  replacement over the identical candidate set, using a durable pre-call seed.
  It uses the J-suite's conservative taker simulator and has its own $15 virtual
  book, separate from real orders/fills/cash. It cannot qualify for live.
- Jev and Claude calls run concurrently. Claim the cohort day and freeze inputs
  before calls; persist all returned receipts and choices before orders. No
  restart repeats a consumed day, even after a crash. Rotate which real arm
  submits first daily, interleaving arms per symbol. The 30-second freshness
  deadline is never renewed. Partial orders and deadline/cash divergence remain
  evidence, not assumed matched fills. Missed entry windows are never replayed.
- Enter only in the first two minutes after the scheduled boundary. Use the
  existing fractional marketable DAY-limit connector; cancel remaining known
  entry orders once the two-minute window ends. One entry per symbol/day;
  no topping up. Hold until the shared runner begins closing five minutes before
  the actual broker close, including early closes. No model is needed to exit.
  Unknown/pending intents reconcile by their original IDs; no duplicated POST.
  Real broker fill activities alone enter the ledger. Proceeds settle T+1.

## Provider and evidence accounting

Jev calls use only `ai/jev.py`, its global $20/month cap and correlated receipts.
Every charge/reservation feeds the shared account cash/risk guard, including
unavailable answers. Claude uses the already authenticated `claude -p`
subscription (local CLI 2.1.289 checked), from an empty temporary directory with
an environment allowlist and tools, MCP, customizations, hooks and skills
disabled. It cannot inherit broker/Jev/API credentials. The 18-second call has
no retry or fallback. Subscription auth is required before each call.

Claude's reported `total_cost_usd` is a client-side list-price estimate, **not an
invoice**. Record that estimate and usage separately. Primary paper P&L assumes
zero incremental cash cost for included existing-subscription usage; also show
net P&L less the full reported estimate as a sensitivity. Any actual billed
overage invalidates that assumption and must be reconciled before qualification.
An unavailable call's missing estimate stays unknown rather than zero.
No new key, subscription or extra-usage setting is created/enabled here.

Source contracts checked before implementation:
[Claude programmatic CLI](https://code.claude.com/docs/en/headless),
[model IDs](https://platform.claude.com/docs/en/models/overview), plus the locally
installed `claude --help` and redacted `claude auth status`. The latter confirmed
existing first-party Max subscription authentication. Monid discovery offered
API alternatives; the authorized subscription route is used.

The trials ledger holds every arm, frozen source/parameters, review digest,
daily observations, seed, requests, receipts, predictions and execution results.
All daily code/fee/state dependencies form the frozen identity. Changes prevent
new daily decisions and qualification of the old version. No live transport exists.

## Qualification and reporting

After at least seven calendar days of actual observations and 30 completed real
round trips, each gated arm must have positive after-cost P&L **and beat the
real ungated arm**, with flat holdings, no active orders, valid costs/code/source
evidence, no kill/halt, and at least 30 actual base signals over the last five
session records. Gates also require at least 30 labels, no unresolved predicted
outcomes, and a Brier score strictly better than always-yes on the same labels.
Every selected gated trade must also complete at the same share quantity as its
ungated counterpart; unfilled/partial selected executions prevent qualification.
Only an actual completed ungated round trip labels a signal, including ones the
model rejected; absent fills remain unlabeled. Jev labels attach immutably to
the wrapper's calibration log. Ties/zero P&L are negative outcomes.

Report all arms, net P&L, completed round trips, maximum observed drawdown,
daily changes, descriptive zero-edge luck probability, calibration/reliability,
provider cost/availability, skipped days and execution divergence. Report trade
P&L by the fixed first-hour SPY up/down/flat/unknown regime, with model charges
separate. These short-run regimes do not establish broad market robustness.
No luck p-value threshold is added. Ungated/random are controls, not live candidates.
Passing queues `ready-for-live`; paper continues with weekly rejudgment. No live
keys exist and none are requested.

## Completed paper promotion review

The PRD §4 owner-approved AI exception replaces historical proof with prospective
7-day/30-trade evidence. The deterministic base rule and code-owned gate use the
common strategy interface; historical tests cannot establish model alpha. The
statistical, calibration, regime and live-fill checklist items remain pending
forward observations. Every PRD §6 limit is unchanged: permanent −40% strategy
kill, −$50 account/day halt, 30-second freshness and 5 API errors/minute. Equity
positions stay within their own $15 paper allocation. This record authorizes
paper admission only, contingent on passing implementation checks.

### What could blow up this account?

**Tail/gap risk:** correlated long equities can fall together; this is not a
market-neutral strategy. A halt, dead process or unavailable exit can leave
overnight shares and a loss larger than the intended intraday risk. The existing
−40% strategy kill is enforced, but cannot guarantee an executable stop or cap
a gap. Fractional positions are bounded by each allocation; no shorting, margin
or options are involved.

**Adverse selection:** taker entries and tiny tickets are sensitive to spread,
fee rounding and subsequent price moves. IEX is not the consolidated market;
paper fills can be more favorable than live fills. The fee overlay and current
quotes are required, and actual broker activities are retained. These checks
do not prove live capacity or a profitable momentum effect.

**Venue/operations:** all real arms share Alpaca and one $140 cash book with
TOM and J1–J4. Existing strategies can exhaust settled cash; missing paired
capacity skips the experiment. Accepted Mac/network/dead-man and checked-out
code risks remain. Pending DAY orders can persist after process death. No new
account, key, venue, startup reconciliation or shutdown cancellation is added.

**Untrusted inputs/reproducibility:** observations are point-in-time data;
headline text cannot grant tools or change policy. Claude has no tools or repo
context; Jev has typed questions. Code validates answers and owns orders. Model
nondeterminism is measured prospectively with immutable prompts/receipts, never
presented as reproducible historical performance. Quota or provider failure
means no gated entry. Subscription cost assumptions are explicit and reviewable.

**Correlation:** candidate baskets overlap each other and existing strategies.
Shared cash/fee/risk guards apply account-wide. The trial reports dependencies,
partial execution and small-sample limits; three similar paper arms are not
three independent sources of evidence.

Decision: admit four ledger variants (three real, one virtual) to paper only;
live evidence, acceptance statistics and any allocation increase remain pending.

## Amendment 1 — model-input scope and deadline (2026-10-06, `tradingbot-mna`)

Made before any decision under the amended version. On October 5 the first
cohort sent both models all 40 observations with headlines. That was about 50k
estimated tokens, and Jev's documented limit is 32k tokens for state plus the
longest question, so Jev refused the request and only Claude answered. The same
turn took its 30-second deadline from the oldest of all 40 quotes: a 16-second-old
LLY quote that was neither a candidate nor shown. That left 14 seconds, and six
of eight ungated entries expired before submission.

From this version, both models receive the identical observations of the day's
candidates plus SPY, the fixed regime symbol, with the same decision contexts and
execution estimates (about 16k tokens on October 5's turn). Each candidate's state
already carries its market and sector context. The deadline is fixed once, after
planning and before any call: the earlier of the feature cutoff plus 30 seconds
and 30 seconds after each quote of those symbols. It is never renewed, and every
order still re-checks its own quote. A request still over Jev's limits fails
closed with no call or charge, and that arm does not trade that day.

Candidates, question, threshold, sizing, exits, arms, allocations, qualification
and every PRD §6 limit are unchanged. The written review above still applies:
orders may now use the full 30-second freshness window that the plan already
allowed, so no new account risk is added.
