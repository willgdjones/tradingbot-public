# C-ROX: HMM regime filter on SPY — results

2026-10-05, NavyHill. Bead `tradingbot-rox`; preregistration
[48-rox-hmm-regime-plan.md](48-rox-hmm-regime-plan.md). Core estimator
correctness by RusticElk (`tradingbot-rox.1`, commit `4b930af`).

**Verdict: FAIL the headline test — do not pursue. Not promotable, not
live-ready.** On the locked holdout the overlay returned **+34.6%** versus
**+161.4%** for always-long SPY over the same window: the regime filter sat in
cash ~72% of the time and gave up ~127 points of return for a modest drawdown
reduction (17.1% vs 24.5%). Only **3 holdout trades** — no statistical
significance (luck p-value undefined). This creates no live designation and no
capital/venue/key/risk change. Research only; the trials ledger holds the
durable evidence (training trials, holdout final trial 7851).

Frozen artifacts (gitignored under `data/research/rox-hmm-regime/`; hashes in the
plan): source `fda5d8af…b2e9450` (5218 SPY sessions, reused from C11),
selection `bd22331d…b0e3`, final `e6ee7788…2d51`. Split: 70% training to
`2020-07-10T14:24Z`, 30% holdout to `2026-10-01Z` (shipped `HoldoutSplit`).

## Training (70% partition, ~2006 to 2020-07; selection only)

Four variants × two cost cases; adjusted total-return equivalent, $140 virtual
slot, 5/10 bp adverse slippage + dated `EquityFeeBook`, monthly decisions.

| variant | 10 bp net $ | long months | switches | trades | max DD | note |
|---|---:|---:|---:|---:|---:|---|
| k2_ret | **0.00** | 0 | 0 | 0 | 0% | 1-D return HMM never converges → all no-decision (null) |
| k3_ret | +87.61 | 65 | 1 | 1 | 32.7% | bought once and held; not a working filter |
| k2_retvol | +167.92 | 109 | 18 | 9 | 15.6% | converges; real toggling |
| **k3_retvol** | **+197.11** | 120 | 13 | 7 | 16.4% | **selected** (highest positive 10 bp net) |

5 bp twins were information-only (k2_retvol +169.36, k3_retvol +198.29, k3_ret
+87.84, k2_ret 0). **Selection rule:** highest positive, complete, 10 bp
training net; listed variant order breaks ties. Selected **`k3_retvol`**
(training trial 7850, version `e7ae9476…b32fcf`).

**Convergence finding:** under the frozen `n_iter=200` / `tol=1e-4`, the 1-D
`ret` Gaussian HMM does not converge on daily SPY returns (log-likelihood still
moves ~0.01–0.4 at the iteration limit), so every `ret` month-end is an explicit
no-decision (correctly rejected by the estimator, net 0). The 2-D `retvol` model
(return + 20-day realised vol) is far better identified and converges, so only
the `retvol` variants produced a live filter. This was established as a
methodology pre-check (convergence behaviour only, no holdout P&L inspected).

## Holdout (30% partition, 2020-07-10 to 2026-10-01; run once)

`k3_retvol` at 10 bp, final trial **7851**, version matched the committed
selection before the feed was built.

| metric | C-ROX overlay | always-long SPY | cash |
|---|---:|---:|---:|
| net on $140 | **+$48.43 (+34.6%)** | +161.4% | 0% |
| max drawdown | 17.1% ($30.03) | 24.5% ($112.7) | 0% |
| trades / switches | 3 / 6 | — | — |
| average exposure | 28.4% | 100% | 0% |
| fees / adverse cost | $0.12 / $0.89 | — | — |
| luck p-value | undefined (too few monthly returns) | — | — |

Per-regime (holdout buckets): **2020-2021 net 0, 2022 net 0** (the filter was in
cash — it dodged the 2022 drawdown but also the recoveries), and **2023-2026 net
+$48.43** (all of the holdout P&L, 3 trades). 74 month-end decisions, 24 long.

## Why it fails, and the honest limitations

- **It loses badly to its own baseline.** The whole point of an overlay is to
  beat always-long after costs; it returned +34.6% against +161.4%. The drawdown
  reduction (17.1% vs 24.5%) is real but nowhere near enough to justify giving up
  ~127 points of return. A regime filter is crash insurance, and its value is
  entirely conditional on a large drawdown falling inside the window.
- **The holdout was a poor window for crash insurance.** It begins 2020-07-10,
  *after* the COVID crash, so it is mostly a bull market; a cash-heavy filter
  (28% average exposure) structurally underperforms there. The strong training
  net (+197, spanning the 2008 and early-2020 crashes) **did not generalise** —
  textbook regime-dependence, which the preregistration flagged as the main risk.
- **No statistical power.** 3 holdout trades / 7 training trades is far below any
  reasonable bar; the luck p-value is undefined. Even the drawdown advantage is a
  near-anecdote.
- **Deterministic and causal, as designed.** Fit-through-t, Viterbi decode over
  the window ending at t, single-threaded, with non-converged/degenerate fits as
  explicit no-decisions (RusticElk's `rox.1`). So the failure is a property of the
  edge, not a bug or a look-ahead artefact.

## Disposition

Closed as a negative result. `k3_retvol`'s holdout is consumed (single-use); no
second variant, cost case or window may reuse it. No follow-up bead: a daily SPY
regime overlay does not clear its baseline, and chasing a cadence/feature that
would is post-hoc fishing on a spent holdout. The deterministic HMM machinery
(`strategy/rox_hmm_regime.py`, the `c11`-based runner) remains available should a
*different*, separately preregistered regime hypothesis be worth testing later.
PRD and §6 limits unchanged.
