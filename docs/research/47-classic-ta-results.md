# Classic TA batch — results (`tradingbot-ob1`)

2026-10-04, DarkMeadow. Research only; actual capital $0. Frozen rules and risk review: [plan](47-classic-ta-plan.md).

## Scope and evidence

Fixed SPY/QQQ/AAPL/MSFT panel; five executable daily rules and three explicit source/specification dispositions. This is a bounded panel, not a sweep of all 40 Jev symbols. Each replay uses its own $140 virtual slot, 10 bp per side plus dated fees, total-return equivalent prices, settled cash, next-open execution and the unchanged risk vetoes. No real orders, model calls or paper/live promotion.

Prices span 2016-01-01 through 2026-10-01 exclusive. The locked 30% starts **2023-07-11 04:48 UTC**. Every partition starts flat with its own signal warmup. Only the highest positive, complete training result per rule receives one final; neither another ticker nor a second cost case reuses that family holdout.

| Symbol | Primary sessions | Accepted independent comparison | Agreement | Disposition |
|---|---:|---|---:|---|
| SPY | 2,701 | Nasdaq close × Alpaca all/split dividend factor | 2,508 / 2,511 (99.88053%) | Pass; first paired return 2016-10-04, 189 earlier unpaired returns retained |
| QQQ | 2,701 | Alpaca all-adjusted | 2,694 / 2,700 (99.77778%) | Pass |
| AAPL | 2,701 | Alpaca all-adjusted | 2,665 / 2,700 (98.70370%) | DATA_FAIL; below 99%; no outcomes |
| MSFT | 2,701 | Alpaca all-adjusted | 2,681 / 2,700 (99.29630%) | Pass |

SPY direct Alpaca agreement was only 93.59259%; that failed comparison is retained. Stooq returned no price CSV for SPY/AAPL. The independent SPY route does not reuse Yahoo prices or adjustment factors. Every disagreement, unpaired date, request and raw-file hash is retained in the source archive. These checks test close returns; they do not independently certify every daily high/low or opening print.

## Training: all admitted outcomes

Drawdown is marked **USD / % of peak / % of initial $140**. Net includes execution costs and fees. The p-value is descriptive, selection-unadjusted, using the fixed-seed three-month block bootstrap; null means fewer than 30 exit-month clusters/months or zero variation. These are not new promotion thresholds.

| Rule | Symbol | Trial | Round trips | Net USD | Max drawdown (USD / peak / initial) | p-value |
|---|---|---:|---:|---:|---|---|
| bollinger | SPY | 6366 | 0 | 0.00 | 0.00 / 0.00% / 0.00% | null (0 exit months) |
| bollinger | QQQ | 6367 | 0 | 0.00 | 0.00 / 0.00% / 0.00% | null (0 exit months) |
| bollinger | MSFT | 6369 | 0 | 0.00 | 0.00 / 0.00% / 0.00% | null (0 exit months) |
| rsi | SPY | 6370 | 15 | 1.64 | 21.11 / 13.95% / 15.08% | null (9 exit months) |
| rsi | QQQ | 6371 | 14 | 16.25 | 16.04 / 9.78% / 11.46% | null (12 exit months) |
| rsi | MSFT | 6373 | 7 | 7.67 | 8.68 / 5.79% / 6.20% | null (5 exit months) |
| sar | SPY | 6374 | 118 | 22.91 | 49.06 / 23.85% / 35.04% | 0.2678 |
| sar | QQQ | 6375 | 116 | 61.56 | 58.44 / 24.23% / 41.75% | 0.0962 |
| sar | MSFT | 6377 | 124 | -25.50 | 75.03 / 43.76% / 53.60% | 0.6812 |
| heikin_ashi | SPY | 6378 | 95 | 12.16 | 47.38 / 30.21% / 33.84% | 0.3956 |
| heikin_ashi | QQQ | 6379 | 93 | 50.47 | 34.44 / 19.91% / 24.60% | 0.0336 |
| heikin_ashi | MSFT | 6381 | 99 | 108.73 | 35.22 / 15.84% / 25.16% | 0.0002 |
| awesome | SPY | 6382 | 30 | 55.22 | 40.35 / 18.60% / 28.82% | null (29 exit months) |
| awesome | QQQ | 6383 | 37 | 100.44 | 55.15 / 20.59% / 39.39% | 0.0591 |
| awesome | MSFT | 6385 | 42 | 82.22 | 66.25 / 25.78% / 47.32% | 0.1225 |

