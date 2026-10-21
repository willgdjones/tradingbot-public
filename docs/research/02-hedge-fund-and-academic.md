# Research 2: Hedge-fund publications and academic evidence (2026-09-29)

## Firms
**What the firms published:**
- **AQR and Man AHL:** trend following works over long horizons, with multi-year drawdowns. Small design choices change results a lot.
- **Robeco:** the low-vol long leg is enough on its own; the short leg adds little.
- **Research Affiliates:** keep factor timing simple.
- **SIG, Jump and Jane Street:** they now make markets on Kalshi and Polymarket. The liquid markets belong to them. A retail edge can only exist in the long tail.

**What transfers to a small account:** trend following on a few assets, cost discipline, volatility targeting.

**What does not transfer:** equity factors, alternative-data ML, anything that needs short books.

## Prediction markets
- **Favourite–longshot bias on Kalshi.** Bürgi, Deng & Whelan 2026, SSRN 5502658, covering about 314k contracts:
  - Contracts priced under 10¢ lose more than 60%.
  - Contracts priced above 50¢ show a small positive return.
  - Takers lose about 32% and makers about 10%.
  - The bias may decay now that it is published.
- **Composition effects.** Yurchenko, SSRN 7364100, 376.8M fills: sports rose to 58.8% of volume, so condition any analysis on series and date.
- **CPI markets.** The longshot bias flips sign with the monetary regime (SSRN 7093759).
- **Polymarket.** Cardozo & Rivero-Wildemauwe, arXiv 2609.12878, 588M trades:
  - Buys under 10¢ lose 19.3¢ per $1.
  - Analysed at the event level, longshots actually gain.
  - There is no bias in sports.
- **Politics.** Political markets are underconfident, with prices pulled toward 50% (Le, arXiv 2602.19520).
- **Kalshi sports.** Prices drift in the final 10 minutes, and parlays are overpriced (Moshrefi, arXiv 2607.14430).
- **Liquidity provision.** Providing liquidity is really underwriting risk: providers end up holding directional exposure at settlement (Palumbo, SSRN 6325658).
- **Cross-venue arbitrage.** Gaps of 2–4% exist for multi-listed events (arXiv 2601.01706). Polymarket's negative-risk arbitrage totals only about $1.12M (arXiv 2608.00666). NBA in-game arbitrage windows last a median of 3.6 seconds.
- **Weather.** The market beats the NBM forecast by about 10% RMSE (Crosier, arXiv 2609.23969). Settlement moved to The Weather Company on 2026-08-14.

## Crypto
- **Funding carry** was negative in 2025 (arXiv 2510.14435).
- **Trend following** evidence is mixed: SSRN 5209907 is positive, SSRN 7405060 finds it has aged.
- **Polymarket 15-minute crypto latency arbitrage** has been killed by a dynamic fee of about 3.15%.

## LLM forecasting
- ForecastBench: superforecasters score a Brier of 0.081, the best LLM 0.101.
- No LLM beat the bookmakers at the 2026 World Cup.
- In PolyBench, 2 of 7 models were profitable.

## Methodology (for many strategies)
- **Trials ledger:** record the true number of strategies tried (N).
- **Deflated Sharpe Ratio:** require ≥ 0.95, and correct for skew. Binary payoffs are extremely skewed.
- **PBO via CSCV:** reject if above 0.2.
- **Significance:** require t > 3 for a new idea.
- **Sample size:** t ≈ edge·√n/σ. A 2¢ edge on 90¢ contracts needs about 700 or more independent events.
- **Faster proxy:** use closing-line value (CLV).
- **Splits:** walk forward by event date. Pre-register each strategy in git.
- **Expect decay:** a McLean–Pontiff style haircut of 50% or more after publication.
- **Paper fills:** a maker order counts as filled only when later trades go through its price.
- **Fees:**

| Venue | Fee |
|---|---|
| Kalshi, taker | 0.07·C·P(1−P) |
| Kalshi, maker (where charged) | 0.0175·C·P(1−P) |
| Polymarket US, taker | 0.0695·C·P(1−P) |
| Polymarket US, maker rebate | −0.0125 |

## Caution
Insider trading is documented on these venues. Avoid markets on company or government announcements.
