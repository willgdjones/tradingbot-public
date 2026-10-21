# Backtest-overfitting check over the trials ledger

`tradingbot-cs9`, 2026-10-07. This is research tooling, not a strategy. The source
is the 2026-10-07 bookmark on the probability of backtest overfitting
(`docs/strategy-intake/2026-10-07-x-bookmarks-batch.md`, item 3). Code is in
`src/tradingbot/backtest/overfitting.py`, tests in `tests/backtest/test_overfitting.py`.
The full output is in `49-overfitting-ledger-check.json` (SHA-256 `c05e6094…`), from
the ledger as of HEAD `5d15af7`.

## Method

- **Selection family:** the completed, non-final training trials that share a
  dataset split and a holdout family (`backtest.holdout.family_identity`). This is
  the set a variant was picked from. The **chosen variant** is the training trial
  with the same `strategy_version` as the family's final-holdout trial. Where there
  is no final trial, it is the best in-sample variant.
- **Input:** each trial's `metrics.monthly_marked_net_usd`, over training months
  only. Months missing from a series are zero P&L: some replays book P&L by exit
  month and omit quiet months. Sharpe is per month on USD P&L. That equals the
  return Sharpe only while the allocation is constant.
- **PBO**, from combinatorially symmetric cross-validation (Bailey, Borwein,
  López de Prado & Zhu 2014):
  - Split the training months into 16 contiguous blocks.
  - Each of the C(16,8) = 12,870 half/half splits is one test. Pick the best
    in-sample Sharpe and find its out-of-sample rank.
  - PBO is the share of splits where the pick lands at or below the median.
  - With no skill, PBO is about 1/2 for an even number of variants and 2/3 for
    three (the median rank then counts as a miss).
  - `P(loss)` is the share of splits where the pick lost money out of sample.
- **DSR**, the deflated Sharpe ratio (Bailey & López de Prado 2014): the
  probability that the chosen variant's true Sharpe beats the expected best of `N`
  skill-less trials, given its skew, kurtosis and length. There are two versions:
  - `DSR(N)` uses the family's own `N` and the spread of its variants' Sharpe ratios.
  - `DSR(L)` uses every completed training trial in the ledger (`N` = 172) and the
    spread of all 103 trials that have a monthly series.
  - `DSR(L)`'s benchmark is a monthly Sharpe of 0.345, about 1.2 annualised. It is
    the upper bound on how much searching this project has done.
- **Command:** `uv run python -m tradingbot.backtest.overfitting [--dataset-key K] [--json PATH]`.
  It is read-only.

## Results (training data only; holdout untouched)

| Family | N | Months | PBO | P(loss) | Chosen trial | SR/yr | DSR(N) | DSR(L) |
|---|---|---|---|---|---|---|---|---|
| c-rox | 8 | 175 | 0.11 | 0.00 | 7850 | 0.82 | 0.86 | 0.09 |
| c02 | 6 | 167 | **0.75** | 0.17 | 5407 | 0.41 | 0.94 | 0.00 |
| c03 | 6 | 175 | 0.05 | 0.00 | 5482 | 0.65 | 0.96 | 0.02 |
| c04 | 12 | 175 | **0.86** | 0.01 | 4063 | 0.74 | 0.99 | 0.06 |
| c05 (and its total-return revision) | 6 | 158 | 0.33 | 0.44 | 3959 / 5385 | 0.16 | 0.58 | 0.00 |
| c08 | 2 | 74 | 0.01 | 0.07 | 3907 | 0.57 | 0.92 | 0.06 |
| c08 total-return revision | 4 | 74 | 0.06 | 0.10 | 5477 | 0.57 | 0.53 | 0.06 |
| c09 | 6 | 175 | 0.02 | 0.06 | 5492 | 0.18 | 0.03 | 0.00 |
| c10 | 4 | 175 | 0.09 | 0.04 | 5528 | 0.43 | 0.77 | 0.00 |
| c11 | 8 | 175 | 0.06 | 0.06 | 5388 | 0.10 | 0.11 | 0.00 |
| c12 (no final; best in-sample) | 8 | 175 | 0.29 | 0.88 | 5511 | −0.13 | 0.06 | 0.00 |
| c17 | 4 | 158 | 0.50 | 0.00 | 5586 | 1.03 | 1.00 | 0.28 |
| c19 | 4 | 175 | 0.24 | 0.00 | 5645 | 1.00 | 1.00 | 0.26 |
| c20 | 4 | 175 | **0.71** | 0.34 | 5683 | 0.06 | 0.55 | 0.00 |
| classic-TA awesome | 3 | 91 | **0.83** | 0.17 | 6383 | 0.60 | 0.92 | 0.05 |
| classic-TA Bollinger (no final) | 3 | 91 | n/a: all variants flat | – | 6366 | 0.00 | – | – |
| classic-TA Heikin-Ashi | 3 | 91 | 0.10 | 0.05 | 6381 | 1.26 | 0.96 | 0.56 |
| classic-TA RSI | 3 | 91 | 0.56 | 0.25 | 6371 | 0.62 | 0.92 | 0.02 |
| classic-TA SAR | 3 | 91 | 0.32 | 0.21 | 6375 | 0.46 | 0.70 | 0.02 |

