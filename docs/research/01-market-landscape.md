# Research 1: Market landscape and the Jev claims (2026-09-29)

## Jev / TypeSafe AI, jev-trader, AgenKit
- **Company:** TypeSafe AI is real. It raised $40M, led by DCVC, and the founder is Diogo Almeida.
- **What Jev does:** returns typed decisions with probabilities.
- **Pricing:** confirmed at $0.042 per million input tokens; output is free.
- **Latency and calibration claims:** these come only from the vendor. No independent benchmarks exist, and the model version cannot be pinned.
- **jev-trader (github.com/jarrodwatts/jev-trader):**
  - It is a dry-run demo with no reported P&L. Issue #1 is titled "It's losing money".
  - PR #2 measured the costs. Gas is about 0.0357 MON per block, roughly 428 MON per hour. That is about 1.8 bps of gas against about 0.6 bps earned from the spread, and the dry run was at −484% of bankroll before counting gas.
  - The prompt described the wrong strategy.
- **Best independent evidence (r4topunk/jev-trading-study):** a pre-registered 90-day paper study of 34,496 decisions.
  - Directional AUC was 0.475, worse than a coin flip.
  - Jev's outputs mostly track momentum over the previous 15–60 minutes.
  - Repeated calls on the same input vary by ±0.04.
- **Other projects:** a survey of more than 20 Jev trading projects found no P&L evidence.
- **AgenKit (agenkit.xyz):** an anonymous paid "quant team" kit promoted by @RohOnChain. Treat it as promotional.

## Evidence on AI/LLM trading
- **Alpha Arena S1:** 4 of 6 models lost money.
- **Bloomberg, May 2026:** 6 of 32 runs were profitable.
- **FINSABER / StockBench:** LLM strategies underperform buy-and-hold once test biases are controlled.
- **Prediction Arena, Jan–Mar 2026:** frontier models lost 16–31% on Kalshi.
- **Where LLMs do help:** parsing, classification, event matching and writing code. They are not a source of alpha.

## Venue access
**UK residents**
- Polymarket international is close-only.
- Kalshi is restricted.
- Hyperliquid is on the FCA warning list (May 2026). It is not geoblocked for the UK, but it blocks US persons.
- The FCA bans crypto derivatives for retail customers of UK-regulated firms.

**US residents**
- Kalshi and Polymarket US are open.
- Hyperliquid is blocked.

**Our position:** the owner has legitimate US access, so we use Kalshi, Polymarket US and Alpaca, and do not use Hyperliquid.

## Tooling
| Tool | Scale | Notes |
|---|---|---|
| Freqtrade | 55k stars | crypto |
| NautilusTrader | 29.5k stars | Rust core; Betfair, Polymarket and Hyperliquid adapters |
| Hummingbot | 20k stars | market making |
| Lean | 22k stars | |
| vectorbt | | |
| CCXT | | |
| Kalshi / Polymarket SDKs | | Polymarket's old py-clob-client is archived; use py-sdk / clob-client-v2 |

## Tax (UK)
- Crypto is taxed under CGT at 18/24% above the £3k allowance.
- The CARF regime is live from January 2026, so exchanges report customer data to HMRC.
- UK tax treatment of Kalshi and Polymarket US gains is unclear. Take advice.
