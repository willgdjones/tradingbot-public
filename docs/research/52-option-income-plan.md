# Option-income ETFs (covered-call / put-write): pre-registration (`tradingbot-ae1`)

2026-10-15, RainyReef. Research only: $140 virtual slot per run, $0 actual.
Source: owner "try it" on [intake 2026-10-14](../strategy-intake/2026-10-14-wheel-strategy-mft.md)
(the wheel is capital-blocked; a fund gives fractional exposure to the same premium).

## Question and rule

Covered-call and put-write ETFs sell index options every month and pay the
premium out. Holding one collects the variance risk premium (PRD §3 risk
premium) on top of equity beta, with capped upside. The question is whether
holding one in a $140 slot is profitable after costs (PRD §4) and how it
compares with simply holding SPY or QQQ at the same exposure.

Two variants, both long/flat, fixed before any outcome:
- **`hold`:** long from the first open after the partition's first close to the
  partition's last open.
- **`trend200`:** long only while the completed adjusted (total-return) close is
  strictly above the mean of the last 200 completed closes. Flat until 200
  closes exist inside the partition. Decide at the close, trade at the next open.

Total-return closes are used because these funds pay about 1% a month: a raw
price average would drift down with every distribution and bias the filter to
"out". No stop, no rebalancing and no other parameter.
Code: `src/tradingbot/strategy/option_income.py` and
`src/tradingbot/research/option_income.py` (source, train, final).

## Universe, fixed before outcomes

| Fund | Strategy | First trade | Role |
|---|---|---|---|
| XYLD | S&P 500 buy-write (Cboe BXM), monthly at-the-money calls | 2013-06-24 | **selectable** |
| QYLD | Nasdaq-100 buy-write, monthly at-the-money calls | 2013-12-12 | **selectable** |
| JEPI | Active defensive S&P 500 stocks + out-of-the-money index calls via notes | 2020-05-21 | descriptive only |
| JEPQ | Active Nasdaq-100 + out-of-the-money calls via notes | 2022-05-04 | descriptive only |
| SPYI | S&P 500 + index call spreads (NEOS) | 2022-08-30 | descriptive only |
| PUTW | Cboe S&P 500 PutWrite | — | **excluded:** delisted. Yahoo has no data and Alpaca has no asset. Not substituted. |
| SPY, QQQ | — | — | benchmarks only |

Inception dates are from Yahoo metadata; tradability (active, fractionable) is
from Alpaca's asset endpoint. Both were read without prices.

JEPI, JEPQ and SPYI started too late to cover the training window. JEPQ and
SPYI have 7 and 3 months of training data, and their `trend200` would never
trade there. Each gets one descriptive `hold` training run on its own history.
None of them can be selected or take the final, so this family produces **no
holdout evidence for them**. That is the price of one final per family.

## Data, execution and holdout

- **Window:** 2014-01-01 to 2026-10-01 (exclusive), the first full year in
  which both selectable funds exist. `HoldoutSplit` 70/30 by elapsed time:
  training ends and the holdout starts at **2022-12-04T04:48:00Z**. Training
  therefore covers 2018 Q4, the 2020 crash and most of the 2022 bear market.
  The holdout covers 2023-2026, including the 2025 tariff sell-off. Each
  partition starts flat, with warm-up inside the partition.
- **Prices** (research data standard): Yahoo split- and dividend-adjusted
  daily open/close. Second source: Nasdaq close × Alpaca all/split dividend
  factor, falling back to Alpaca all-adjusted closes. Accept at ≥99% of paired
  daily returns within 5 bp. Single-source years are disclosed, not resliced.
  Every session from a fund's first trade must match the archived exchange
  calendar. A fund that fails is recorded as DATA_FAIL with no outcomes.
- **Distributions:** total-return equivalent, meaning distributions are
  reinvested through the adjusted-close factor. No separate dividend cash and no taxes. A
  live slot would receive monthly cash and has to reinvest it.
