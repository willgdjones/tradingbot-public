# C-ROX: HMM regime filter on SPY — preregistration

2026-10-05, NavyHill. Bead `tradingbot-rox`; from intake
[2026-10-05-x-bookmarks-batch](../strategy-intake/2026-10-05-x-bookmarks-batch.md)
(@RitOnchain "fit an HMM to detect regimes, one playbook per state, walk-forward
with real costs, reject if it doesn't clear costs").

**Amendment 2026-10-05 (pre-outcome, nothing consumed), after RusticElk review
(Agent Mail 7179):** the decision rule's fit/decode wording below was corrected
to match the implementation and the causality argument — the HMM is **fit on and
Viterbi-decoded over the window ending at the deciding close t** (causal because
that window contains no post-t observation), replacing the earlier, imprecise
"strictly before t" / "filtered" wording. The frozen hyperparameter block's
promises — single-threaded fit, and treating a non-converged or degenerate fit
as a no-decision — are now implemented in `strategy/rox_hmm_regime.py`. No
training/holdout trial had been run, so no result or holdout admission is
affected by this clarification.

**Frozen source (2026-10-05):** `data/research/rox-hmm-regime/source.json`,
sha256 `fda5d8afa5b1c4ceb330e1fd18207c92a36945ddfb4740ded773e7660b2e9450`, 5218
sessions — the cross-checked SPY total-return bundle reused from C11 (input
hashes re-verified). Recorded here so the runner may replay; the training
`selection.json` hash is appended below before the single holdout final.

**Frozen training selection (2026-10-05):** `data/research/rox-hmm-regime/selection.json`,
sha256 `bd22331d7a3abb60ade16b7f739ce616ae80374121c9bbc4230d6566df0b40e3`.
Selected variant **`k3_retvol`** (training trial 7850, strategy version
`e7ae9476ab3e5ac3402884e3d88896e0cf035c5169958a435726f43318b32fcf`) — the
highest positive, complete 10 bp training net (+197.11 on the $140 slot). The
1-D `ret` variants did not converge (net 0, no decisions); the other `retvol`
variant was +167.92. This hash authorises exactly one 10 bp holdout final.

**Status: preregistration frozen; source + training selection frozen; holdout final pending.**
Training ran on the 70% partition only; the 30% holdout final has not run. Actual allocation $0.
This is a **deterministic, statistical** strategy — a Gaussian HMM, **no LLM/Jev
calls** — so it is distinct from J4 (the Jev-decided regime switcher) and is
absent from the c-series (c01–c20). Gates 1/2 pass (concrete rule / documented
regime-dependence mechanism); gate 3 passes (daily ETF, free data, Alpaca cash,
fits §6/T+1). Gate 5 is the real risk: **regime switches are infrequent, so the
trade count and statistical power are low** — this is judged on the locked
holdout against an always-long baseline on risk-adjusted terms, with **no
profitability, paper-fidelity or live-readiness claim**.

## Hypothesis and distinction

Equity return and volatility are regime-dependent (calm/trending vs
turbulent/drawdown). A Gaussian HMM fit only on past data can classify the
current regime; **gating a passive long position to flat during the
lowest-mean-return ("risk-off") regime** should improve risk-adjusted net return
versus always holding. This is a **filter/overlay**, not a standalone
high-churn system, and not a directional forecast. It is deterministic
(fixed seed, fixed hyperparameters); the "AI" framing of the source is dropped.

## Universe, instrument and benchmark

- **Traded instrument:** SPY only (one liquid broad-market ETF). Single-asset by
  design, to isolate the regime-filter effect from cross-sectional selection.
- **HMM input:** SPY's own completed daily history (below). No other series.
- **Benchmarks (not traded):** (a) **always-long SPY buy/hold** — the "always-on
  baseline" the overlay must beat; (b) cash. The overlay is only interesting if
  it beats always-long after costs on the holdout, primarily on drawdown /
  risk-adjusted terms.

## Fixed decision rule

At each **month's final regular-session close t** (monthly cadence to bound
turnover and overfitting):

