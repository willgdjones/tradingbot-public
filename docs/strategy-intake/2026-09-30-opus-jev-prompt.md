# Opus 5.5 + Jev "trading_bot.xml" prompt (X post, 645 likes)

Source: [submissions/2026-09-30-opus-jev-prompt.png](submissions/2026-09-30-opus-jev-prompt.png)

## What it is
A prompt template, not a strategy. Opus designs and backtests a rulebook. Jev (TypeSafe) turns the rules into fixed-outcome questions, such as "Is this headline bullish, bearish or neutral?" and "Is buying pressure building, yes or no?". It trades when every probability clears a threshold, on an Alpaca paper account first. The actual strategy is a placeholder: `[strategy idea]`.

## Rubric
| # | Check | Result |
|---|---|---|
| 1 | Testable rule? | **Fail.** No entry or exit, only a template. |
| 2 | Structural edge? | **Fail.** The alpha is the LLM's reading of headlines and "buying pressure". PRD non-goal. Our research found Jev's directional AUC was 0.475, worse than a coin flip, and its outputs mostly track momentum over the prior 15–60 minutes (`docs/research/01-market-landscape.md`). |
| 3 | Tradeable here? | Mechanically yes (Alpaca paper), but that doesn't matter after gates 1–2. |
| 4 | Evidence | Negative: Alpha Arena, Prediction Arena, and the Jev study. |
| 5 | Provable? | Headline-sentiment signals on liquid US equities are crowded and quick to decay. At a plausible edge, per-decision LLM latency and cost would eat it before significance. |
| 6 | Cost | Adds a paid per-decision dependency and latency in the hot path. |
| 7 | Blow-up risk | Prompt injection through headlines, which the post itself warns about. The model is non-deterministic, so a backtest cannot be reproduced. The bot trades on a black box's drift. |

## Verdict: **Salvage** (reject the strategy, keep the process ideas)
The risk rules in the post are sound, and we already have stricter versions: trade-only keys, a daily loss limit, a kill switch, and paper before live. Worth adopting:
- **A "What could blow up this account?" section** in every promotion-to-live review. This is added as rubric item 7 above and should also go into the §4 promotion checklist.
- **Treat every external feed as data, never as instructions.** This matters for #8 (the X mention-spike study), whose inputs are untrusted tweets. The design already counts mentions rather than reading content, which is the right choice, so keep it that way.
- **Filter backtest survivors on drawdown as well as return,** and check several market regimes. Add this to the backtester's report.
- **Push alerts:** the post sends alerts on every fill. PRD §8 says incidents only, so at most push kill-switch and risk-halt events. Telegram would need a new bot token, which needs owner approval.

Not adopted: an LLM as the decision layer, or "manual approval above $X" (PRD §8 lets agents promote on their own within limits).