## Reading

- **Nothing survives the ledger-wide deflation.** The best `DSR(L)` is 0.56
  (Heikin-Ashi on MSFT), far below 0.95. After 172 training variants, no single
  backtest is strong enough on its own to rule out search luck. Forward paper
  evidence and the untouched holdout carry the weight.
- **High PBO (c02, c04, c20, awesome):** the in-sample pick did no better than
  chance. In c04 the 12 variants are a near-identical parameter grid. That makes
  the family spread tiny, so `DSR(N)` looks strong (0.99) even though the pick
  itself is noise. For these families, read PBO and `DSR(N)` together, not
  `DSR(N)` alone.
- **Low PBO with a weak Sharpe (c09, c11, c10):** the pick was consistent, but
  the edge is small. `DSR(N)` is 0.03–0.77. All three holdout results were
  negative.
- **c05 is on paper** as `c05_total_return_paper_v1`. Its family has PBO 0.33,
  out-of-sample loss in 44% of splits, SR/yr 0.16 and `DSR(N)` 0.58: weak
  multiple-testing evidence. This is no incident and changes no paper status;
  it is flagged for the weekly review.

## Coverage gaps

These sweeps have no monthly series in the ledger, so neither check can run on
them:
- `turn_of_month` (on paper), c01, c06, c07;
- longshot (30 variants);
- the classic-TA dual-thrust, MACD and shooting-star families, and the source/
  data-fail rows.

Paper and AI cohorts are out of scope. Their evidence is the forward
7-day/30-trade run.

## Coverage gaps closed (`tradingbot-9os`, 2026-10-07)

`uv run python -m tradingbot.backtest.monthly_backfill --commit` derived a monthly
USD series for 47 training trials. It used only evidence each trial already
recorded; nothing was re-run, and no final-holdout trial was touched.

- **Storage:** each series is a NEW metrics key, `monthly_net_usd_derived`, which
  records its basis, source and reconciliation. No existing metric was edited.
- **Reconciliation:** every series totals the trial's own recorded net within
  $0.0001, or within the trial's stored cash-reconciliation tolerance if larger.
  The largest difference is $1.8e-5 (c07).
- **Undo:** `UPDATE trials SET metrics = metrics - 'monthly_net_usd_derived'`.

| Family | Source | Basis | Trials |
|---|---|---|---|
| turn_of_month | ledger fills by `trial_id` (round trips) | exit month (New York) | 3277, 3279, 3280 |
| c01 | `monthly_returns` × `start_equity`, terminal open liquidation booked in the last month | month-end equity | 3313–3318 |
| c06 | `monthly_net_usd` | exit month (New York) | 3541–3546 |
| c07 | last `daily_exposure.marked_equity_usd` of each month | month-end equity | 4064, 4065 |
| longshot | `monthly_marks` (start/end equity chain) | month-end equity | 30 trials, 3808–3967 |

c01's labels are pinned by its recorded first-year return. A one-month shift
fails that check. TOM's control trial 3278 has no trades and stays without a
series.

