# Batch 2026-10-09: IBS mean reversion, Gotobi yen days, "Claude funnel" posts

Sources: [Wealth-Lab IBS article](https://wealth-lab.com/blog/build-a-profitable-mean-reversion-strategy-using-the-ibs-indicator), plus screenshots of @kieran__duff posts ([1](submissions/2026-10-09-kieran-duff-funnel-1.png), [2](submissions/2026-10-09-kieran-duff-funnel-2.png), [3](submissions/2026-10-09-kieran-duff-gotobi.png)). A Firebase "agentic barista" screenshot came with them; it isn't trading-related and was skipped.

## 1. IBS (Internal Bar Strength) mean reversion on QQQ: **Pursue**
- **Rule:** IBS = (close − low) / (high − low). Buy at the next open when IBS crosses below 0.10. Sell at the next open when IBS crosses above 0.90. 100% of the slot, QQQ daily.
- **Claimed:** about 10 years, 164 trades, 74% win rate, 0.9% average per trade, 15% a year, 36% exposure, drawdowns "rarely over 6–7%". Costs and out-of-sample results aren't reported.
- **Rubric:**

| Check | Result |
|---|---|
| Rule | Exact |
| Reason | Documented short-term mean reversion in index ETFs (e.g. Pagonidis 2013, and widely replicated). It may have decayed. |
| Tradeable | Long/flat, free daily data, cash account. Trades are days apart, so they fit T+1. |
| Provable | About 16 trades a year means about 50 in a 30% holdout, which is enough for a rough read. |
| Blow-up | Gap risk while held, crash regimes (2008, 2020, 2022), and decay of a well-known effect. |

- **Bead:** pre-registered backtest on QQQ and SPY with the exact thresholds, next-open fills, costs and the 70/30 holdout. Report drawdown, regimes, and performance against buy-and-hold at the same exposure. No threshold tuning.

## 2. Gotobi days (yen pairs): **Pursue as research. Trading parked.**
- **Rule (from the hint plus the literature):** on Japanese settlement days (dates ending in 5 or 0, plus month-end, moved earlier for weekends and holidays), importers buy USD at the 9:55 JST Tokyo fix. USD/JPY tends to rise into the fix and fade after it.
- **Evidence:** documented structural order flow (e.g. Ito & Yamada, on the Tokyo-fix "gotobi" anomaly). A **forced-flow edge**, the kind the PRD likes best.
- **Tradeable?** **Not on Alpaca.** It happens around 7:00–10:00 JST, which is the US evening when FXY (the yen ETF) is closed, and Alpaca has no FX. It needs spot FX or CME yen futures (the IBKR candidate, unfunded), so trading is parked until that venue exists.
- **Bead (research only):** free hourly FX data (e.g. Dukascopy) for USD/JPY and EUR/JPY, about 10 years. Test long from the Tokyo open to the 9:55 fix on gotobi days against non-gotobi days, with realistic spreads and the 70/30 holdout. If it holds up, it's the first concrete reason to fund the futures/FX venue.
- **Outcome (2026-10-09, `z1t`): FAIL.** The pre-fix drift was real in 2016–2022: +5.4 bp gross, long 03:00→09:55 JST on gotobi days. In the 2023–2026 holdout it fell to +0.24 bp gross (−2.76 bp net, p 0.95). That is no case for a venue. See [results](../research/51-gotobi-results.md).

## 3. "Automated Claude funnel" strategies (NI225, NDX, XAUUSD, SP500, GBPJPY): **Reject**
- No rule is disclosed, only MT5-style equity curves.
- A "funnel" that generates many strategies and posts the winners is selection bias by construction. Without the trial count, the curves aren't evidence.
- The only concrete lead (Gotobi) is item 2.
