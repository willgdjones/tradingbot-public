# X bookmarks batch — 2026-10-05

Source: `docs/strategy-intake/bookmarks.jsonl`, pulled by `ops/x_bookmarks.py` at
2026-10-05 13:27 UTC (5 bookmarks, status `new`). The captured `text` is the
tweet's opening; linked threads/PDFs were **not** retrieved (X login wall, and
the local browser daemon was unavailable this session). Evaluations are desk
triage of the captured gist; where a verdict would hinge on unread thread
content, that is stated. No capital, venue, key or risk-limit change.

## 1. @confinedape — "Twelve research papers worth reading" — **Park (research lead)**
A thread listing 12 primary-source finance papers "for discretionary judgment"
and their usefulness to systematic traders.
- **Gate 1 (concrete rule?): fail** — a reading list, not a strategy.
- **Value:** a pointer to vetted literature that could seed structural-edge
  candidates, overlapping what `docs/research/02-hedge-fund-and-academic.md`
  already covers.
- **Blocker:** the 12 titles are in the unread thread body; the captured text
  has only the intro. Mining it needs the full thread.
- **Verdict: Park.** No bead now — uncertain marginal value over our existing
  academic base, and the actual list isn't in hand. Revisit if the owner wants
  the thread expanded; then extract titles and cross-check against the trials
  ledger before testing any.

## 2. @51bodila — "Jane Street LLMs + AI agents, 16-page PDF" — **Salvage**
Claims Jane Street keeps *uncorrected* historical data because a "corrected"
history can manufacture an edge that never existed.
- **Gate 1: fail** — a secondhand playbook summary, no entry/exit/sizing.
- **Salvageable principle:** use **point-in-time / vintage data**; never backtest
  on restated series, or look-ahead leaks in. This is sound and is **already our
  standard** — forward-recording over revisable series, FRED/COT vintage handling,
  the locked 70/30 holdout, and the "store event date AND first-observed time"
  rule in `04-open-items.md` (X cost study). Nothing new to build.
- **Verdict: Salvage** (principle noted, already honoured). No bead; reject as a
  strategy. The "16-page PDF" is marketing, not evidence.

## 3. @RitOnchain — "HMM regime-detection trading bot" prompt — **Pursue (one bead)**
Hype framing ("leaked Jane Street prompt, paste into claude code") around a
concrete *method*: fit a hidden Markov model to detect market regimes, write one
playbook per state, backtest walk-forward with real costs, and reject the
strategy if it doesn't clear costs.
- **Gate 1 (concrete rule?): pass (as a method)** — HMM state inference on daily
  features → per-regime long/flat (or trend-on/off) → walk-forward, cost-aware,
  self-rejecting on the holdout.
- **Gate 2 (why it works?): pass** — regime-dependent return/vol is a documented
  statistical effect; **deterministic HMM regime detection is a structural/
  statistical edge, not LLM alpha** (no model calls, no Jev cost), so it fits
  "structural edges only" more cleanly than the AI-decided arms.
- **Gate 3 (tradeable here?): pass** — daily ETF/index data from free sources,
  Alpaca cash account, fits §6 and T+1.
- **Gate 4 (evidence exists?):** partial overlap with **J4 (regime switcher)**,
  but J4 is **Jev/LLM-decided**; a deterministic HMM is a distinct, cheaper,
  reproducible detector and is **absent from the c-series** (c01–c20 cover trend,
  inverse-variance, low-vol, yield-curve, credit, country-reversal, etc. — no HMM).
- **Gate 5 (provable?): caution** — regime strategies switch infrequently, so
  trade count is low and statistical power is the real risk; frame it as a
  **regime *overlay/filter* on an existing simple signal** (e.g. trend or
  equal-weight market) rather than a standalone high-churn system, and judge it
  on the locked holdout vs an always-on baseline.
- **Gate 7 (blow-up?):** regime misclassification and whipsaw at transitions;
  look-ahead if HMM is fit on the full sample — must be walk-forward only.
- **Verdict: Pursue** — bead at backtest stage (PRD §4), **P3** (overlaps J4's
  concept and low-frequency/hard-to-prove, so below the live equity work).

## 4. @0xSoural — SpaceXAI engineer on agent verification — **Reject**
"Can't spawn 100 agents if you don't trust one"; verification-skill advice.
AI-engineering/workflow content, **not a trading strategy** (gate 1 fail). Mildly
relevant to our own multi-agent verification habits, but nothing to trade.

## 5. @mattshumer_ — long-horizon builds with Astra — **Reject**
An AI coding/agent technique for long-horizon builds. **Not a trading strategy**
(gate 1 fail). No market edge.

## Outcome
- **Pursue:** 1 → bead for a deterministic HMM regime-filter research backtest.
- **Salvage/Park:** items 1 (reading-list lead) and 2 (PIT-data principle, already
  standard) — no beads.
- **Reject:** items 4 and 5 (not strategies).