- **Execution:** same as IBS (`50-ibs-mean-reversion-plan.md`):
  - total-return-equivalent replay, ledger, unchanged §6 risk vetoes and the
    dated `EquityFeeBook`;
  - target min(95% of equity, $140), 5% cash reserve, $0.01 fee buffer;
  - settled cash only, quantity floored to 1e-9, $1 minimum;
  - **10 bp per side** adverse, cent-rounded, plus fees, in one cost scenario;
  - the partition's last open only exits.
- **Selection (one final per family):** the training grid is XYLD and QYLD ×
  `hold` and `trend200`, four runs, plus the three descriptive holds.
  - The winner is the highest **positive, complete, flat-at-terminal** 10 bp
    training net among the four selectable runs. Ties go to listed order:
    XYLD before QYLD, `hold` before `trend200`.
  - That one winner runs **once** on the holdout, in family
    `option_income_etf`.
  - No positive selectable run means no final, and the family fails.
  - No sibling fund, variant, cost case or renamed version can reopen the
    holdout.

## What gets reported

For every run:
- net and gross after costs, fees and adverse cost, trades, exposure and turnover;
- marked max drawdown (dollars and %);
- calendar years (including **2020** and **2022**) and the fixed regimes;
- annualised return, volatility and return/volatility;
- the monthly block-bootstrap luck p-value. For a held position, months with a
  marked change are the observations, and the p-value needs at least 30.

**Benchmarks** (not selectable), on the same sessions:
- **SPY and QQQ** buy-and-hold, at full exposure and **at equal exposure** (the
  run's average exposure held constantly, rest cash, no costs);
- the fund's own buy-and-hold.

**Stress windows** (SPY peak-to-trough closes, fixed now): fund vs SPY and QQQ
return over 2018-09-20→2018-12-24, 2020-02-19→2020-03-23,
2022-01-03→2022-10-12 and, in the holdout, 2025-02-19→2025-04-08.

**Pass (PRD §4):** profitable after all costs in training **and** on the single
holdout run, with complete execution.
- Buy-and-hold of an equity fund will usually pass that over multi-year
  windows, so a pass mostly proves the fund went up.
- Whether the slot is worth it rests on the comparison: the fund against SPY or
  QQQ at equal exposure, and its drawdown in the stress windows. Losing that
  comparison does not fail PRD §4, but the results file states it plainly.
- If the family passes, it queues for live like IBS, subject to the owner.

## What could blow up this account?

- **Edge/evidence:** the variance risk premium is documented (Cboe BXM/PUT
  studies), but these funds are mostly **equity beta with capped upside**.
  Covered calls give up most of a rally and keep almost all of a crash. That
  asymmetry is the main risk: they trail the index in bull markets and do not
  protect much in bear markets.
- **Tail/gap:** long-only with no stop. A crash like March 2020 (−30% or more
  in weeks) hits the slot nearly in full. The −40% strategy kill ($56) is the
  backstop. `trend200` exits late, after a fall is under way, and whipsaws in
  V-shaped recoveries.
- **NAV erosion and distributions:** the high payouts include return of
  capital. Price falls over time, and only total return matters. In a live cash
  account the distributions arrive as cash and must be reinvested, otherwise
  exposure drifts down (a fidelity gap versus this model).
- **Fund structure:** JEPI and JEPQ use equity-linked notes (bank counterparty
  risk). SPYI uses index options with the 60/40 tax treatment. Tax is out of
  scope here. A fund can close, as PUTW did; a closure forces a sale at NAV.
- **Execution:** small fractional market-hours orders on liquid ETFs. Spreads
  are a few cents; 10 bp per side is a scenario, not a measurement.
- **Venue:** Alpaca only, a Mac, no dead-man switch (PRD §9 accepted). Any
  future key trades only, never withdraws.
- **Correlation:** long equity beta like the C-family, IBS and J1-J4 longs.
  It loses on the same days and concentrates the −$50 daily halt.
- **Untrusted inputs:** price data only; nothing is read as instructions.
- **Reproducibility:** deterministic Decimal rule; source bytes and code
  hashes are pinned before outcomes; tests check prefix causality and
  next-open fills.
- **Limits:** PRD §6 limits unchanged. No capital, venue, key or order here.

**Decision at this stage:** idea → backtest only. No paper or live claim.

## Source amendment before outcomes — 2026-10-15

The first freeze, `data/research/option-income/source.json` (SHA-256
`a34eef4d2cd2768188f6e2c08ecb30cc1b3740520f2ada000cae472f1742501c`, kept, not
used), failed XYLD and QYLD on the second-source check. QYLD agreed on 92.4% of
days; XYLD agreed on 96.3% on the Alpaca fallback, after a missing-day error on
Nasdaq × Alpaca. JEPI, JEPQ, SPYI, SPY and QQQ passed. No strategy outcome was
computed.

**Cause: the check, not the prices.**
- Raw closes agree across sources. Yahoo vs Nasdaq official closes match within
  1.5 cents on 2,503 of 2,503 QYLD days and 2,502 of 2,503 XYLD days.
- Alpaca's all-adjusted closes are **rounded to the cent**. These funds pay
  about 1% a month, so 2016-2023 adjusted prices sit near $5-11, and cent
  rounding alone moves a daily return by 5-10 bp. Yahoo's factor is a clean
  step function that changes only on ex-dates (126 for QYLD); Alpaca's
  all/split ratio changes on 1,715 days.
- XYLD's Alpaca bars and dividend records restart in 2020 (May for dividends,
  August for bars).

