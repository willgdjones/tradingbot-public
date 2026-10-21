# je-suis-tm/quant-trading ("17 strategies for free")

Source: [submissions/2026-10-02-je-suis-tm-quant-trading.jpg](submissions/2026-10-02-je-suis-tm-quant-trading.jpg) (post by @RuujSs). Repo: https://github.com/je-suis-tm/quant-trading. Apache-2.0, about 10.8k stars, mostly 5–7 years old.

## What it is
Educational Python backtests of classic technical-analysis rules:
- Indicators and patterns: Bollinger Bands, MACD, RSI, Parabolic SAR, Heikin-Ashi, Awesome Oscillator, Shooting Star.
- Intraday breakouts: Dual Thrust, London Breakout (FX).
- Pair trading.
- Options straddle.
- A VIX calculator.
- Monte Carlo (an educational demonstration that it doesn't forecast).
- Macro/commodity "projects": Oil Money, Ore Money, Smart Farmers.

The backtests are teaching examples, mostly in-sample, with few or no costs and no holdout.

## Rubric
| # | Check | Result |
|---|---|---|
| 1 | Testable rule? | **Yes.** Each file is a precise rule. |
| 2 | Plausible reason it works? | Weak. These are classic trend and mean-reversion heuristics. The literature (Sullivan, Timmermann & White 1999; Bajgrowicz & Scaillet 2012) finds most technical rules fail once data-snooping and costs are accounted for. |
| 3 | Tradeable here? | Mostly, as **long/flat on ETFs and mega-caps** with free data. Not tradeable: pair trading (no shorting in a cash account), London Breakout (FX), and options straddles (only 2024+ indicative data). |
| 5 | Provable? | Yes. Cheap to pre-register and run through our backtester with costs and the 70/30 holdout. |
| 6 | Cost | Low. The rules are simple, and our engine does the hard parts. |

## Verdict: **Salvage → one pre-registered batch**
Port 8 rules as long/flat strategies on the existing ETF/mega-cap universe: Bollinger, MACD, RSI, Parabolic SAR, Heikin-Ashi, Awesome Oscillator, Shooting Star, and Dual Thrust (intraday, on our IEX data).
- Use **the repo's default parameters only**, with no tuning, so the holdout stays honest.
- Costs on, 70/30 holdout, every variant in the trials ledger.
- Expect most to fail. Survivors can also be tried as **base rules for the J1 Jev gate**.
- The Apache-2.0 license allows reuse with attribution.

Not ported: pair trading (needs shorting), London Breakout, the straddle, the VIX calculator, Monte Carlo, and the FX/commodity "money" projects.
