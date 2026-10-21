# Gotobi-day USD/JPY: results (`tradingbot-z1t`)

2026-10-09, FoggyOwl. Research only; no venue, capital $0. Frozen design,
amendments and receipts: [plan](51-gotobi-plan.md). Code:
`src/tradingbot/research/gotobi.py`. Artifacts: `data/research/gotobi/`.

## Verdict: FAIL. Gotobi is not a reason to fund an FX or futures venue.
- **The gotobi effect was real in 2016–2022.**
  - Long USD/JPY from 03:00 to the 09:55 JST fix on gotobi days averaged
    **+5.4 bp gross** and was positive in every training year.
  - Gotobi days beat control days by 5.8 bp (p 3×10⁻⁶).
  - EUR/JPY showed the same pattern.
- **It has nearly gone in the locked 2023-07 → 2026-09 holdout:**
  - **+0.24 bp gross per trade** (median +1.8 bp) over 188 trades.
  - That is **−2.76 bp net** at the 3 bp venue cost, with t-test p = 0.95.
  - It is negative even at FXCM's own spread (−0.15 bp).
  - Gotobi minus control is only +1.2 bp (p 0.30).
- **No venue can trade it:** the break-even round-trip cost is about
  **0.24 bp**, roughly a third of a pip. That is far below any futures or
  retail spot cost.
- The decay showed early: the 2023 days still in training gave only +1.1 bp.
  The published papers (2017, 2023) and the wide retail discussion are the
  likely cause.

## Training (2016-01 → 2023-07-11 04:48 UTC)
Per-trade bp. Net = gross − 3 bp. Quoted = FXCM ask/bid. Control = the same
window on non-gotobi business days. USD at $140 notional per trade.

| Trial | Window | Pair | Trades | Gross | Quoted | Net | t-test p | Win | Control gross | Gotobi − control | Net USD | Max DD |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| 8806 | open_fix 09:00→09:55 | USDJPY | 568 | 2.47 | 2.20 | −0.53 | 0.82 | 48.6% | 0.52 | +1.95, p 0.002 | −4.22 | $7.90 / 5.6% |
| **8807** | **early_fix 03:00→09:55** | **USDJPY** | **488** | **5.42** | **5.14** | **+2.42** | **0.0099** | **57.4%** | **−0.34** | **+5.76, p 3e-6** | **+16.53** | **$2.52 / 1.8%** |
| 8808 | post_fix_fade 09:55→12:00 (short) | USDJPY | 312 | 3.38 | 3.14 | +0.38 | 0.31 | 51.3% | 1.04 | +2.35, p 0.016 | +1.67 | $1.76 / 1.3% |
| 8809 | open_fix | EURJPY | 568 | 2.09 | — | −0.91 | 0.95 | — | — | +2.25, p 0.0002 | −7.24 | $10.48 |
| 8810 | early_fix | EURJPY | 488 | 5.38 | — | +2.38 | 0.006 | — | — | +4.40, p 5e-5 | +16.24 | $2.52 |
| 8811 | post_fix_fade | EURJPY | 302 | 1.64 | — | −1.36 | 0.97 | — | — | +1.13, p 0.12 | −5.76 | $7.47 |

- **Admission:** only `early_fix` on USD/JPY passed all three rules (net > 0,
  p < 0.05, gotobi beats control). It was selected.
- **The 09:00→09:55 window the intake proposed is real but too small:** about
  2.5 bp gross, below any realistic cost.
- **The drift starts well before the Tokyo open,** consistent with Bessho
  et al.'s 03:00 JST start.

**`early_fix` USD/JPY, mean gross bp per year (training):**

| Year | Trades | Mean gross bp |
|---|---:|---:|
| 2016 | 64 | 9.4 |
| 2017 | 67 | 7.3 |
| 2018 | 66 | 5.2 |
| 2019 | 65 | 1.9 |
| 2020 | 64 | 4.4 |
| 2021 | 63 | 5.2 |
| 2022 | 66 | 6.8 |
| 2023 (to the cut) | 33 | 1.1 |

**Regimes** (gross / net bp):

