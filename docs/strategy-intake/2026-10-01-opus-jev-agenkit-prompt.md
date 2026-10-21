# Opus 5.5 + Jev "trading_bot.xml" v2 prompt (AgenKit edition)

Source: [submissions/2026-10-01-opus-jev-agenkit-prompt.png](submissions/2026-10-01-opus-jev-agenkit-prompt.png)

## What it is
A longer version of the [2026-09-30 prompt](2026-09-30-opus-jev-prompt.md). It is still a template: the strategy is a placeholder, `[strategy idea]`. New elements:
- **Harness:** build everything through AgenKit (agenkit.xyz), a six-phase agentic harness.
- **State engine:** a point-in-time snapshot per candle (price, spread, book imbalance, realised volatility, trend, order flow).
- **Jev's role:** Jev scores fixed-outcome questions (regime, direction, buying pressure, setup quality, risk state).
- **Strategy gates:** Sharpe > 1.5, max drawdown < 15%, hit rate > 55%, and t > 2.0 out of sample.
- **Sizing:** quarter-Kelly sizing from Jev's probabilities.
- **Calibration and self-improvement:** calibration with Brier scores and reliability curves, and nightly "self-improvement" where Opus rewrites strategy.md and the Jev questions, re-running the backtest gate.

## Rubric
| # | Check | Result |
|---|---|---|
| 1 | Testable rule? | **Fail.** There is no strategy, only scaffolding. |
| 2 | Plausible reason it works? | None given. Jev is the decision layer, which is allowed since the 2026-10-01 PRD change, but there is no hypothesis about *why* the questions would predict anything. Prior evidence for Jev is negative (AUC 0.475). |
| 2b | AI-decided? | Yes, so a forward paper run is required (7+ days and 30+ trades). The prompt's own "backtest across 2 years" would be contaminated by look-ahead in the model's training data. |
| 3 | Tradeable here? | Mechanically yes: Alpaca paper. A Jev key needs the owner. |
| 4 | Evidence | None. It promotes AgenKit and Jev. |
| 5 | Provable? | Only forward, and only once a concrete strategy exists. |
| 6 | Cost | AgenKit would duplicate what we already run: ntm, beads, Agent Mail, test-first agents, review. Jev costs money per call. |
| 7 | Blow-up risk | **Nightly self-improvement against the same backtest gate is overfitting on a loop.** Every rewrite that "clears the gate" has been selected using the gate's data. Kelly sizing on probabilities that are only "verified calibrated" on a short sample magnifies errors. |

## Verdict: **Salvage**
Reject it as a strategy, and reject AgenKit. Keep these ideas:
1. **Calibration logging for AI-decided strategies.** Log every probability the model gives along with the realised outcome. Report the Brier score and a reliability curve per question. Use the model's confidence for sizing or thresholds only after calibration has been checked on our own forward fills. This is added to bead `tradingbot-tph`.
2. **The point-in-time state snapshot.** It is the only input the model sees, and it is built strictly from data timestamped before the decision. This matches our no-look-ahead rule; make it explicit in `tph`.
3. **A holdout-reuse guard for any self-improvement loop.** A rewritten strategy is a **new version**. It may not reuse the same 30% holdout; its holdout must be **new forward data** (paper). The single-run holdout enforcement (`zgn`) already refuses a second run per version, so make sure "new version, same holdout" is also refused. Filed as a bead.
4. **Extra statistics** (Sharpe, max drawdown, hit rate, out-of-sample t-stat) **shown on the leaderboard and weekly page for information.** The owner's promotion bar stays as PRD §4 says (profit after fees, in-sample and on the holdout).

Not adopted:
- AgenKit.
- Telegram alerts for every fill (PRD: incidents only).
- Quarter-Kelly sizing until calibration is proven.
- "Manual approval above $X" (the owner chose no gate).