**Amendment (v2), fixed before running it:**
- The decisive second source for **every** symbol is Nasdaq official closes
  with **Alpaca cash-dividend records** (corporate-actions API, captured and
  checksummed). The reference daily return is close / (previous close −
  dividend going ex), the same convention as an adjusted close. Nasdaq's own
  dividend history covers only Nasdaq-listed funds, so it is not used.
- Coverage starts at a symbol's first recorded ex-date, because earlier absence
  is unknown rather than zero. Days before that, and before Nasdaq's ~10-year
  window, are single-source and disclosed.
- Acceptance is unchanged: ≥99% of paired daily returns within 5 bp, and every
  session from first trade present. The v1 rounded-factor checks are kept in
  the source as diagnostics only.
- The source is `data/research/option-income/source-v2.json`. Code:
  `dividend_reference` and `alpaca_dividends` in the research module, with a
  test that a back-adjusted series agrees with the reference exactly.

## Source frozen before outcomes — 2026-10-15

Source `data/research/option-income/source-v2.json`, SHA-256
`be1c7beabad61668a25e74711462ca6bac849f11b82cc03554c358ebae5706bf`
(41 pinned input files). Every symbol has every calendar session from its
first trade to 2026-09-30, none missing or extra. Every recorded ex-date has an
official close. The only other corporate action is one name change.

| Symbol | First session | Sessions | Official close + dividends | Paired days | Disagreeing | Single-source |
|---|---|---:|---:|---:|---:|---|
| XYLD | 2014-01-02 | 3,205 | 100.000% | 1,600 (from 2020-05-19) | 0 | 2014-01-02 to 2020-05-18 |
| QYLD | 2014-01-02 | 3,205 | 99.920% | 2,502 (from 2016-10-17) | 2 | 2014-01-02 to 2016-10-14 |
| JEPI | 2020-05-21 | 1,598 | 100.000% | 1,569 (from 2020-07-02) | 0 | first 6 weeks |
| JEPQ | 2022-05-04 | 1,106 | 100.000% | 1,086 (from 2022-06-02) | 0 | first 4 weeks |
| SPYI | 2022-08-30 | 1,025 | 99.703% | 1,009 (from 2022-09-22) | 3 | first 3 weeks |
| SPY | 2014-01-02 | 3,205 | 99.840% | 2,502 (from 2016-10-17) | 4 | 2014-01-02 to 2016-10-14 |
| QQQ | 2014-01-02 | 3,205 | 99.880% | 2,502 (from 2016-10-17) | 3 | 2014-01-02 to 2016-10-14 |

The disagreeing days (10-100 bp) are ex-dates or single-day print differences,
listed in the source. The holdout (from 2022-12-05) is fully paired for every
symbol.

