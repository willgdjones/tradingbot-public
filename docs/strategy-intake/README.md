# Strategy intake

The owner sends strategy ideas (X posts, screenshots, links, papers, or a line of text) to any Claude session. Each one gets evaluated against the PRD and recorded here, whether it is accepted or rejected.

## Process
1. Save the source to `submissions/YYYY-MM-DD-<slug>.<png|md|pdf>`.
2. Write the evaluation to `YYYY-MM-DD-<slug>.md` using the template below.
3. Handle the verdict:
   - **Pursue:** create a bead (`br create ... -l strategy,intake`) that starts at the backtest stage (PRD §4).
   - **Salvage:** create beads only for the reusable parts.
   - **Reject:** no bead.
4. Add a row to the log table below, and add a line to CHANGELOG.

The evaluation is a desk review only. It does not change risk limits, venues, keys or capital; those still need the owner (PRD §8).

## Rubric (in order; a fail at gates 1–3 is a reject)
1. **Is there a concrete, testable rule?** Entry, exit, sizing and universe must be specified. "Use AI to find trades" is not a strategy.
2. **Is there a plausible, documented or testable reason it works?** Structural, risk-premium, behavioural or AI-decided ideas are all eligible (PRD §3, open-minded since 2026-10-01). Reject sports and speed races (HFT).
   - **2b.** If it is AI-decided, a historical backtest doesn't count. It needs a forward paper run of 7+ days and 30+ trades (PRD §4).
3. **Is it tradeable here?**
   - Venues: Alpaca cash account (live). Kalshi and Polymarket US are pending verification. Futures are research only until a broker is chosen and funded. Data must be free.
   - Capital: $1k, about $140 per slice.
   - Must fit the §6 limits, T+1 settlement and the PDT rule.
4. **Does evidence already exist?** Check `docs/research/`, the "dead" list in PRD §5 and the trials ledger. Is it already published or arbitraged away?
5. **Is it provable?**
   - Is there enough history for a backtest after fees?
   - How many trades would it take to reach p < 0.05 at a plausible edge?
   - Can it be proven within about 60 days?
6. **Cost:** build effort, data cost, and overlap with components that already exist.
7. **What could blow up the account?** Tail risk, adverse selection, gap risk, and dependence on a counterparty or venue.

**Verdict:** one of Pursue, Park (plausible but low priority or blocked), Salvage (reject the strategy, keep the useful parts) or Reject.

## Log
| Date | Submission | Verdict | Beads |
|---|---|---|---|
| 2026-09-30 | [Opus 5.5 + Jev trading-bot prompt (X post)](2026-09-30-opus-jev-prompt.md) | Salvage | see file |
| 2026-09-30 | [JEVUP bot: Jev memecoin sniping on Robinhood Chain](2026-09-30-jevup-robinhood-chain-memecoins.md) | Park → staged research | stage 1 research bead; stage 2 deferred |
| 2026-10-01 | [Opus 5.5 + Jev v2 prompt (AgenKit edition)](2026-10-01-opus-jev-agenkit-prompt.md) | Salvage | calibration logging (tph), holdout-reuse guard, info stats |
| 2026-10-02 | [Jev trading repos + 'cheap brain' playbook](2026-10-02-jev-trading-repos-and-playbook.md) | Salvage | AI-1 LLM gate A/B, AI-2 LLM analyst basket (forward paper) |
| 2026-10-02 | [Coinbase agent skill / MCP](2026-10-02-coinbase-agent-skill.md) | Park (venue candidate; don't use the MCP) | futures venue comparison |
| 2026-10-02 | [je-suis-tm/quant-trading, 17 strategies](2026-10-02-je-suis-tm-quant-trading.md) | Salvage | batch of 8 classic TA rules |
| 2026-10-02 | [RohOnChain 'CLAUDE.md 10x quant'](2026-10-02-rohonchain-claude-md.md) | Duplicate | none |
| 2026-10-05 | [X bookmarks batch (5)](2026-10-05-x-bookmarks-batch.md) | Pursue×1 / Salvage/Park×2 / Reject×2 | HMM regime filter (`rox`) |
| 2026-10-08 | [X bookmarks batch (2)](2026-10-08-x-bookmarks-batch.md) | Reject×2 | none |
| 2026-10-09 | [IBS / Gotobi / Claude-funnel batch](2026-10-09-ibs-gotobi-funnel-batch.md) | Pursue (IBS) / Pursue-research (Gotobi) / Reject (funnel) | IBS backtest, Gotobi FX research |
| 2026-10-14 | [X bookmarks batch (5)](2026-10-14-x-bookmarks-batch.md) | Reject×4 / skip×1 | none |
| 2026-10-14 | [Options wheel, weekly 0.15–0.25Δ puts (@MFT_Get_Funded)](2026-10-14-wheel-strategy-mft.md) | Park (capital-blocked; see C14) | none |
| 2026-10-15 | [X bookmarks batch (2)](2026-10-15-x-bookmarks-batch.md) | Reject×2 | none |