All completed training configurations finished flat with zero rejected orders and no risk halts.

### Training regime breakdown

Marked net USD by calendar regime (including unrealized marks at boundaries). The 2023 column ends at the training cutoff; this is not a holdout result.

| Rule | Symbol | 2016–2019 | 2020–2021 | 2022 | 2023 training |
|---|---|---:|---:|---:|---:|
| bollinger | SPY | 0.00 | 0.00 | 0.00 | 0.00 |
| bollinger | QQQ | 0.00 | 0.00 | 0.00 | 0.00 |
| bollinger | MSFT | 0.00 | 0.00 | 0.00 | 0.00 |
| rsi | SPY | 6.48 | -10.90 | 6.07 | 0.00 |
| rsi | QQQ | 7.59 | 2.51 | 6.15 | 0.00 |
| rsi | MSFT | 7.91 | 0.00 | -0.25 | 0.00 |
| sar | SPY | 27.34 | 34.40 | -36.96 | -1.88 |
| sar | QQQ | 31.17 | 58.07 | -45.58 | 17.91 |
| sar | MSFT | -9.38 | 27.58 | -55.08 | 11.37 |
| heikin_ashi | SPY | 10.96 | -12.85 | 9.62 | 4.42 |
| heikin_ashi | QQQ | 29.25 | 2.30 | 7.82 | 11.11 |
| heikin_ashi | MSFT | 68.91 | 25.93 | 8.14 | 5.74 |
| awesome | SPY | 34.63 | 34.24 | -27.36 | 13.71 |
| awesome | QQQ | 56.90 | 62.89 | -42.94 | 23.60 |
| awesome | MSFT | 66.18 | 35.65 | -41.68 | 22.07 |

### Training costs, exposure and passive diagnostic

Buy-and-hold is the same-partition adjusted-close return at full exposure, before costs. It is a diagnostic, not another selectable strategy; the capped active slot has different exposure. Positive active net does not establish alpha over buy-and-hold.

| Rule | Symbol | Fees USD | Adverse cost USD | Turnover USD | Mean exposure | Buy/hold return |
|---|---|---:|---:|---:|---:|---:|
| bollinger | SPY | 0.00 | 0.00 | 0.00 | 0.00% | 149.93% |
| bollinger | QQQ | 0.00 | 0.00 | 0.00 | 0.00% | 254.38% |
| bollinger | MSFT | 0.00 | 0.00 | 0.00 | 0.00% | 578.57% |
| rsi | SPY | 0.60 | 4.15 | 4066.94 | 1.55% | 149.93% |
| rsi | QQQ | 0.56 | 3.98 | 3869.27 | 1.14% | 254.38% |
| rsi | MSFT | 0.28 | 1.97 | 1921.17 | 0.50% | 578.57% |
| sar | SPY | 4.72 | 32.09 | 31590.93 | 52.63% | 149.93% |
| sar | QQQ | 4.64 | 30.57 | 29785.94 | 46.55% | 254.38% |
| sar | MSFT | 4.96 | 29.51 | 28240.03 | 56.63% | 578.57% |
| heikin_ashi | SPY | 4.45 | 14.72 | 14494.29 | 16.76% | 149.93% |
| heikin_ashi | QQQ | 4.50 | 16.42 | 16028.29 | 16.82% | 254.38% |
| heikin_ashi | MSFT | 4.69 | 17.00 | 16253.10 | 14.76% | 578.57% |
| awesome | SPY | 1.20 | 8.55 | 8428.38 | 58.03% | 149.93% |
| awesome | QQQ | 1.48 | 10.70 | 10441.44 | 52.70% | 254.38% |
| awesome | MSFT | 1.68 | 11.29 | 10859.32 | 50.51% | 578.57% |

