# Jev intraday runner

Owner scope: J1–J4 on real Alpaca paper, 15-minute regular-session decisions,
one entry per symbol per day **per arm**, settled cash, flat by the close.
Controls are virtual and informational. The existing shared paper cash book
is $140; this infrastructure never increases or resets it. Each admitted arm
has a ceiling of one quarter of that existing initial book. TOM keeps its own
frozen allocation/identity and competes for the same actual settled cash.

## Policy contract

`tradingbot.strategy.jev.JevStrategy` extends the common strategy interface.
Implement pure `plan(View) -> Plan` and `choose(DecisionSpec, answers) -> str`.
Set the class's registered `key`, `arm` (`J1`–`J4`) and `ungated_twin=True`
for J1. Other arms use the default `ungated_twin=False`.
Both functions are reusable in forward paper, live and replay runtimes. The
historical backtester does not synthesize Jev answers or establish AI alpha.

- `Target(symbol, fraction: Decimal, stop_distance: Decimal | None)` requests
  a new long position as a fraction of the arm's frozen allocation. Zero means
  exit. A holding is never topped up. Stops are dollar distances from actual
  weighted entry fills, computed by policy code (for J1/J3: 1.5 ATR).
- `DecisionSpec(key, questions, alternatives, state={}, skip='skip',
  baseline=None, action_class='entry', random_mode='matched')` declares every
  allowed choice before calling Jev. Alternatives map names to tuples of
  targets; their fractions total at most one slot. The skip alternative is
  empty. `action_class` is entry, exit or regime. J4 uses uniform regime draws
  with `random_options=('trend', 'chop', 'risk_off')`; its separate unavailable
  `skip` sentinel must not become a fourth regime. `risk_off` explicitly exits
  each holding with a zero target; an empty target list means hold/no action.
- For J2, set `minimum_size_factor=Decimal("0.5")` on an entry spec and
  implement `size_factor(spec, answers)` as the code formula
  `max(0.5, conviction/3)`. The factor must remain within that declared floor
  and 1; the runtime rounds quantity down and never scales exits. Cost hurdles
  use the smallest permitted ticket. Random controls shuffle the passing
  factor distribution independently of symbol selection.
- `View` contains the frozen boundary/states, the variant's own positions,
  available cash, allocation, entries already used today and durable memory.
  `Plan(decisions=(), memory={})` returns updated memory, including consumed
  headline IDs. Revisions should be distinguished with their receipt/version.
- Keep policy objects stateless except for frozen parameters. Each control
  gets a fresh policy instance and its own memory/holdings. Unknown features
  remain unknown. Headline text is untrusted data. `choose` cannot add targets.

Question instructions need not repeat state-builder slot estimates: the runner
adds the actual proposed quantity and a per-target cost hurdle (spread,
EquityFeeBook round-trip fees and a conservative Jev-call allowance). Model
calls go only through `ai/jev.py`, requesting `jev-latest` with the wrapper's
version pin. Typed questions are batched at 128 per request. The original
30-second observation deadline is never renewed by a later execution quote.

## Controls and persistence

`jev_intraday_turns` uniquely claims `(trial_id, boundary)` before paid calls.
It records the immutable observation, candidate alternatives, RNG seed,
provider receipts and execution outcomes. A process interrupted mid-turn never
repeats that turn. Each real and control variant has its own trials-ledger row.

Failed turns retain `failure.stage` (`view`, `plan`, `costs`, `persist`,
`decide` or `execute`), the exception class and the innermost raising
`file`/`line`. Repository paths are relative; external frames keep only their
filename. Exception messages, source text and local variables are never
recorded. The same failure metadata accompanies the existing daily-deduplicated
`turn_failed` incident; every failed turn keeps its own receipt. Virtual
planning failures and caught execution failures carry the same provenance
without changing real/control isolation or an uncertain order reservation.

