# Options "wheel" (weekly 0.15–0.25 delta puts on SPY/QQQ/mega-caps), @MFT_Get_Funded

Source: [submissions/2026-10-14-wheel-strategy-mft.md](submissions/2026-10-14-wheel-strategy-mft.md)

**Verdict: Park (capital-blocked).** The edge is real but modest (the variance risk premium). We can't trade it at $1k, and C14 already showed that cash-secured puts don't fit a $140 slot.

1. **Testable rule?** Mostly. Sell weekly cash-secured puts at delta 0.15–0.25 on liquid quality underlyings. If assigned, sell covered calls (the wheel). Exits, rolls and sizing are unspecified.
2. **Why it works:** the variance risk premium. Implied volatility exceeds realised volatility on average, so put sellers are paid for crash insurance. This is a documented risk premium, eligible under PRD §3.
   - The claimed **1.5–4% a month (18–48% a year)** is far above the long-run evidence. The CBOE PUT index returned roughly equity-like returns at lower volatility, not equity returns plus 20–40 points.
3. **Tradeable here?** **No.**
   - One cash-secured SPY put needs about $77k of collateral (strike × 100), and QQQ about $73k.
   - At a $140 slot only strikes ≤ $1.40 fit, which means junk underlyings and breaks the poster's own rule 1. C14 (`tradingbot-ddw`, docs/research/25-candidate-shortlist.md) found zero eligible contracts.
   - Options are also still research only.
4. **Evidence already exists:** the PUT/BXM index literature, and C14 (capital-infeasible).
5. **Provable?** Alpaca's indicative options history starts Feb 2024. That's one regime and too short for a tail-risk strategy, whose losses come in rare crashes (2008, 2020, 2022).
6. **Cost:** a medium build, reusing the options data harness (docs/research/10).
7. **What could blow up the account?** A gap down through the strike in a crash week, which loses many weeks of premium at once. Assignment then ties up all the capital in a falling stock. Selling insurance looks steady until it doesn't.

**Revisit when** capital is about $5k or more (a quality underlying around $25–50 fits one contract), or for SPY-sized contracts at about $75k. A put-write ETF (for example PUTW, or covered-call funds like JEPQ/QYLD) gives fractional exposure to the same premium today. But it is essentially buy-and-hold of a low-volatility equity proxy, like C04, so it was not queued.