**Known primary-source gaps, disclosed and not patched:**
- **QYLD:** Yahoo lacks five monthly distributions that Nasdaq's dividend
  history records: 2014-11-26 (0.85%), 2015-02-25 (0.65%), 2016-01-20 (1.0%),
  2016-03-23 (0.71%) and 2017-10-25 (0.61%). It also overstates 2017-12-20 by
  about 0.45% (0.2495 against 0.13577).
  - Net effect: QYLD's 2014-2017 training total return is **understated by
    about 3.4%**, roughly $5 on the slot.
  - Only 2017-10-25 and 2017-12-20 fall inside the paired window; they are its
    two disagreeing days. The rest are in the single-source years.
  - **Pre-declared:** the selection rule stays mechanical. If QYLD loses the
    selection by less than 3.5% of its own training ending equity, the
    results file flags the choice as data-sensitive.
- **XYLD:** before 2020-05-18 there is no independent dividend record. Yahoo
  shows 12 ex-dates in every year from 2014 to 2025, consistent with monthly
  payments. Raw closes agree with Nasdaq from 2016-10.

## Training frozen before the holdout — 2026-10-15

Seven training trials, 10 bp per side plus fees, each from its first session
to the 2022-12-04 holdout start. All finished flat, with no rejected orders and
no halts. No fund, variant or cost case was added.

| Run | Trial | Net after costs | Trades | Exposure | Max marked DD | CAGR / vol | SPY at equal exposure | QQQ at equal exposure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **XYLD hold** | 8818 | **+$84.62** | 1 | 96% | $73.06 (32.9%) | 5.4% / 14.4% | +$214.13 | +$345.82 |
| XYLD trend200 | 8819 | +$9.79 | 36 | 65% | $38.12 (22.6%) | 0.8% / 8.4% | +$130.76 | +$200.37 |
| QYLD hold | 8820 | +$78.66 | 1 | 96% | $68.12 (25.8%) | 5.1% / 15.0% | +$214.23 | +$345.99 |
| QYLD trend200 | 8821 | +$0.67 | 41 | 61% | $31.12 (20.7%) | 0.1% / 9.2% | +$121.22 | +$184.46 |
| JEPI hold (from 2020-05) | 8822 | +$54.58 | 1 | 96% | $29.35 (14.6%) | 13.9% / 11.3% | +$57.86 | +$39.97 |
| JEPQ hold (from 2022-05) | 8823 | −$11.16 | 1 | 93% | $24.70 (17.6%) | — (7 months) | −$5.54 | −$14.05 |
| SPYI hold (from 2022-08) | 8824 | +$0.95 | 1 | 92% | $13.83 (9.7%) | — (3 months) | +$3.44 | −$3.27 |

Selection receipt `data/research/option-income/selection.json`, SHA-256
`8ce313b8236c50d9753aa74d625d13d2f0b46b61d5dee69ac7b93db44bf6db2f`.
It binds the source, the code dependencies and all seven training results.

- **Selected: XYLD hold**, trial 8818, version
  `4b933bbe58ed4e86c30a86ae1601ba2df68d0dda73672fdc36f06523f64540a7`. It runs
  exactly once on 2022-12-05 to 2026-09-30.
- **Data-sensitive (pre-declared flag):** XYLD beat QYLD hold by $5.96. That is
  less than 3.5% of QYLD's training ending equity ($7.65), and Yahoo's missing
  QYLD distributions are worth about $5. With complete QYLD data the two are
  roughly tied. Either way, the holdout tests one fund, not both.
- **Already visible in training:** XYLD returned about half of what SPY did at
  the same exposure, at only slightly lower volatility.
  - In the 2020 crash XYLD fell 32.4%, against SPY's 33.7%.
  - In the 2022 bear market it fell 17.1%, against 24.5%.
  - The 200-day filter cut drawdowns but gave up nearly all the return.

No final has run at this freeze.

## Completed final disposition — 2026-10-15

Selection commit `387851d` came before the final. XYLD hold final, trial
**8825**: **+$75.24** after costs, complete and flat. The `option_income_etf`
holdout family is now used. No other fund or variant will run on the holdout.
PRD §4 pass, but SPY at equal exposure beat it in both partitions. Queued
`ready-for-live` for the owner's decision (`tradingbot-s4s`); the agent
recommends against funding it. Details: [results](52-option-income-results.md).
