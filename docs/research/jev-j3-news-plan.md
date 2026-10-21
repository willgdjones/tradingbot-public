# J3 Jev news reactor — prospective paper plan

Owner bead `tradingbot-369`; fixed before any J3 model requests or orders.
This is the owner-authorized AI-decided exception in PRD §§3–4. Historical
LLM decisions are not evidence and no historical performance is being claimed.

## Fixed policy and observation

- Registered policy `tradingbot.strategy.jev_j3.J3NewsReactor`, key
  `jev_j3_news`, arm J3. Parameters contain only
  `news_start_at: 2026-10-05T13:30:00+00:00` (Monday's regular open).
- Use the runner's approved 40-symbol universe, committed quarter-hour
  snapshots and free Alpaca headline receipts. For each symbol, classify each
  available new headline separately: Choice `bullish/bearish/neutral`, Score
  bullish strength 0–4, Noul material new information.
- Enter long when any headline is bullish, expected strength is at least 3,
  and material probability is strictly above 0.5. A 0.5 tie is unknown and
  skips. No additional confidence threshold or tuned alternative is used.
- One decision per symbol groups up to five headlines (15 questions), matching
  the existing accessor's bounded coverage. All 40 symbols therefore fit the
  runner's 40-decision ceiling. The provider feed and five-item window can miss
  news during bursts; this is a coverage limitation, not proof of absence.
- A revision is identified by article ID, provider update time, local first
  receipt time and retained headline content. Provider creation/update/receipt
  timestamps must be ordered and timezone-aware. Only receipts in the
  immediately preceding quarter, at or after the frozen start, qualify.
  Post-boundary receipts wait for the next boundary; missed quarters and
  pre-admission history are never replayed. All examined eligible-time
  revisions are durably consumed before model outcomes, including candidates
  blocked by cash, holdings, ATR, data gaps or collection halts.
- Headline text stays in explicitly untrusted state. Static question
  instructions never interpolate it. The wrapper validates answer types,
  probability vectors and Score expectations; refusals/errors/partial replies
  fail closed. Calls use only `ai/jev.py`, `jev-latest` pinned to `jev-1.13.0`,
  under the shared $20 UTC-month cap. No new keys or paid data sources.

## Execution, sizing and controls

Paper allocation ceiling $35, a quarter of the existing $140 shared book.
Each entry requests 90% of that arm allocation, with the balance left for
fees/slippage. Symbol order is alphabetical, fixed before model answers.
Cash and aggregate exposure checks may reject competing signals. There is no
top-up of a holding, no shorting, and at most one entry attempt per symbol per
day per arm. TOM retains its existing allocation and shares actual cash.

Code attaches a stop distance of 1.5 times the observed positive ATR14; absent,
nonfinite or nonpositive ATR means no entry. The runner measures the stop from
actual weighted entry fills and begins flattening five minutes before the
broker-calendar close (including early closes), independently of Jev. Only
actual broker fills enter the real ledger. Fractional marketable DAY limits,
freshness/deadline checks, complete-portfolio risk/cost checks, exact shared
fees, and dated T+1 cash settlement are inherited unchanged. The risk veto can
prevent exits; failed flattening is an incident, never a synthetic fill.

One separately recorded virtual random twin uses the same available headline
groups, receipt rules, targets, source observations and fees. It matches the
real entry decision rate, with a seed fixed before model outcomes, and never
pollutes the real ledger. Different fills/holdings/cash can change later
eligibility and are reported. Its fresh-BBO taker simulator caps displayed
depth conservatively at one share. The control is informational only and
never qualifies for promotion. No ungated J3 arm is created.

## Evidence and promotion review

Admit to **forward paper only**: the owner explicitly authorizes J1–J4 paper
experiments. This supersedes the older checklist's structural-only and
historical-backtest requirements for AI strategies; it does not establish an
edge. All variants and failed admissions remain in the trials ledger.

The runner reports net P&L after fees and actual/reserved model costs, completed
round trips, marked maximum drawdown, daily results and luck statistics. With
zero forward trades, P&L/drawdown/regime evidence and luck odds are unavailable.
Runtime source/code/receipt integrity is part of qualification. The weekly
review must show regime coverage and real/control divergence without treating
the control or luck odds as new success gates.

Queue `ready-for-live` only after at least seven calendar days, 30 completed
real round trips and positive after-cost P&L, with flat confirmed inventory,
no pending orders and valid evidence. Keep paper running and rejudge weekly.
No live keys exist and this runner cannot place live orders. The same pure
policy callbacks are available to paper/live/replay adapters; historical replay
does not count as clean AI evidence. Broker-paper/live fidelity is still
unmeasured and must remain explicit at any later live review.

## What could blow up this account?

**Tail/gap risk:** a headline can be wrong or already priced in; a stock can
gap through the 1.5 ATR stop. A halt, stale quote or dead process can carry the
position overnight. Long-only loss is bounded by the actual position spend,
but a stop does not guarantee the −40% arm kill threshold. Sizing uses the
owner's equity allocation cap, not the superseded $25 prediction-market cap.

**Adverse selection:** this is a delayed, quarter-hour headline experiment,
not a speed edge. Informed traders can move before the feed arrives, and IEX
quotes can be incomplete. The model sees the actual proposed ticket's spread,
fees and conservative model-cost hurdle; a positive classification is not
proof of an executable edge. Taker execution avoids unsupported maker fills.

**Venue/counterparty:** Alpaca paper and free IEX are shared dependencies with
other arms and TOM. Outages can block both entries and exits. PRD §9 accepts
resting orders after process death, no startup account-wide reconciliation,
and execution of checked-out code. Those choices remain unchanged. Existing
paper credentials are used; no withdrawal permission, account or key is added.

**Untrusted inputs:** source text may contain instructions or manipulation.
It remains data in a separate state field; static prompts, validated finite
answers and code-created targets prevent it from selecting symbols, tools,
sizes, stops or risk limits. A model may still misclassify it, causing losses.

**Reproducibility:** model outputs are stochastic and cannot be reproduced by
re-querying history. Immutable question/state/receipt hashes, pinned model,
answers, costs, seeded controls and execution outcomes preserve what actually
happened. Pure policy replay is deterministic given those records. Source
changes invalidate an original experiment's qualification while checked-out
execution continues as accepted in PRD §9.

**Correlation:** J3, J1, J2 and TOM can all lose on long equity exposure at once.
The shared cash guard prevents cash reuse and the existing global daily halt
applies across the account. All PRD §6 constants stay unchanged: −40% per-arm
kill, −$50 global day halt, equity exposure up to the arm allocation, 30-second
staleness, five API errors/minute. A gap can overshoot a threshold.

Decision: approve the fixed $35-ceiling forward-paper experiment, 2026-10-02,
NavyLantern under owner-authorized scope. No capital addition, live promotion,
new venue/key/account, paid data or public post. Admission trial IDs and actual
validation results belong in `jev-j3-news-results.md` after the code is frozen.