## Unattempted configurations

| Rule / symbols | Trial IDs | Disposition |
|---|---|---|
| bollinger / AAPL | 6368 | DATA_FAIL: Missing/contradictory adjusted daily prices; see frozen cross-check. |
| rsi / AAPL | 6372 | DATA_FAIL: Missing/contradictory adjusted daily prices; see frozen cross-check. |
| sar / AAPL | 6376 | DATA_FAIL: Missing/contradictory adjusted daily prices; see frozen cross-check. |
| heikin_ashi / AAPL | 6380 | DATA_FAIL: Missing/contradictory adjusted daily prices; see frozen cross-check. |
| awesome / AAPL | 6384 | DATA_FAIL: Missing/contradictory adjusted daily prices; see frozen cross-check. |
| macd / SPY, QQQ, AAPL, MSFT | 6386, 6387, 6388, 6389 | SPEC_BLOCKED: Upstream interactive SMA periods have no default. |
| shooting_star / SPY, QQQ, AAPL, MSFT | 6390, 6391, 6392, 6393 | NO_LONG_RULE: Only short-entry/cover; whole-sample and future-bar dependencies. No invented long rule. |
| dual_thrust / SPY, QQQ, AAPL, MSFT | 6394, 6395, 6396, 6397 | DATA_FAIL: Only 1 archived IEX session(s); five prior sessions plus replay required. |

MACD requires interactive periods in the pinned source, so there are no numeric defaults to test. Shooting Star only opens shorts and covers them; its whole-sample mean and next-bar references are also unsuitable for contemporaneous decisions. A long inversion was not invented. IEX has only the 2026-10-02 session per symbol as of the frozen cutoff, insufficient for Dual Thrust’s five prior sessions. No strategy P&L, drawdown or p-value is claimed for these unattempted configurations.

## Frozen selections and final holdouts

| Rule | Selected symbol | Training trial | Training net USD | Final trial | Final net USD | Round trips | Max drawdown (USD / peak / initial) | p-value |
|---|---|---:|---:|---:|---:|---:|---|---|
| awesome | QQQ | 6383 | 100.44 | 6398 | 64.80 | 17 | 23.21 / 13.00% / 16.58% | null (14 exit months) |
| bollinger | None | — | — | Not run | — | — | — | — |
| heikin_ashi | MSFT | 6381 | 108.73 | 6399 | -2.75 | 36 | 26.39 / 17.42% / 18.85% | null (27 exit months) |
| rsi | QQQ | 6371 | 16.25 | 6400 | 19.95 | 4 | 7.43 / 4.91% / 5.31% | null (4 exit months) |
| sar | QQQ | 6375 | 61.56 | 6401 | 3.09 | 57 | 36.92 / 24.34% / 26.37% | 0.4465 |

Finals cover only the 2023–2026 regime. They are not evidence across multiple unseen market regimes; training regime results remain visible above.

| Rule | Final fees USD | Adverse cost USD | Turnover USD | Mean exposure | Final buy/hold return | Cash/target skips | Ending holdings |
|---|---:|---:|---:|---:|---:|---:|---|
| awesome | 0.68 | 4.53 | 4485.26 | 59.45% | 104.65% | 0 | Flat |
| heikin_ashi | 1.84 | 6.87 | 6793.00 | 25.57% | 58.22% | 0 | Flat |
| rsi | 0.16 | 1.12 | 1102.56 | 0.82% | 104.65% | 1 | Flat |
| sar | 2.28 | 15.04 | 14905.56 | 56.89% | 104.65% | 8 | Flat |

## Decision and limits

Positive training-and-final candidates: awesome on QQQ, rsi on QQQ, sar on QQQ. These can be considered as **candidate base rules for a separately preregistered J1 study**. Daily signals cannot be relabelled as validated 15-minute intraday rules; J1’s prospective 7-day/30-trade AI paper requirement still applies.

