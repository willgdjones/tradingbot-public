# Research 3: Non-sports structural edges (2026-09-29)

## Key facts
- **PDT rule:** removed. The SEC approved the change on 14 Apr 2026 and it took effect on 4 Jun 2026, but brokers have until 20 Oct 2027 to implement it (FINRA RN 26-10). Check Alpaca's status.
- **Micro E-mini futures:** about $2,300 overnight margin, which is not feasible with $1k.
- **Proof needs a backtest.** Around 700 or more independent trades are needed for a 2¢ edge, and live P&L on $100 over 60 days cannot supply that.

## Alive: prediction markets (US)
1. **Favourite–longshot bias, trading as a maker (Kalshi).** Supported by academic work (CEPR DP20631). Kalshi pays 3.75% APY on balances of $250 or more.
2. **Liquidity Incentive Program.**
   - **Kalshi:** scores resting orders every second and pays $1–$1,000 per market per day. It runs until 1 Jan 2027, is open to US users only, and excludes market-maker agreement holders. See help.kalshi.com/en/articles/13823851.
   - **Polymarket US:** runs its own incentive program and pays a 1.25% maker rebate.
3. **Kalshi INX/NASDAQ100 range contracts vs probabilities implied by SPX options** (Breeden–Litzenberger). There is little published evidence (a Stevens project; quantgalore/kalshi-trading). It settles daily.
4. **Weather settlement mechanics.** Settlement now uses Weather Company data from a specific station. Trade late in the day, once the high has already been recorded. Data is free (NOAA/METAR).
5. **Cross-venue Fed/econ gaps.** Mostly caused by differences in resolution rules. A Fed paper (FEDS 2026-010) finds that Kalshi FOMC prices beat futures. Events are rare.

## Alive: US equities
- **Turn of the month:** robust (Quantpedia).
- **Month-end pension rebalancing:** when equities are overweight, the next day returns about −17 bp (Harvey, Mazzoleni & Melone, NBER w33554).
- **End-of-day leveraged-ETF and gamma flows:** the LETF effect is weakening; the gamma effect persists (SSRN 3925725).
- **Post-earnings drift:** survives only in small caps.
- **Merger arbitrage, SPAC trust arbitrage and closed-end fund discounts:** alive but slow and small.

## Alive but blocked for US persons (Hyperliquid)
- **Equity-perp funding carry:** median funding is about 14% (CoinDesk, Aug 2026).
- **Token-unlock shorts:** Keyrock found about 90% of unlocks are followed by a price decline.
- **Post-listing fade:** the median new listing is down 21.5% after 30 days.

## Dead or not provable in 60 days
- **Dead:**
  - Overnight drift (NY Fed, Jul 2026)
  - Pre-FOMC drift
  - S&P inclusion (Greenwood & Sammon, JF 2025)
  - Large-cap PEAD
  - BTC funding carry (2.2% in 2026)
  - MEV / CEX–DEX arbitrage
  - Sum-to-100% arbitrage: 3 of 543 Kalshi events showed an edge, and all were negative after fees
  - Stablecoin depegs
  - Micro-futures carry at $1k
- **Not provable in 60 days:** short vol / 0DTE VRP, VIX ETPs, HLP.

## Guaranteed yield
- Kalshi: $25 bonus when you trade $10, plus 3.75% APY.
- Brokers run transfer-match promos (Robinhood 1–3% until 16 Oct; Moomoo 3%). Verify these are still current.
