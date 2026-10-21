# IBS mean reversion on QQQ/SPY: results (`tradingbot-kyn`)

2026-10-09, RainyReef. Pre-registration: [50-ibs-mean-reversion-plan.md](50-ibs-mean-reversion-plan.md).
Exact Wealth-Lab rule (IBS crosses under 0.10 → buy next open; crosses over 0.90
→ sell next open), $140 virtual slot, 10 bp per side plus fees, settled cash.
Artifacts: `data/research/ibs-mean-reversion/` (source, train, selection, final).

## Verdict

**QQQ passes PRD §4: profitable after costs in training (+$142.18) and on its
single holdout run (+$71.48).** It also beats buy-and-hold at equal exposure in
both partitions. Queued for an Alpaca paper runner **after the Oct 15
execution-code freeze**. SPY corroborates in training only (+$89.91). It has no
holdout result, because the family's one holdout run went to QQQ (see below).

## Results

| Run | Period | Trial | Net after costs | Trades | Win rate | Net %/trade | Exposure | Max marked DD | Equal-exposure B&H | Full B&H |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ train | 2006-01 → 2020-07 | 8802 | **+$142.18** | 223 | 69.1% | +0.44% | 24.1% | $44.70 (26.5%) | +$99.54 (DD 19.2%) | +$865.61 (DD 53.4%) |
| **QQQ holdout** | 2020-07 → 2026-09 | **8804** | **+$71.48** | **98** | 65.3% | +0.58% | 26.5% | $23.27 (12.5%) | +$51.41 (DD 12.5%) | +$266.42 (DD 35.1%) |
| SPY train | 2006-01 → 2020-07 | 8803 | +$89.91 | 214 | 67.3% | +0.37% | 22.8% | $42.43 (24.3%) | +$54.04 (DD 17.3%) | +$325.88 (DD 55.2%) |
| SPY holdout | — | 8805 | refused, no outcome | | | | | | | |

The buy-and-hold columns use adjusted closes with no costs; "equal exposure" means the
strategy's average exposure held constantly, with the rest in cash. All runs
finished flat, with no rejected orders and no risk halts.

**QQQ holdout detail.** Gross before fees +$75.40. Fees $3.92. The 10 bp adverse
fill cost was $26.43, about a quarter of the gross edge. Positions were held for
5.9 sessions on average. There were no delayed entries. Turnover was $26,085.
Ending equity was $211.48 on $140.
- **Luck:** one-sided t-test p = 0.017. The monthly block bootstrap gives
  p = 0.024 over 75 months and 61 exit-month clusters.
- **Training luck:** QQQ t-test p = 0.0012, bootstrap p = 0.0002. SPY t-test
  p = 0.039, bootstrap p = 0.008.
- **Multiple testing** (`backtest.overfitting`, dataset `ibs-mean-reversion:76ecbfbb…`):
  family N=2 (QQQ, SPY), PBO 0.33. QQQ training has a Sharpe of 0.82 a year,
  DSR(N) = 1.00 and DSR(L) = 0.85 against the ledger's Sharpe variance.
  DSR(L) < 0.95, but paper is still worth the time. The rule comes from a
  third party and was not tuned, there was no sweep beyond the two
  pre-registered tickers, and the single holdout run (98 trades) agrees with
  training.

### Regimes (marked P&L by exit date)

| Regime | QQQ train | QQQ holdout | SPY train |
|---|---:|---:|---:|
| 2006-2009 | +$24.11 (58 tr; 2008 −$23.76) | — | +$37.99 (62 tr; 2008 +$7.64) |
| 2010-2019 | +$105.44 (154 tr) | — | +$50.60 (141 tr) |
| 2020-2021 | +$12.63 (11 tr, to Jul 2020) | +$41.47 (26 tr) | +$1.32 (11 tr) |
| 2022 | — | **−$6.45** (20 tr; DD 12.5%) | — |
| 2023-2026 | — | +$36.46 (52 tr) | — |

- **QQQ holdout by year:** 2020 +$17.45, 2021 +$24.02, 2022 −$6.45, 2023 +$26.66,
  2024 −$4.39, 2025 +$21.11, 2026 (to Sep) −$6.92.
