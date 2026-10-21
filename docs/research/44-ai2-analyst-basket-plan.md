# AI-2: daily Jev / Claude analyst basket — prospective paper plan

2026-10-05; tradingbot-cvm; RusticElk. The owner explicitly undeferred this
experiment and requested Jev, a Claude arm and a random twin. This replaces the
unlaunched October 2 plan before any AI-2 observations, calls or orders. The
earlier version remains in git; it generated no results. Implementation/admission
is separate from future evidence. No historical LLM backtest counts.

## Hypothesis, universe and frozen decision

Test whether a model's daily long/flat choices improve after-cost returns over
the same universe held at equal weights. Jev and Claude receive the same bounded,
numeric, point-in-time state. A model supplies probabilities only; code owns every
symbol, weight, price and exit. No tuning, substitutions or confidence sizing.

Use the **20 stocks already recorded by the shared IEX/state pipeline**, sorted:
AAPL AMD AMZN AVGO COST GOOGL HD JNJ JPM LLY MA META MSFT NFLX NVDA PG TSLA UNH V XOM.
This replaces the old plan's separately downloaded daily-bar panel with the state
builder the owner requested. Source cutoffs, receipt hashes, missing-feature flags,
market/sector context and original execution quotes are retained in each daily
turn; raw headlines are excluded from model inputs.

- Fixed prospective sessions: **2026-10-06 through 2026-10-23 inclusive**. No
  early stop for favorable performance. October 5 is implementation/admission,
  never a retrospectively reconstructed model decision.
- One common snapshot at **open + 45 minutes** (normally 10:15 New York), with
  an entry window of two minutes. Wait for the recorder's completed boundary;
  then consume the day's turn once, including refusals. No later catch-up.
- Every stock needs a state, one complete most-recent 15-minute interval and a
  fresh valid IEX quote. Missing warmup indicators remain explicit nulls; they
  are never backfilled. Missing one required stock skips the whole daily cohort.
- Ask one named Noul question per stock: probability that the benchmark-sized
  long earns positive P&L after the stated round-trip cost hurdle by the coded
  exit. Jev uses jev-latest, resolved by the wrapper to **jev-1.13.0**. Claude
  uses **claude-sonnet-5-5**, through the shared no-tool headless wrapper on the
  existing subscription. One complete 20-question batch per provider per day,
  no retries. Reject partial, nonfinite, wrong-model or late responses.
- **Long iff p >= 0.5**, including ties. Equal dollar targets among chosen longs;
  no longs means cash. Confidence is max(p, 1-p), recorded, never used to size.
  A failed model leaves its own arm flat; it does not manufacture a prediction
  or suppress the equal-weight benchmark.
- Jev and Claude submit **real Alpaca paper** orders. The **random twin** is a
  separate virtual book: sample exactly Jev's number of selected stocks without
  replacement from the same 20, using a seed committed before model answers.
  The **equal-weight benchmark** holds all 20 in its own virtual book. Controls
  use the existing conservative fresh-BBO taker simulator, observed displayed-size
  bounds, T+1 and fees. They never write broker ledger fills. This changes the old
  unlaunched real-broker benchmark into an explicit virtual comparator; different
  fill mechanisms remain a promotion-review limitation.
- Each real arm has a **$35 simulated ceiling**; each control has a $35 virtual
  book. Common daily target budget is 90% of the smallest of: either arm's
  available slot cash, either control's available cash, $35, and half the
  account's available settled cash after costs/cushions. If twenty $1 minimum
  tickets cannot fit, skip all entries before calling a model. The two real arms
  compete for the existing **$140 shared paper cash book**; no funding, reset,
  J1–J4/TOM allocation change or borrowing occurs. Every actual submission still
  rechecks account cash, current prices and unchanged risk limits.
- Benchmark execution precedes model calls. Alternate which model arm is
  called/executed first by exchange-session date. Persist each receipt before
  its orders; execute the random twin after Jev's choice. Serial ordering,
  model latency, partial fills, cash contention and unfilled orders are measured
  implementation limitations, never adjusted away.
- Entries use the **original 30-second quote/observation deadline**, even if
  later quotes arrive. Marketable regular-session DAY limits and nine-decimal
  shares use the existing connector. Cancel pending entry orders after the
  two-minute window. At **close minus five minutes**, code closes owned positions
  independently of either model. Poll only known intents; never duplicate an
  uncertain POST. Residual positions/pending orders block the next day's entry.
  No startup-wide reconciliation or new dead-man rule is introduced.
- Stop new entries after October 23. Continue resolving known orders/reporting;
  do not silently extend the experiment. This leaves settlement sessions before
  TOM 3298's October 27 planned entry.

## Costs, evidence and evaluation

The existing account-wide AIPaperCostGuard applies dated equity regulatory fees
without double-charging recorded broker fees. Every Jev actual charge and
outstanding reservation counts, even for failed/skipped calls, through
paper-trial:<id>:... attribution. Only the existing Jev wrapper may call Jev;
its owner-approved **$20/month** cap is unchanged.