Heikin-Ashi MSFT v1 fails the positive-after-costs holdout criterion. Its training winner is not replaced by another symbol. RSI's positive final has only four round trips; Awesome has 17, and SAR's descriptive p-value is 0.4465. None establishes a statistically reliable edge.

No paper/live promotion occurs. The daily rules share equity exposure, have regime and drawdown weaknesses, and do not demonstrate an independent structural edge. Selected QQQ SAR loses materially in 2022 and its training peak-to-trough loss exceeds $56 (40% of initial capital); the shared kill remains a loss-from-initial-allocation veto, not a new trailing stop. Short samples with null luck estimates remain visible. Current survivors and reused historical assets introduce selection/familiarity limitations. Opening fills, slippage, fees and corporate actions must be checked prospectively before deployment.

Bollinger’s exact absolute defaults produced zero trades. MACD, Shooting Star, AAPL price disagreement and insufficient Dual Thrust history are resolved as documented research limitations, not fabricated backtest results. No holdout was used for rule redesign or a second winner.

## Reproducibility and validation

- Preregistration: `ed47752`; tested implementation and source admission: `8b49eab`.
- Selection was committed and pushed as `9d8ab07` before finals 6398–6401. Read-only verification matched all **36** ledger trials, training artifact hashes, final versions, net/trade counts and exactly one family holdout receipt per selected rule. All finals finished flat with zero rejected orders and no risk halts; Bollinger has no final receipt. Verification: `data/research/classic-ta/verification.json`, SHA-256 `d5cde8832500a3738561491f47d84a8f600365bf6e2b65dff9939179f4afe5d5`.
- Source: `data/research/classic-ta/source.json`, SHA-256 `0c87c2622ff9399067c38a744302fabd7c886a24982d5a1f0f9d423d6dddc9a8`.
- Training selection: `data/research/classic-ta/selection.json`, SHA-256 `0a37b0081f7ef69b2dc18be5d9f12de30f688d38230a82033b61f381b661f50b`. It contains every training trial, complete diagnostics, executable dependency hashes and each training artifact hash.
- Per-run evidence: `data/research/classic-ta/train-<rule>-<symbol>.json` and `final-<rule>.json`; full marked curves, years/regimes, trades/fill IDs, costs, cash skips, ending holdings and benchmark diagnostics. Prices and detailed disagreement logs remain local archived evidence; the database trials ledger is authoritative.
- **30 checks passed**: 17 classic-TA checks plus shared equity-runtime and durable holdout tests. Tests use synthetic prices; prefix causality, initialization/defaults, cash, next-open execution, costs, terminal liquidation and repeated-final refusal are covered. An early fixture refusal was explicitly annotated as synthetic; no real final was consumed by tests.
- No risk limits, live keys, accounts, venues, capital, deployed paper strategies or model spending changed.
- Final awesome artifact SHA-256: `384704b970df195d9d72446e91a11828c23040e6f10c164ee8a015ef97b0e6d6`; trial 6398; frozen strategy version `3b98ab4f853b5b1717621683ad842adfdc612456cff552cbed9e21438d694cda`.
- Final heikin_ashi artifact SHA-256: `f20c2434052fb49427521de780e9df064c7f0f7f5e111f4fc0b0b823155c3394`; trial 6399; frozen strategy version `7844f44e69b3e2e9fd32fb4896456775b911b8e8c21cd1f2728e460e948add44`.
- Final rsi artifact SHA-256: `c073f5c0f0b0d8c5d56f3e8957b31a82e4aa21eb7fade6276b1a2bdb2e0135db`; trial 6400; frozen strategy version `1d295b4a0ab7f134b1d73306166d45b91ad7cb1ff337b6f6eafea8821968dbc6`.
- Final sar artifact SHA-256: `d9c1c672618849b25f5f462184c025d7fca1adc1bc7ea7a1d4d809aebcb78b11`; trial 6401; frozen strategy version `70d7d07936d994c0462bdab974caff4c59fe0fcb37133658821281e76bad7e4e`.