- **QQQ training by year:** losses only in 2008 (−$23.76). It was positive in every other
  year, but weak in 2012 (+$1.71) and 2015 (+$0.76).
- **SPY training:** losses in 2011 (−$5.09) and 2018 (−$10.16).

The worst marked drawdown is the 2008 crash leg: QQQ $44.70, 26.5% of the
slot. That stays inside the −40% kill ($56), but not by much.

### Against the published claim

| | Wealth-Lab (QQQ, ~10y, no costs stated) | Ours, QQQ, 10 bp/side + fees |
|---|---|---|
| Trades a year | ~16 | 15.4 (train), 15.8 (holdout) |
| Win rate | 74% | 69% / 65% |
| Mean per trade | +0.9% | +0.44% / +0.58% net (≈ +0.65% / +0.8% before costs) |
| Exposure | 36% | 24% / 26% |
| Drawdown | "rarely over 6-7%" | 26.5% (2008), 12.5% (2022) |

The edge is real but about half the size the article claims once costs are
paid. The article's drawdown figure is not credible for a long-only rule
across 2008, 2020 or 2022.

## SPY final refused (DB incident 2049)

The plan said each symbol gets its own final. The backtester's guard counts
one holdout run per **strategy family**, and QQQ and SPY share the reactor key
`ibs_mean_reversion`. QQQ ran first (trial 8804) and used the family's
holdout. SPY's final (trial 8805) was refused at admission, before any holdout
event was read: no curve and no fills. Incident 2049 (`holdout_family_reuse`)
was recorded.

The guard is right: a sibling ticker of the same rule should not get a second
look at the holdout. The plan was wrong. The SPY holdout will **not** be
reopened under a renamed family. No money, cohort or ledger is affected.

## Promotion checklist (idea → backtest done; backtest → paper queued)

1. **Edge:** short-term index mean reversion (behavioural/liquidity, PRD §3),
   not a forced flow. The rule is single and exact, with entry and exit. It is
   profitable after all fees in training and on the holdout.
2. **Statistics:** trade counts, p-values, PBO/DSR, drawdown and regimes are
   above. The edge survives 2008 (SPY) and 2020-2021, and is mildly negative
   in 2022 and 2024. It is not a one-regime result.
3. **Fidelity:** the same `IBSReversion` strategy class is meant to run in paper.
   The paper runner must use real Alpaca opening fills, so the 10 bp scenario
   gets measured rather than assumed.
4. **What could blow up this account:** see the plan's section. Restated
   briefly:
   - **Gaps:** the rule buys weak closes and has no stop. In 2008 it lost 26.5%
     of the slot, and a worse crash could reach the −40% kill.
   - **Fill cost:** opening-auction cost is about a quarter of the gross edge,
     so fill quality decides the result.
   - **Correlation:** it is long QQQ alongside every other long-equity sleeve,
     concentrating the −$50 daily halt.
   - **Decay:** this is a widely published effect.
5. **Limits:** PRD §6 unchanged. No capital, venue, key or order.
6. **Decision:** QQQ v1 (`679b87a0f8b31699…`) → **paper**, $140 slot, built
   after 2026-10-15. This is a backtested rule, not an AI-decided one, so the
   7-day/30-trade forward rule does not apply. Paper must show that Alpaca
   opening fills, fees and settlement match the backtest (checklist §3), and
   then it queues as `ready-for-live`. At about 16 trades a year, expect only
   a few round trips a month. SPY: training-only evidence, no paper slot.

## Independent replication (`tradingbot-3xw`, 2026-10-13, ChartreuseLantern)

[`50-ibs-replication.py`](50-ibs-replication.py) re-implements the rule from the
plan text and the frozen source alone. It does not use `strategy/ibs.py`, the
backtester, the ledger or the risk engine. It is read-only: no trial, no
database, no new holdout decision.

| Run | Trades | Entry/exit times | Skipped entries | Net (ours / stored) |
|---|---:|---|---|---|
| QQQ train (8802) | 223 / 223 | identical | 2006-02-03, 2006-02-21 (both) | $142.18 / $142.18 |
| QQQ holdout (8804) | 98 / 98 | identical | none (both) | $71.48 / $71.48 |
| SPY train (8803) | 214 / 214 | identical | same 3 (both) | $89.92 / $89.91 |

