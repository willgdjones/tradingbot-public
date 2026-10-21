# J4 Jev regime switcher — prospective paper plan

Owner-authorized J4 (implementation `tradingbot-32i`, admission
`tradingbot-ec9`). Frozen before any J4 model request or order, 2026-10-04.
This is the AI-decided exception in PRD §§3–4: no historical LLM replay
establishes an edge. Single plan and paper-admission review. Forward results
go in the trials ledger, the weekly report and `46-j4-regime-results.md`.

## Fixed policy

- Registered policy `tradingbot.strategy.jev_j4.J4Regime`, key
  `jev_j4_regime`, arm J4, empty parameters.
- Two decisions per day, at the 09:45 and 12:30 ET boundaries. Each is one Jev
  Choice: trend / chop / risk_off. The instructions tell the model to prefer
  risk_off when the evidence is mixed.
- **Baskets are code-owned** and drawn from the 20 runner ETFs (SPY … UNG,
  including GLD/SLV/TLT/USO/UNG):
  - **trend:** the top 3 by 1-day return, at 30% of the allocation each.
  - **chop:** the 2 lowest by RSI14, at 45% each.
  - **risk_off:** cash.
  - Every regime also sells any held symbol outside its basket.
  - If the model is unavailable, the answer is invalid, or the deadline
    expires, nothing changes (skip). The close flatten still applies.
- Execution inherits the runner unchanged:
  - Entries are marketable DAY limits.
  - There is at most one entry per symbol per day. A symbol sold at 12:30 is
    not re-bought that day, and a held symbol is never topped up.
  - Cash is settled cash only.
  - Flattening starts five minutes before the broker-calendar close.
- J4 has **no price stop**. Its exits are a regime change, the close flatten,
  and the arm/global risk halts.
- Calls go only through `ai/jev.py`, using `jev-latest` pinned to `jev-1.13.0`
  under the shared $20/month cap. J4 uses at most 2 calls a day.

## Controls and evidence

- **Uniform random-regime virtual twin:** picks trend / chop / risk_off at
  random with a seed fixed before outcomes. It uses the same baskets and fees
  and has its own virtual book.
- It is informational only and not a promotion gate. There is no ungated twin.

Qualification follows the owner's J1–J4 rule: at least 7 calendar days, at
least 30 completed real round trips, and positive P&L after fees and model
costs. Positions must also be flat, with no pending orders and intact
integrity. Rejudge weekly. Passing only queues `ready-for-live`.

The maximum is 5 entries a day (3 trend + 2 chop). That means 30 round trips
needs about 2–3 weeks, and longer if the model often picks risk_off.

At freeze there are no trades, no drawdown or per-regime figures, and no
p-value.

## What could blow up this account?

**Tail / gap risk.** There is no stop. A crash between 09:45 and the close
runs the whole ≈$31.50 basket into the loss until the next regime decision,
the close flatten or the −40% arm kill. Commodity ETFs (USO, UNG, SLV) can
move several percent intraday. A halt, stale quote or process death can block
the flatten overnight.

**Adverse selection / model error.** Momentum and oversold baskets chase or
fade on partial IEX data. A misread regime (trend at a top, chop in a
breakdown) causes losses. The random-regime twin shows whether the label adds
anything.

**Counterparty / venue.** The arm depends on Alpaca paper, free IEX and one
local Mac, shared with J1–J3 and TOM. PRD §9 accepted risks are unchanged.
Trade-only paper credentials; nothing new is added.

**Untrusted inputs.** Headline state is untrusted data. The model chooses
only one of three labels. The code owns the symbols, fractions and exits.

**Correlation.** A trend basket is broad long beta, as are J1–J3 and TOM, all
on one $140 cash book. The shared settled-cash guard, the −$50 global day halt
and the −40% per-arm kill are unchanged PRD §6 constants. A gap can overshoot
a threshold.

Decision: admit the fixed $35-ceiling forward-paper experiment, 2026-10-04,
daily autonomous session under owner-authorized J1–J4 scope. No capital, live
promotion, venue, key, account, paid data or public post.