1. **Refit** the HMM on SPY daily log returns observed **within the current
   partition over the expanding window that ends at t** (i.e. up to and including
   t's completed close). Require at least **756 completed trading days** (~3y) of
   in-partition history before the first decision; otherwise no decision (hold
   the prior position, default flat before the first valid decision).
2. **Decode** the current state by **Viterbi** over that same through-t window
   (`GaussianHMM.predict`). This is causal **because the window ends at t** — it
   contains no observation after t — not because any observation is withheld; no
   smoothed/forward-backward pass over a longer series is used.
3. **Label** the **risk-off state** deterministically as the fitted state with
   the **lowest mean daily return** (tie-break: highest return-variance, then
   lowest state index).
4. **Hold long SPY** (full budget) iff the current decoded state **is not** the
   risk-off state; otherwise **go flat** (cash). Execute at the **next eligible
   regular open**. Monthly target expires at the next decision.

No threshold search, confidence sizing, second filter, or discretionary
override. The playbook is binary long/flat per the risk-off label only.

## Ordered variants (training selection only)

Kept deliberately small to limit search:

1. `k2_ret` — K=2 states, feature = daily log return (1-D).
2. `k3_ret` — K=3 states, feature = daily log return (1-D).
3. `k2_retvol` — K=2 states, features = [daily log return, 20-day realized vol] (2-D).
4. `k3_retvol` — K=3 states, features = [daily log return, 20-day realized vol] (2-D).

× two cost cases (5 bp, 10 bp) = **eight training trials**; selection uses the
10 bp nets (5 bp twins are information-only). Listed order breaks ties.

**Frozen HMM hyperparameters** (identical across variants except K and features):
`covariance_type="full"`, `n_iter=200`, `tol=1e-4`, `random_state=0`,
k-means init (hmmlearn default), realized vol = sqrt(252)·stdev of the trailing
20 completed daily log returns. Implementation adds `hmmlearn` via `uv add`
(pulls scikit-learn/scipy); determinism is pinned by `random_state=0` and a
single-threaded fit. If a refit fails to converge or yields a degenerate
(collapsed-variance) state, that decision is a no-decision and is logged, never
silently skipped.

## Frozen data, cash and execution contract

- **Interval:** `2006-01-01T00:00:00Z` inclusive to `2026-10-01T00:00:00Z`
  exclusive. The **final (holdout) partition** begins at exactly 70% of elapsed
  UTC time via the shipped `HoldoutSplit` (end-exclusive), not by row count.
  Each partition starts flat; all HMM warm-up (the 756-day minimum) and signal
  observations for a decision stay **within that decision's partition**. The
  final's walk-forward refits may use all data before each holdout decision
  (standard expanding-window fitting); the holdout is only **run once** and is
  never used for selection.
- **Free data:** Yahoo split/dividend-adjusted daily SPY closes, cross-checked
  against an independently adjusted second source (Alpaca adjusted or Stooq, or
  the documented Nasdaq-close × Alpaca dividend-factor route). Require daily
  total-return agreement within **5 bp on ≥99% of paired days**; retain every
  disagreeing/unmatched day. Pin raw bytes and source/code hashes before any
  strategy outcome. `DATA_FAIL` is reserved for missing/contradictory **prices**
  only. No primary patching, ticker/interval substitution, paid source, or
  synthetic pre-inception history.
- **Research standard:** total-return equivalents (no separate dividend cash);
  exact fractional/corporate-action mechanics and the Amendment-21 blackout are
  **not** prerequisites (blackout omitted).
- **Sizing:** $140 virtual cash, no borrowing/shorts/interest. At decision equity
  E, budget **B = min(0.95·E, $140)**, cash reserve 0.05·E. Long = buy SPY to B;
  flat = liquidate to cash. Signals use completed closes; execute at the next
  eligible regular open. Floor units to 1e-9; skip a buy below $1 without
  redistributing.
- **Costs:** exactly **5 bp and 10 bp per side**, adverse raw-cent rounding then
  conversion to adjusted units, plus `EquityFeeBook` (dated 2026-09-17) on
  raw-share equivalents. Current-account fee/settlement scenarios, not recovered
  historical fees. Fund expenses already in price are not double-charged.
- The last eligible open in each partition is liquidation-only, with costs and
  the unchanged §6 risk vetoes. A vetoed exit or residual inventory is reported
  and makes that run ineligible, never erased.

## Trials, one final and reporting

Four ordered variants × two cost cases = **eight training trials**. Log every
attempt, no-decision and failure before execution. **Select only the highest
positive, complete, flat, rejection-free 10 bp training net**; listed variant
order breaks ties. Crucially, because the always-long baseline may itself be
strongly positive, selection also records whether the winner **beats always-long
after 10 bp costs in training** — a variant that is positive but worse than
always-long is reported and still eligible to be the single final (the holdout
decides), but the headline test is **overlay vs always-long**, not vs cash. No
eligible positive winner means **no final**.

Commit the source/code and the exact selected trial/version/receipt into this
same plan before running **one final at 10 bp** in canonical family `c-rox`.
A failed or interrupted final is still consumed; no second cost case, sibling or
cosmetic revision may reuse it.

Create **one** results file (`48-rox-hmm-regime-results.md`). Report gross/net,
fees, adverse rounding, trade count, **turnover and number of regime switches**,
**max drawdown**, a **per-regime / per-decade breakdown**, exposure (fraction of
time held long), and the comparison vs always-long SPY and cash. Preserve the
gate-5 statistical-power limitation explicitly: a small number of regime
switches means a favourable holdout is **suggestive, not significant**, and no
live-readiness follows. PRD and §6 limits are unchanged by this research.