**Command and receipt:** `uv run python -m tradingbot.backtest.overfitting`, from
the ledger after the backfill. The receipt is
`49-overfitting-ledger-check-9os.json` (SHA-256 `0e42e623…`), at code `3c4e523`.
The `DSR(L) 36m+` column comes from rerunning the same command with
`--variance-min-months 36`.

| Family | N | Months | PBO | P(loss) | Chosen trial | SR/yr | DSR(N) | DSR(L) | DSR(L) 36m+ |
|---|---|---|---|---|---|---|---|---|---|
| turn_of_month (on paper) | 3 | 90 | 0.00 | 0.01 | 3277 | 0.78 | 0.95 | 0.01 | 0.14 |
| c01 | 6 | 174 | 0.02 | 0.02 | 3316 | 0.82 | 0.97 | 0.00 | 0.10 |
| c06 (no final; best in-sample) | 6 | 175 | 0.60 | 0.98 | 3545 | −0.25 | 0.09 | 0.00 | 0.00 |
| c07 (2 of 6 completed; no final) | 2 | 175 | 0.36 | 0.74 | 4064 | −0.06 | 0.33 | 0.00 | 0.00 |
| longshot (4 blocks, 6 splits) | 30 | 11 | 0.33 | 0.67 | 3935 | 0.73 | 0.45 | 0.16 | 0.33 |

**The ledger-wide variance depends on sample length.** The backfill raised the
trials with a series from 103 to 150. It also raised the cross-trial Sharpe
variance from 0.0161 to 0.0364, which lowers every family's `DSR(L)`; the earlier
families now show 0.00–0.12. Almost all of that rise comes from the 30 longshot
variants. Their 11-month Sharpe estimates are noisy: with no skill, the variance
of a Sharpe estimate is about 1/T, roughly 0.09 at T = 11 against 0.006 at
T = 175.

`--variance-min-months 36` keeps the shorter families out of the variance (120
trials) and brings it back to 0.0166. With it, the earlier families'
`DSR(L)` values return to close to the first table: Heikin-Ashi 0.54, c17 0.26,
c19 0.24. Read `DSR(L)` with the 36-month floor for the long equity families.
`N` is 172 either way.

**Reading:**

- **Turn of month (on paper):** the in-sample pick is stable (PBO 0.00, out-of-sample
  loss in 1% of splits), and `DSR(N)` is 0.95 against its own three variants.
  The three variants share one rule set, so a low PBO is expected and says
  little; the family spread is narrow.
  - Against the whole ledger, `DSR(L)` is 0.01, or 0.14 with the 36-month floor.
  - As for every other family, the backtest alone can't rule out search luck.
    TOM's forward paper run carries the evidence. No paper status changes.
- **c01:** similar. The pick is stable (PBO 0.02, `DSR(N)` 0.97) but far below
  the ledger-wide benchmark (`DSR(L)` 0.10 with the floor).
- **c06 and c07:** negative in-sample. The best variant loses out of sample in
  98% and 74% of splits respectively. This confirms the existing negative
  results.
- **Longshot:** 11 months give only 4 CSCV blocks (6 splits), so its PBO is
  coarse. The final variant 3935 has `DSR(N)` 0.45 against 30 variants. The
  family stays deferred with prediction markets.

**Remaining gaps:** none among completed training trials. The families still
without a series have only failed, source or data-fail rows (batch2 c09–c14,
c15, c16, c18, the classic-TA dual-thrust, MACD and shooting-star families, and
the sweep-v1 rows). Trials without a `dataset_key` are outside the selection
families, as before.

## Independent cross-check (NavyHill, `e0513f5`)

- **Agreement:** a separate stdlib implementation matched the first table to
  floating point on 18 of 19 families. That covers per-variant Sharpe, `DSR(N)`,
  `DSR(L)` and the ledger-wide benchmark Sharpe.
- **The one gap is c20 PBO:** 0.71 here, against 0.35 when ties are ranked in
  the pick's favour.
  - c20 has 3 non-zero months out of 175, so 1,287 of the 12,870 splits have a
    flat in-sample pick.
  - Sparse-activity families (January-only and the like) are therefore sensitive
    to how ties are ranked.
  - This module counts "no better than its peers" as a miss, which is the
    faithful CSCV reading.