No automatic retry was added for transient planning reads: the durable turn
claim still wins, and later stages may already have persisted memory, incurred
provider charges or submitted orders. Diagnosing a specific read-only failure
with the new stage/source evidence comes before designing a separately reviewed
retry. The original observation deadline is never extended, and failed turns
are never replayed. These diagnostics are part of the executable source identity;
old cohort versions are preserved rather than rewritten after a deployment.

Random controls match **decision** pass counts within action class at each
boundary. Equal candidate counts give equal pass counts. Different holdings
can change eligibility; stochastic rounding matches the same rate in
expectation and records the candidate/count difference. J4's regime control is
uniform over its declared alternatives. Unavailable real decisions do not
generate passes and remain in the candidate denominator; an entirely
unavailable action class generates no random entries. J1's ungated control
remains independent of Jev. A control planning/execution failure is recorded
on its own virtual trial and cannot block real orders or qualification.

The equity simulator stores a separate JSON book in each virtual trial; it
never writes Alpaca `orders`, `fills` or `positions`. BBO executions are modeled
takers, at ask for buys and bid for sells. Unknown depth produces no fill.
When raw IEX displayed size is at least one whole unit, fills are conservatively
capped at **one share**, a lower bound whether that unit is shares or round
lots; raw lot counts are never assumed to be full share depth. Partial fills
and differences from real execution must remain visible. Makers require later
trade-through evidence and are unsupported by this equity simulator. Fees use
the same `EquityFeeBook` policy; no real Jev charge is invented for a control.

Sale proceeds settle on the broker calendar's dated T+1 settlement date,
including non-settlement holidays. Virtual risk state and outcomes stay
separate from the real account: permanent strategy kills and cohort daily
halts use the unchanged PRD constants. Random-arm fee rounding is cumulative
within their hypothetical account/day. Each control has its own frozen slot;
TOM and real orders can reduce actual available cash and cause further
execution divergence. Controls never qualify for promotion.

## Scheduling and execution

The tmux service polls every 15 seconds and claims at most one turn per arm per
15-minute boundary, beginning at 09:45 ET. It waits for a committed snapshot
and never replays an earlier missed boundary. All arms receive the same frozen
observation. Arm order rotates by boundary to share limited decision time.
The transport fetches the universe/complete risk portfolio in batched free-IEX
requests, while all 30-second freshness/deadline checks remain in force.

Actual orders are fractional, marketable DAY limits through the existing
Alpaca paper connector. The ledger records only broker fill activities,
including partials and dated settlement. A durable entry reservation precedes
submission; uncertain POSTs are never sent again. A rejected attempt also
consumes that symbol's entry allowance for the day. Existing holdings are not
topped up. Startup performs no account-wide reconciliation; ordinary scheduled
polls refresh only known local intents. No shutdown cancellation/dead-man is
introduced (PRD §9).

Execution details (`tradingbot-jsa`, 2026-10-07):
- The limit is priced at the **fresh** ask (bid to exit) from the guard's
  pre-submit capture, as the plans specify. A buy's quantity is cut so its
  notional never exceeds the ticket its cost proof covered. The deadline is unchanged.
- Symbols resolve only to the broker-registered instrument (Alpaca asset UUID),
  never to a `research:` row with the same symbol. Two broker rows fail closed.
- Quotes stamped up to 1s ahead of this host's clock are held until the clock
  reaches their event time (free-IEX times led it by tens of ms). Timestamps, the
  future-quote checks and the 30-second limit are unchanged.
- A read-only account-cost view refused because another process committed a
  newer Jev receipt or fill mid-read is re-read once with a fresh clock.

Code manages stops continuously and begins closing five minutes before the
broker's actual session close, including early closes. It cancels outstanding
intents and sells the confirmed residual only once those intents are resolved.
These exits run without a Jev response. The risk engine can veto an exit;
unknown fills, stale data, halts, outages or process death can leave exposure.
An after-close residual becomes an incident and invalidates qualification;
the runner never fabricates a flat account.

The common `AIPaperCostGuard` includes regulatory-fee top-ups and all correlated
Jev actual charges/outstanding reservations across the real account. It
preserves any stronger existing guard. Costs update the same risk thresholds
even when every model decision is a skip. Refreshes retain broker fill evidence
when current marking fails. Real sale proceeds cannot be reused before T+1.