| Regime | Gross bp | Net bp |
|---|---:|---:|
| 2016–2019 | 5.93 | 2.93 |
| 2020–2021 | 4.78 | 1.78 |
| 2022 | 6.77 | 3.77 |
| 2023 to the cut | 1.10 | −1.90 |

**Month-end-only gotobi days:** 34 trades at 4.65 bp gross, against 5.48 bp
on the 5th/10th/… days.

## Final holdout: trial 8812, run once (2023-07-11 → 2026-09-30)
Run through `claim_final`, family `gotobi`, the same strategy version as 8807.

| | USD/JPY (verdict) | EUR/JPY (replication) |
|---|---:|---:|
| Trades (gotobi Tue–Fri) | 188 | 188 |
| Mean gross bp (median) | **0.24** (1.81) | 2.09 (2.95) |
| Mean quoted-cost bp | −0.15 | 1.53 |
| Mean net bp (−3 bp) | **−2.76** | −0.91 |
| t-test p (net > 0) | 0.95 | 0.72 |
| Win rate (net) | 46.8% | 49.5% |
| Control mean gross bp (372 days) | −0.94 | 0.11 |
| Gotobi − control | +1.17 bp, p 0.30 | +1.99 bp, p 0.14 |
| Net USD at $140 per trade | −7.27 | −2.39 |
| Max drawdown | $8.13, 5.8% of slot, 580 bp | $5.38, 3.8%, 385 bp |
| Monthly block-bootstrap p | 0.96 | 0.71 |

**USD/JPY gross bp by year:**

| Period | Trades | Mean gross bp |
|---|---:|---:|
| 2023 H2 | 32 | 0.58 |
| 2024 | 63 | −1.19 |
| 2025 | 60 | 0.05 |
| 2026 to September | 33 | 2.96 |

**Month-end-only gotobi days:** 13 trades at −6.1 bp.

**FXCM coverage gap:** 85 Tue–Fri holdout business days, gotobi and control
together, were dropped for a missing anchor. Most fall in the 2024–2026 weeks
that have no FXCM archive file. Whole weeks are missing, so both groups lose
days alike, but the holdout is smaller than its calendar length suggests.

## Multiple testing
Run with `uv run python -m tradingbot.backtest.overfitting --dataset-key gotobi:bb30c4a2…`.
- The family has 6 variants over 91 months, with **PBO 0.03**. The in-sample
  pick was not luck within the family.
- The chosen variant, 8807, has DSR(N) 0.34 and DSR(L) 0.00 against the
  180-trial ledger.
- The holdout result agrees with the low DSR. A real past effect does not
  make a current one.

## Data
- **Prices:** FXCM public one-minute bid/ask (primary), cross-checked against
  HistData one-minute bid bars.
  - Both pairs passed: 99.4–99.7% of days agree within 5 bp on every window
    return, with 97.7–99.9% coverage and a median difference of about 0.2 bp.
  - Dukascopy (the intake's suggestion) now requires a requester-pays AWS
    bucket, so it was not used.
- **Two harness bugs were found and fixed before training,** both from
  price-only diagnosis (plan amendments A2–C):
  - HistData's stamps are not the documented fixed EST. They follow New York
    DST until 2018 and EU DST dates from 2019. Each week's UTC offset is now
    read from the Sunday 17:00 New York open.
  - Crossed FXCM quotes (ask < bid, concentrated at the 09:55 fix minute) are
    kept at mid rather than dropped.

## What could blow up this account?
The study failed, so nothing is promoted. The risks in the plan still apply if
anyone revisits it:
- **Leverage:** one micro yen contract is about $8k notional. That is about
  8× the account and 60× the PRD §6 slot.
- **Intervention and policy gaps:** moves of 2–5 yen in minutes, with W2 held
  through the US close.
- **Decay:** a published, crowded anomaly. This holdout shows the decay.

## Disposition
- No futures/FX venue case. The parked "trading" half of intake item 2 stays
  parked, now with evidence against it.
- **Do not reopen with re-cut windows.** A different gotobi window on these
  pairs would be a new idea with the 2023–2026 period already seen
  (holdout spent: FamilyHoldoutSpend trial 8812).
- **The legitimate re-test is a forward one:** if a yen venue is ever funded
  for another reason, a paper run would show whether the effect has
  returned.