Claude has **zero incremental subscription cash cost**, only if the adapter
verifies the existing subscription and excludes API-key billing. Retain the CLI's
separate list-price estimate and report P&L sensitivity after subtracting it.
Unknown estimates from failed calls are unknown, not zero. No subscription,
account or key is created/upgraded. Quota refusal means no trade.

Each real arm and control has a trials-ledger row. Freeze code, prompt,
parameters, provider pins, allocation and this plan's SHA before admission.
Source/parameter drift blocks new decisions and requires a new experiment;
existing exits and actual-fill accounting continue. Durable daily claims,
pre-answer random seeds, snapshot payloads, decisions, probabilities, receipts,
order IDs and control fills make missed/interrupted turns visible.

Report gross/net P&L, actual/modeled/provider costs, completed flat-to-flat round
trips, exposure, turnover, rejections/missed days, fill coverage, observed marked
max drawdown, daily results, benchmark-up/down regimes and a descriptive
weekly-cluster luck p-value (null if fewer than two observed weeks). Same-day
stocks are correlated observations, not independent market regimes.

Label each stock's forecast only after its virtual benchmark round trip closes:
net_after_fees > 0. Missing/incomplete labels remain unknown. Report Brier score,
always-yes and 0.5 baselines and five fixed reliability bins, including stocks
left flat. Store Jev labels with the wrapper's outcome API; retain Claude labels
in the same daily audit. These are **virtual-benchmark outcome labels**, not
claimed real-broker fills. Calibration is descriptive, with no extra threshold.
The random twin is informational only.

At the fixed window's end, either model arm queues **eligible for review** only
after seven actual observed calendar days, 30 completed real-paper round trips,
positive net P&L **and net P&L strictly above the equal-weight benchmark**, flat
holdings/no pending orders, complete benchmark coverage, reconciled costs/receipts,
unchanged identity and no risk halt. Do not mark a strategy live automatically.
Weekly review must assess the virtual comparator and real-fill fidelity; live
keys remain owner-owned. Insufficient or losing evidence is a valid reported
outcome, never a reason to retune this version.

## What could blow up this account?

**Tail/gap and correlation.** Both real arms can concentrate in the same US
mega-caps and overlap J1–J4/TOM. A halt, gap or failed exit can strand shares
overnight. Their $35 ceilings and shared settled cash limit requests; unchanged
−40% strategy kills and −$50 daily halts are vetoes, not guaranteed exit prices.
No live capital is allocated or risk limit changed.

**Adverse selection and venue.** We cross spreads on one-venue IEX evidence;
Alpaca paper fills can be more favorable than tradable consolidated prices.
Virtual controls use another fill mechanism and cannot establish live execution
parity. Small tickets magnify rounding/fees. Missing data, latency, partial fills
and accepted Mac/dead-man failures remain recorded risks. Resting DAY limits can
survive process failure. Existing trading-only credentials/venue are reused;
there is no new account or withdrawal permission.

**Untrusted inputs and reproducibility.** Numeric observations and model output
are data, never executable instructions. Claude has no tools or project/broker
context. Code validates all 20 probabilities and owns every intent. Models are
nondeterministic, so evidence is prospective; frozen requests/versions and
receipts support audit, not claims of reproducible historical alpha.

**Admission checklist disposition.** PRD's explicit AI exception replaces the
older checklist's structural-only/historical-profit requirements. This file
defines testable entry/exit, costs, controls, frozen evidence and the written risk
review for **paper admission only**. Trade count, luck, drawdown, regimes and
live-fidelity evidence are pending and reported as such. Implementation tests
and source/account preflight must pass before admission. No backtest or profit
result is invented and no historical holdout is consumed.

## Amendment 1 — snapshot validity on free IEX data (2026-10-07, `tradingbot-jxa`)

Made before any AI-2 decision, order or model call. Across the four captured
sessions (October 2, 5, 6 and 7), only 12–16 of the 20 stocks had all 15 IEX
minute bars for 10:00–10:15 ET. The free IEX feed has no bar for a minute with
no IEX trade, and the shared state builder then counts the interval as
incomplete. The rule "one complete most-recent 15-minute interval" for every
stock therefore skipped every day, so the comparison could never start.

From this version, every stock still needs:
- a state;
- a fresh, valid IEX quote within the unchanged 30-second limit;
- live event collection.

Missing any of these, for any stock, still skips the whole daily cohort. A stock
whose most-recent interval has a bar-less minute no longer skips the day. Its
state is unchanged: the shared builder leaves its price features as explicit
nulls and reports `complete_suffix_intervals = 0`. Both models see exactly that,
with the quality flags. Nothing is backfilled, and no price is carried forward.
Each turn lists those stocks under `incomplete_latest_interval`.

Questions, the 0.5 threshold, sizing, exits, arms, controls, the window,
allocations, qualification and every PRD §6 limit are unchanged. The written
review above still applies: entries and marks still require the same fresh
quotes. The change alters what the models know on some days, not account risk.
