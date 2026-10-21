# J1 Jev gate — prospective paper plan

Owner-authorized J1 (implementation `tradingbot-1tc`, admission
`tradingbot-ec9`). Frozen before any J1 model request or order, 2026-10-04.
This is the AI-decided exception in PRD §§3–4: no historical LLM replay
establishes an edge. Single plan and paper-admission review. Forward results
go in the trials ledger, the weekly report and `46-j1-gate-results.md`.

## Fixed policy

- Registered policy `tradingbot.strategy.jev_j1.J1Gate`, key `jev_j1_gate`,
  arm J1, empty parameters. Universe: the runner's 40-symbol IEX list.
  Decisions come at quarter-hour boundaries from 09:45 ET.
- **Base rule (code-owned):** the latest completed 15-minute close is above
  the prior one-hour high, and the volume ratio is above 1. The symbol must
  also be flat, have no entry today, and have a finite positive ATR14.
  Otherwise no decision is created.
- **Gate:** one bounded Jev Choice per dimension (data quality, signal
  alignment, market regime, event risk, execution versus cost hurdle) with
  the options ok / conflict / block / insufficient.
  - Code skips the entry on any `block`, or on any `conflict` with
    confidence ≥ 0.55.
  - Any other answer enters.
  - If the model is unavailable, the answer is invalid, or the deadline
    expires, the entry is skipped (fail closed).
- **Entry:** one long slot requesting 90% of the $35 arm allocation, as a
  marketable DAY limit at the fresh ask. The stop is 1.5 × ATR14 below the
  actual weighted entry fill. There are no top-ups and no shorts.
- **Exits are code-owned.** The runner sells when the bid crosses the stop,
  and starts flattening five minutes before the broker-calendar close. J1
  emits no exit decisions.
- Headlines are passed only as an untrusted state field. Calls go only through
  `ai/jev.py`, using `jev-latest` pinned to `jev-1.13.0` under the unchanged
  shared $20/month cap. The cap is shared by J1–J4, so heavy breakout days
  can use up budget that the other arms need. When the cap is hit, every arm
  fails closed (it skips) and nothing is overspent.

## Controls and evidence

- **Ungated virtual twin:** takes every base-rule breakout (`baseline="enter"`).
  It measures what the gate adds.
- **Random virtual twin:** passes breakouts at the real gate's matched rate,
  using a seed fixed before outcomes.
- Both twins are informational only, never touch the real Alpaca ledger, and
  are not promotion gates.

Qualification follows the owner's J1–J4 rule: at least 7 calendar days, at
least 30 completed real round trips, and positive P&L after fees and
actual/reserved model costs. Positions must also be flat, with no pending
orders and intact source/code integrity. Rejudge weekly. Passing only queues
`ready-for-live`; no live keys exist.

At freeze there are no trades, no drawdown or per-regime figures, and no
p-value. These are reported as forward data accumulates.

## What could blow up this account?

**Tail / gap risk.** Breakouts can reverse sharply, and a halt or gap can jump
through the 1.5 ATR stop. A stale quote, a risk veto or process death can block
the stop or the close flatten and carry the position overnight. Loss is bounded
by the ≈$31.50 position, but the stop does not guarantee the −40% arm kill.

**Adverse selection.** Breakout entries are momentum-chasing taker fills on
partial IEX quotes. Late breakouts often fade. The cost-hurdle question and the
ungated twin make this visible but do not prevent it.

**Counterparty / venue.** The arm depends on Alpaca paper fills, free IEX bars
and one local Mac, all shared with J2, J3, J4 and TOM. The owner-accepted PRD §9
choices are unchanged: no dead-man cancel and no startup reconciliation.
Trade-only paper credentials; no key, account or venue is added.

**Untrusted inputs.** Headline text could carry instructions. It stays data,
and the model can only pick finite labels. The code owns the symbol, size, stop
and risk.

**Correlation.** J1–J4 and TOM are all long US equities/ETFs on one $140 cash
book. A market-wide drop hits them together. The shared settled-cash guard,
the −$50 global day halt and the −40% per-arm kill are unchanged PRD §6
constants. A gap can overshoot a threshold.

Decision: admit the fixed $35-ceiling forward-paper experiment, 2026-10-04,
daily autonomous session under owner-authorized J1–J4 scope. No capital, live
promotion, venue, key, account, paid data or public post.
