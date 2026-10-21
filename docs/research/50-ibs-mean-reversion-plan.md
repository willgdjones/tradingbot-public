# IBS mean reversion on QQQ/SPY: pre-registration (`tradingbot-kyn`)

2026-10-09, RainyReef. Research only: $140 virtual slot per run, $0 actual.
Source: [intake 2026-10-09](../strategy-intake/2026-10-09-ibs-gotobi-funnel-batch.md),
from the [Wealth-Lab article](https://wealth-lab.com/blog/build-a-profitable-mean-reversion-strategy-using-the-ibs-indicator).

## Rule, exactly as published (no tuning)

The article states: QQQ, daily, "Buy when IBS crosses below 10" and sell when it
crosses above 90, both "at the open of the next trading day" as market orders.
Indicator period 1, 100% position size, no stop or time exit, 10-year test.
Commissions, slippage and out-of-sample results are not stated. Claimed: 164
trades, 74% winners, +0.9% per trade, 15% a year, 36% exposure, drawdowns
"rarely" over 6-7%.

- IBS = (close − low) / (high − low) of the completed daily bar (0.10 = 10).
- **Entry:** while flat, IBS crosses under 0.10 (previous ≥ 0.10, current < 0.10,
  WealthLab `CrossesUnder`). Buy at the next regular open.
- **Exit:** while long, IBS crosses over 0.90 (previous ≤ 0.90, current > 0.90,
  `CrossesOver`). Sell at the next regular open.
- A zero-range bar has no IBS and cannot cross. The first bar of each partition
  has no prior bar, so it cannot signal.
- Code: `src/tradingbot/strategy/ibs.py` (signal and strategy, shared interface)
  and `src/tradingbot/research/ibs_mean_reversion.py` (source, train, final).

## Data, execution and holdout

- **Symbols:** QQQ is the primary test. SPY is the replication. Fixed before
  any outcome; no other tickers.
- **Window:** 2006-01-01 to 2026-10-01 (exclusive), so 2008 is in sample.
  `HoldoutSplit` 70/30 by elapsed time: training ends and the holdout starts at
  **2020-07-10T14:24:00Z**. Each partition starts flat, with in-partition warmup.
- **Prices** (research data standard): Yahoo split- and dividend-adjusted OHLC
  (high and low scaled by the same adj-close/close factor as open and close;
  IBS is scale-free). Second source: Nasdaq close × Alpaca all/split dividend
  factor, falling back to Alpaca all-adjusted closes. Accept at ≥99% of paired
  daily returns within 5 bp. Pairs exist from 2016; 2006-2015 is single-source
  and disclosed, not resliced. Every session must match the archived exchange
  calendar. A symbol that fails is recorded as DATA_FAIL with no outcomes.
- **Execution:** existing total-return-equivalent replay, ledger, unchanged
  risk vetoes and dated `EquityFeeBook`. Target min(95% of equity, $140), 5%
  cash reserve, $0.01 fee buffer, settled cash only (conservative cash-release
  calendar), quantity floored to 1e-9, $1 minimum. **10 bp per side** adverse,
  cent-rounded, plus fees. One cost scenario. A delayed entry retries at later
  opens while the signal is still long. The partition's last open only exits.
- **No selection between symbols.** Each symbol is its own strategy version.
  Each symbol whose training run is complete, flat and net-positive after costs
  gets exactly **one** final on the holdout. A failed or non-positive training
  run gets no final. No sibling ticker, threshold, cost case or renamed version
  can reopen a final.

## What gets reported

Net and gross after costs, fees, adverse cost, trades, win rate, mean % per
trade, mean sessions held, exposure, turnover, delayed entries, rejections,
marked max drawdown, calendar years and fixed regimes (2006-2009, 2010-2019,
2020-2021, 2022, 2023-2026), and the monthly block-bootstrap luck p-value
(only with ≥30 months and ≥30 exit-month clusters). Benchmarks (not
selectable): cash, buy-and-hold, and **buy-and-hold at equal exposure** (the
strategy's average exposure fraction held constantly, rest in cash, no costs).
Side by side with the published claim.

**Pass (PRD §4):** profitable after all costs in training **and** on the single
holdout run, with complete execution. QQQ decides; SPY corroborates. Losing
to equal-exposure buy-and-hold does not fail PRD §4, but it is reported and
weighs on whether a paper runner is worth a slot. Even a pass prepares an Alpaca
paper runner only **after the Oct 15 execution-code freeze**.

## What could blow up this account?

- **Edge/evidence:** short-term index mean reversion is a behavioural/liquidity
  effect (PRD §3 allows it), not a forced flow. It is widely published (IBS
  since about 2013), so decay is the main risk. The 2016-2026 Wealth-Lab figures
  are in-sample and cost-free. This prior is known, so the holdout is not
  independent of public knowledge.
- **Tail/gap:** the strategy buys after weak closes, i.e. into sell-offs.
  An overnight gap or a crash leg (2008, March 2020, 2022) while long can take a
  large bite of the $140 slot. There is no stop, so a long can sit through a
  falling market until a strong close. The −40% strategy kill is the backstop.
  The $25 cap is a prediction-market rule and does not apply.
- **Adverse selection:** market-on-open taker fills at the open auction; the
  10 bp per side is a scenario, not a measured fill. Opening prints after news
  can be worse.
- **Venue:** Alpaca only, a Mac, no dead-man switch (PRD §9 accepted). Holding
  overnight means an outage cannot strand an intraday order, but it can delay
  an exit by a day. Any future key trades only, never withdraws.
- **Untrusted inputs:** price data only; nothing is read as instructions.
- **Reproducibility:** deterministic Decimal rule; source bytes and code hashes
  are pinned before outcomes; tests check prefix causality and next-open fills.
- **Correlation:** long QQQ/SPY after down days loses at the same time as every
  long-equity sleeve (C-family, J1-J4 longs), concentrating the −$50 daily halt.
- **Limits:** PRD §6 limits unchanged. No capital, venue, key or order here.

**Decision at this stage:** idea → backtest only. No paper or live claim.

## Source frozen before outcomes — 2026-10-09

Source `data/research/ibs-mean-reversion/source.json`, SHA-256
`76ecbfbb561e42855f0d5cd15b436b650bc2dafc9b94ccd3da0c25806e4640fa`
(16 pinned input files). Both symbols have all 5,218 calendar sessions
(2006-01-03 to 2026-09-30), none missing or extra, and no zero-range bar.

| Symbol | Nasdaq × Alpaca agreement | Paired days | Disagreeing | Single-source |
|---|---:|---:|---:|---|
| QQQ | 99.920% | 2,506 (from 2016-10-11) | 2 | 2006-01-03 to 2016-10-10 |
| SPY | 99.880% | 2,506 (from 2016-10-11) | 3 | 2006-01-03 to 2016-10-10 |

Pre-outcome fix: OHLC order is validated on the exact raw Yahoo bar. The
adjusted high/low are clamped to the adjusted open/close only when Decimal
rounding of `high × adj_close/close` misses Yahoo's own adj_close (first seen
on QQQ 2016-03-01, a close at the high). The clamp refuses anything larger than
1e-20 of price. No price was patched.

## Training frozen before the holdout — 2026-10-09

Training trials **8802** (QQQ) and **8803** (SPY), 2006-01-03 to the
2020-07-10 holdout start, 10 bp per side plus fees. Both finished flat, with no
rejected orders and no halts. Neither had a parameter, ticker or cost case added.

| Symbol | Trial | Net after costs | Trades | Win rate | Max marked DD | Equal-exposure B&H | Frozen version |
|---|---:|---:|---:|---:|---:|---:|---|
| QQQ | 8802 | **+$142.18** | 223 | 69.1% | $44.70 (26.5%) | +$99.54 | `679b87a0f8b31699…` |
| SPY | 8803 | **+$89.91** | 214 | 67.3% | $42.43 (24.3%) | +$54.04 | `8adcc03cde10ffd2…` |

Selection receipt `data/research/ibs-mean-reversion/selection.json`, SHA-256
`93a2dd70417e763095b6064025d6d09e1f2a1e00f33185e22e56b699ae31cb47`.
It binds the source, code dependencies, both training metrics and versions.
Both symbols were positive and complete, so each gets exactly one final on
2020-07-10 to 2026-10-01. No final has run at this freeze.

## Completed final disposition — 2026-10-09

Selection commit `1d2143d` came before the finals. QQQ final, trial **8804**:
**+$71.48** after costs, complete and flat. The SPY final, trial 8805, was
refused at admission before any holdout event was read (incident 2049). Both
symbols share the `ibs_mean_reversion` holdout family, which QQQ had already
used. The "one final per symbol" line above was wrong about the guard. SPY will
not be reopened. Details: [results](50-ibs-mean-reversion-results.md).
