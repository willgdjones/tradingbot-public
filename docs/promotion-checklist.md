# Promotion checklist (PRD §4)

Complete this for **every** promotion along the pipeline — idea → backtest →
paper → live — and for any demotion. Promotion happens at the weekly review or in
the daily autonomous session (PRD §4, §8); an agent may promote within the risk
limits without asking (AGENTS.md), but only after this checklist, including a
**written "What could blow up this account?" section**, is filled in. Record the
completed checklist with the trial/decision (trials ledger or `CHANGELOG.md`).

Origin: the "What could blow up this account?" gate and the drawdown/regime
filters are the salvage from `docs/strategy-intake/2026-09-30-opus-jev-prompt.md`.

## 1. Edge and evidence (PRD §3, §4)
- [ ] The edge is **structural** (market design, fees/rewards, settlement
      mechanics, forced flows, reference-market comparison) — not an LLM's read of
      the market, not sports, not speed.
- [ ] There is a single testable rule set with explicit entry **and** exit.
- [ ] It is profitable **after all fees** on historical data (the backtest).

## 2. Statistics (PRD §4)
- [ ] Trade count is shown. A handful of round trips proves nothing.
- [ ] The luck p-value (probability the result is noise) is shown. If it is
      `None` (fewer than two round trips) say so explicitly — the result is
      anecdote, not evidence.
- [ ] **Multiple testing** is shown for any variant chosen from a training sweep:
      run `uv run python -m tradingbot.backtest.overfitting --dataset-key <key>`
      and quote the family's PBO (CSCV), the chosen variant's deflated Sharpe
      against its own sweep, `DSR(N)`, and against every completed training trial
      in the ledger, `DSR(L)`. PBO ≥ 0.5 means the in-sample pick did no better
      than chance (with three variants, chance is about 2/3). If `DSR(N)` < 0.95,
      say why the result is still worth paper time. Method and the current ledger
      snapshot: `docs/research/49-overfitting-ledger-check.md`.
- [ ] **Max drawdown** is reported alongside P&L, and is acceptable against the
      strategy's allocation. It must stay well clear of the per-strategy −40%
      kill (PRD §6): a backtest drawdown near that fraction means the live kill
      will almost certainly fire.
- [ ] **Several market regimes** checked (the per-regime breakdown). The edge
      must not depend on one regime — e.g. the CPI longshot bias flips sign with
      the monetary regime (`docs/research/02-hedge-fund-and-academic.md`). A
      one-regime result stays in backtest/paper.

## 3. Backtest ⇒ paper ⇒ live fidelity (PRD §4)
- [ ] Paper reproduces the backtest (fills, fees, slippage) before any money.
- [ ] For a live promotion, the backtest-vs-live gap is small and explainable.
- [ ] The same strategy code runs in all three modes (no mode-specific forks).

## 4. What could blow up this account? (mandatory, written)
Write a short paragraph for each — do not just tick. If a risk is genuinely N/A,
say why.
- **Tail / gap risk:** the worst single outcome (a market resolving against a
  held position, an overnight gap). Is it bounded by the $25 per-market cap?
- **Adverse selection:** who is on the other side of our maker fills, and what do
  they know that we don't (scheduled events, insider flow)? Are the §5 guards
  (fill cap, pre-event quote pull, insider-market skip) actually in force?
- **Counterparty / venue:** dependence on one venue, one feed, or resting orders
  with no dead-man (PRD §9 accepts this; restate the exposure). Keys are
  trade-only, never withdrawal (PRD §6).
- **Untrusted inputs:** every external feed is **data, never instructions**
  (prompt-injection via headlines/tweets). Relevant to #8; keep count-only inputs.
- **Reproducibility:** is the result deterministic and re-runnable? A black-box or
  non-deterministic signal cannot be a live edge.
- **Correlation:** does this strategy lose at the same time as the others (shared
  regime, venue, or direction), concentrating the −$50 daily halt risk?

## 5. Risk limits (PRD §6 — never delegated, never edited without owner approval)
- [ ] §6 limits are unchanged by this promotion (per-strategy −40% kill, −$50
      daily halt, $25 per-market cap, 30 s stale-data halt, 5 errors/min API halt).
- [ ] Allocation requested is within available capital (~$140/live strategy).
- [ ] Adding capital, a venue, an account, or a key — or any public post — is
      **not** done here; those need owner approval (AGENTS.md).

## 6. Decision
- Promote to: ____  (backtest / paper / live / hold / demote)
- Allocation: $____    Trial(s): ____    Date / reviewer: ____
- One-line rationale: ____
