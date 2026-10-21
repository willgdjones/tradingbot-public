# Option-income ETFs (covered-call / put-write): results (`tradingbot-ae1`)

2026-10-15, RainyReef. Pre-registration: [52-option-income-plan.md](52-option-income-plan.md).
Funds: XYLD, QYLD (selectable), JEPI, JEPQ, SPYI (descriptive). PUTW is
delisted. Variants: `hold`, `trend200`. $140 virtual slot, 10 bp per side plus
fees, settled cash, total-return equivalent. Artifacts:
`data/research/option-income/` (source-v2, train-*, selection, final).

## Verdict

**XYLD hold passes PRD §4: profitable after costs in training (+$84.62) and
on its single holdout run (+$75.24).** But holding
SPY at the same exposure did better in both partitions. XYLD gave almost no
protection in the 2020 crash and some in 2022 and 2025. As the owner asked, it
queues as `ready-for-live` (bead below). **My recommendation is not to give it
a slot.** If the aim is lower volatility, a smaller SPY position delivered that
with more return and none of the fund-structure risk.

## Results

| Run | Period | Trial | Net after costs | Max marked DD | CAGR / vol | Return/vol | SPY at equal exposure | QQQ at equal exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| XYLD hold, train | 2014-01 → 2022-12 | 8818 | **+$84.62** | $73.06 (32.9%) | 5.4% / 14.4% | 0.38 | +$214.13 (0.64) | +$345.82 (0.71) |
| **XYLD hold, holdout** | 2022-12 → 2026-09 | **8825** | **+$75.24** | $30.72 (16.4%) | 12.0% / 9.4% | 1.28 | +$133.50 (1.34) | +$214.65 (1.44) |

Equal exposure means the run's average exposure (96%) held constantly, with
the rest in cash. It uses adjusted closes on the same sessions and no costs; the
figure in brackets is that benchmark's return/vol. Both runs finished flat,
with one round trip each, no rejected orders, no halts and no delayed entry.

**Holdout detail:**
- One entry, at the 2022-12-06 open, after the first holdout close. One exit,
  at the terminal 2026-09-30 open.
- Gross +$75.28. Fees $0.04. The 10 bp adverse fills cost $0.42, so costs are
  irrelevant for a held fund.
- XYLD's own buy-and-hold over the period: +56.7%.
- **Luck:** monthly block bootstrap p = 0.0001 over 46 months. This tests the
  hypothesis that the fund did not go up, not that it beat SPY. Against SPY it
  lost.

### Other training runs (from the plan)

| Run | Trial | Net | Max DD | Note |
|---|---:|---:|---:|---|
| XYLD trend200 | 8819 | +$9.79 | 22.6% | 36 trades; the filter cut drawdowns and gave up the return |
| QYLD hold | 8820 | +$78.66 | 25.8% | lost the selection by $5.96, flagged data-sensitive (Yahoo is missing about $5 of QYLD distributions) |
| QYLD trend200 | 8821 | +$0.67 | 20.7% | 41 trades |
| JEPI hold (from 2020-05) | 8822 | +$54.58 | 14.6% | CAGR 13.9%, vol 11.3%, return/vol 1.23 against SPY's 0.79 at equal exposure; 2.5 years only, no holdout |
| JEPQ hold (from 2022-05) | 8823 | −$11.16 | 17.6% | 7 months, all in the 2022 bear market |
| SPYI hold (from 2022-08) | 8824 | +$0.95 | 9.7% | 3 months |

### Stress windows (SPY peak-to-trough closes, fixed before outcomes)

| Window | XYLD hold | SPY | QQQ |
|---|---:|---:|---:|
| 2018 Q4 (09-20 → 12-24) | −17.5% | −19.3% | −22.0% |
| **2020 crash** (02-19 → 03-23) | **−32.4%** | −33.7% | −27.9% |
| 2022 bear (01-03 → 10-12) | −17.1% | −24.5% | −34.3% |
| 2025 tariffs (02-19 → 04-08), holdout | −14.9% | −18.8% | −22.8% |

A covered-call fund keeps nearly all of a fast crash: in March 2020, XYLD
fell as far as SPY and further than QQQ. It cushions slower declines (2022)
because it keeps collecting premium. It gives up most of every rally.

### Calendar years, XYLD hold (marked net on the slot)

| | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (to Sep) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Train | +10.25 | +0.85 | +10.97 | +25.57 | −11.00 | +36.32 | −1.14 | +40.12 | −27.29 | | | | |
| Holdout | | | | | | | | | −1.91 (Dec) | +14.55 | +28.39 | +13.95 | +20.25 |

## Why it trails SPY

The ETFs sell at-the-money index calls every month. The premium (about 1% a
month, paid out) is the variance risk premium. Selling the calls also caps
each month's gain at about that premium. Over 2014-2026 equity rallies were
large and frequent, so the capped upside cost far more than the premium earned.
Crashes like 2020 come too fast for a month of premium to offset. Training CAGR
was 5.4% against 11.0% for SPY at the same exposure. In the holdout, return/vol
was 1.28 against 1.34: XYLD got there with less volatility, but no more
efficiently.

## Promotion checklist (idea → backtest done)

1. **Edge:** the variance risk premium (PRD §3 risk premium), held through a fund.
   Profitable after all costs in both partitions. Most of the profit is equity
   beta, and the fund underperformed its own beta.
2. **Statistics:** one held position per partition. Months are the
   observations: 108 in training, 46 in the holdout. Selection was over 4
   configurations. The data-sensitive flag is in the plan. PBO/DSR were not
   computed: they would test the selection among nearly identical beta
   exposures, and the decision rests on the SPY comparison instead.
3. **Fidelity:**
   - Live, the fund pays about 1% a month in cash on the pay date, after the
     ex-date. The model reinvests it through the adjusted close.
   - A runner must reinvest the cash, about 12 small buys a year, or exposure
     drifts down.
   - Much of each distribution is return of capital or ordinary income. Tax is
     out of scope.
4. **What could blow up this account?** See the plan's section, restated
   briefly:
   - **Crash:** no stop, and a 2020-like crash costs about a third of the slot
     (training max drawdown 32.9%, close to the −40% kill at $56).
   - **Correlation:** it is equity beta like IBS and every other long sleeve,
     concentrating the −$50 daily halt.
   - **Fund risk:** a fund can close (PUTW did).
5. **Limits:** PRD §6 unchanged. No capital, venue, key or order.
6. **Decision:** XYLD hold v1 (`4b933bbe58ed4e86…`) passes PRD §4 and queues
   as `ready-for-live` (bead `tradingbot-s4s`), as the owner asked in the bead.
   The pipeline's next step is a paper fidelity check, unless the owner
   extends the IBS override. **Recommendation: do not fund it.** SPY at equal
   exposure beat it in both partitions. JEPI looked better in its short
   training window, but it has no holdout here, and this family's holdout is
   now used.