## Source quality and morning features

The state builder now resets windows at missing/incomplete/nonadjacent
intervals; it never compresses a data gap into a 15-minute or hourly return.
Session returns and day extrema remain unknown when full-session coverage is
missing. It exposes current close, prior-hour high, ATR14 and volume ratio for
the code-owned rules, plus quality counts, news `known_at`/`updated_at` and
source digests/receipt times.

The runner obtains the immediately preceding session from the broker calendar,
searching at most seven calendar days. Only that session's exact closing
snapshot, observed before the decision and matching the official opening, can
warm RSI/ATR/trend windows. Intraday return windows stay within today. `ret_1d`
compares the same elapsed session boundary on consecutive trading sessions.
Missing prior-session evidence stays unknown. No prior snapshot is replayed
as a current decision. Full source receipts stay in the turn audit, while the
model receives the compact features and separate untrusted headlines.

The Oct 2 closing store has all 40 snapshots, but only seven have fully
complete session bars and 34 have complete final intervals. Those limitations
remain visible; no missing IEX prices are imputed.

## Admission, reporting and operations

Each strategy bead must create its reviewed `Strategy` row (`status='paper'`,
Alpaca venue, allocation at most $35 for the current book), frozen parameters
under `config['params']`, a registered `JevStrategy` class and its one plan file
with the completed promotion/risk review. Then use:

```text
uv run python -m tradingbot.forward.jev_intraday --prepare \
  --module <registered Python module> --strategy-key <registered key> \
  --review-record <repository plan path>
```

Admission saves the source/parameter identity, review path/hash, model pin,
and real/control trial IDs. Failed admission attempts remain in the ledger.
It can run while the daemon is active; the service discovers new admissions
on its next poll. It never changes the cash book or creates credentials.

`ops/jev_intraday.sh` is launched by `ops/services.sh` in its own pane, with
`logs/jev-intraday.log` and a singleton database lock. `--once` performs one
scheduled cycle. With no admitted policies it reports
`waiting_for_admitted_strategies` and makes no model/order call. Other service
panes are not restarted. Four policy implementations remain separate beads.

Weekly consumers read `Trial.metrics['jev_intraday_v1']` and the ordinary
trial P&L/trade/drawdown fields. Metrics distinguish real versus virtual
trials, include daily net P&L, actual/reserved model costs, fee top-ups,
request count/mean latency, source/code/receipt integrity, and promotion
reasons. Turn payloads retain selections, random rate/count audits and actual
execution outcomes for divergence reporting.

Qualification requires at least seven calendar days from first observation,
30 completed real round trips, positive P&L after every cost, a flat ledger,
no pending orders and valid evidence. It sets `ready_for_live` and the
`ready-for-live` pipeline label only; the trial remains running in paper.
Qualified arms are rejudged after seven days, with immediate revocation for
risk/integrity failures. Luck statistics and twins are informational. Changed
checked-out code continues to run as accepted in PRD §9, but a mixed code
identity cannot qualify the original frozen experiment. No live transport is
present in this runner.

Validation on 2026-10-02: 132 distinct checks pass (76 runner/existing Alpaca
transport/connector/cash, 32 state/shared-cost, 24 simulator/control). Tests use
fake HTTP/model calls and isolated rollback-only PostgreSQL state. They cover
partial/uncertain orders, duplicate turns, outages, close/stop behavior, stale
deadlines, risk vetoes, settlement, source gaps, exact random pass counts,
control-failure isolation, provider cost reporting and weekly qualification.
The migration is applied with no schema drift; the real one-cycle smoke check
reports zero admitted arms. No paid request or actual order was made by these
checks. Strategy admission and the required forward evidence remain separate.

Service verification: pane `%39` is running with zero admitted arms, a second
worker is refused by its singleton lock, and the shared $140 initial paper
cash/TOM trial 3298 allocation remain unchanged. Other service panes retain
their original processes.