Per-trade net differs by ≤ $0.003 because positions are sized from a slightly
different equity mark (about 0.03% in size). Fees match ($0.04 per round trip).
This confirms there is no look-ahead in the backtest: a signal on day D uses
D's completed bar and fills at D+1's open.

**High/low/close check.** The source audit compared only closes, but IBS also
needs the daily high and low. Signals from the frozen Yahoo OHLC, compared with
Alpaca daily bars:

| | Crosses identical | Entry crosses shared |
|---|---|---|
| QQQ, SIP 2016+ | 629 / 634 | 230 / 232 |
| QQQ, SIP 2022+ | 269 / 269 | 108 / 108 |
| SPY, SIP 2016+ | 577 / 611 | 216 / 226 |
| SPY, SIP 2022+ | 271 / 272 | 107 / 108 |
| QQQ, **IEX** 2020-09+ | 331 / 353 | 131 / 137 (+14 spurious) |

- **SPY:** the pre-2022 disagreements are Alpaca bad prints, not Yahoo errors.
  For example, Alpaca shows a 2016-03-11 high of 210.55 (the actual high was
  202.81) and a 2020-03-12 close of 255.24 (SPY closed at 248.11). SPY's
  training evidence stands.
- **For the paper runner (`tradingbot-v2i`):** compute IBS from **consolidated
  (SIP) daily bars**, which are free once they are more than 15 minutes old.
  Fetch the bar after about 16:20 ET or before the next open. Do not use the IEX
  feed or IEX recorder bars: IEX's high, low and close differ by more than 0.02
  IBS on 28% of days. Since 2020 that would have missed 6 of 137 entry signals
  and produced 14 that the backtest never saw.

**Fill-cost margin.** From the stored cost breakdown, the gross edge before fill
costs covers about **33 bp per side** (training) and **37 bp** (holdout) before
net reaches zero. The backtest assumes 10 bp. Paper should log realised fill
versus the official open per trade against that bar.

## Live on the $140 slot (owner override, `tradingbot-752`, 2026-10-14)

The owner skipped the paper stage for this one strategy ("I want to start
trading on real money now"; PRD §4 override). The §6 limits are unchanged.

- **Runner:** `src/tradingbot/live/ibs_qqq.py` (see `src/tradingbot/live/README.md`).
  Live trial **8815**, strategy `ibs-QQQ-live-v1`, version `679b87a0f8b31699…`.
  It starts flat, anchored on the 2026-10-14 bar (IBS 0.181). The first
  possible entry is the 2026-10-16 open.
- **Signal:** the unchanged `strategy.ibs.Signal` on Alpaca SIP daily bars,
  per the replication above.
- **Execution:** fractional marketable DAY limits from 09:30:30 ET, through
  `AlpacaLiveConnector` (cash account, §6 `RiskEngine`, kill switch). Sizing as
  planned.
- **Dry run until the owner adds `ALPACA_LIVE_KEY`/`ALPACA_LIVE_SECRET`:** it
  then initializes a $140 live book and trades without further action.
- **Fidelity is now measured with real money.** Every fill is logged against
  the official SIP open. Review it after the first round trips: the edge
  survives up to ~33 bp per side, and the backtest assumes 10.

**What could blow up this account, live-specific additions** (the plan's list
still applies):

- **No paper evidence:** opening fills, fee bookings and settlement have never
  been observed for this rule. The first trades are the fidelity test.
- **Kill mechanics:** at −$56 (−40%) the strategy is killed. The unchanged risk
  engine then refuses every order, including the exit. The runner raises an
  incident asking the owner to close QQQ in Alpaca.
- **Operations:** it runs on a laptop (PRD §9). A missed morning delays an exit
  by a day. If the keys stop resolving after going live, the runner raises an
  incident rather than trading the virtual book.
- **Concentration:** the $140 book holds one long QQQ position overnight, for
  about 6 sessions per trade.
