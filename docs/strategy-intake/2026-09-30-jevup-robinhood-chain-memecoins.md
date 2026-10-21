# JEVUP bot: Jev-driven memecoin sniping on Robinhood Chain

Source: [submissions/2026-09-30-jevup-robinhood-chain-memecoins.md](submissions/2026-09-30-jevup-robinhood-chain-memecoins.md). The owner was grilled on 2026-09-30.

## Rubric
| # | Check | Result |
|---|---|---|
| 1 | Testable rule? | Partly. The hard gates are concrete, but there is no exit rule, and the entry is "whatever Jev says". |
| 2 | Structural edge? | **Fail as written.** The alpha is Jev (an LLM; PRD non-goal; our research found AUC 0.475). New-pool sniping is a speed race against MEV bots and snipers (the HFT non-goal). Copy-trading high-win-rate wallets suffers from survivorship bias, and copied wallets can sell into their copiers. |
| 3 | Tradeable here? | **Not yet.** It needs a new venue and account type, which needs owner approval. A hot-wallet key can withdraw funds, which breaks the hard rule. |
| 4 | Evidence | The $27 → $27k claim can't be verified, and the post is a referral-link advertisement. No independent evidence. |
| 5 | Provable? | Yes, cheaply. The chain history is public, so the base rate of a dumb gated rule can be backtested without Jev. |
| 6 | Cost | Moderate: an EVM reader, a pool-launch history, and a gas/slippage/MEV model. Jev costs money per call. |
| 7 | Blow-up risk | Honeypots and rugs that pass the gates, and MEV sandwiches. A hot-wallet drain from a bug, a prompt-injected token name, or **poisoned contract addresses copied from shill posts**. Never use addresses from the post; verify them from official Robinhood and Uniswap sources. |

## Verdict: **REJECT** (Stage 1 failed, 2026-10-01)

Stage 1 ran and **failed decisively** (bead `tradingbot-x6a`). The dumb gated
buy-every-new-pool rule is a large, statistically unambiguous net loser on real
Robinhood Chain on-chain data: mean net return **≈ −59%** per launch for **all five**
pre-registered exits (one-sided p ≈ 1.0, Holm-adjusted; **242 qualifying launches** >
the required 200), negative in **every** monthly regime. ~70% of qualifying launches
could not be sold within 24h (honeypot / dead-on-arrival ⇒ −100%). Evidence:
[`docs/research/08-robinhood-chain-memecoins-results.md`](../research/08-robinhood-chain-memecoins-results.md)
(plan: `08-robinhood-chain-memecoins-plan.md`; trials ledger: strategy
`rhmeme_fbc4716d6e221e8238b36eac`).

Per the pre-registration, Stage 1 failing makes this **Reject, with no revisit without
new evidence**. **Stage 2 (Jev on paper) and Stage 3 (live) do not proceed.** If the
dumb rule has no edge, there is no base for Jev to improve on — consistent with the
rubric's "structural edge: Fail as written". The staged plan below is retained for the
record.

### Original decision (superseded): Park → staged research
The owner believed the claim is "probably exaggerated, but there's something there" and wanted that tested. The data decided; stage 1 failed.

### Stage 1: chain base-rate backtest (research, no wallet, no Jev, no money)
- **Universe:** every new Uniswap V3 pool on Robinhood Chain since launch. Verify the chain ID, RPC and factory address from official docs before use.
- **Entry:** buy every pool that passes the post's hard gates (liquidity ≥ $20k, ownership renounced, contract has code) at the first feasible block after creation, plus a fixed latency of N blocks, recorded honestly.
- **Pre-registered exits (5 variants, all go in the trials ledger):** hold 5m, 1h or 24h; TP +100% / SL −50%; trailing stop −40% from peak.
- **Costs:** gas, pool fee, price impact at the slot's size (about $140), and an MEV/sandwich haircut. Honeypots (tokens that can't be sold) count as −100%.
- **Pass bar:** mean net return per launch > 0 after costs, p < 0.10 (Holm-adjusted across the 5 variants), with at least 200 qualifying launches. Also report drawdown and regimes (tradingbot-l0v).

### Stage 2: Jev on paper vs the dumb rule (only if stage 1 passes)
- Same gates. Jev's buy/hold/skip is compared with "buy everything that passes the gates" on live launches.
- **Kill rule:** Jev's buys don't beat the dumb rule after costs over 30 days or 200 launches.
- **Budget:** at most $20/month of Jev API spend. New API key, so it needs owner approval.
- Pool and token fields are untrusted data; they are never interpolated as instructions.

### Stage 3: live (only if stage 2 passes; owner vote required)
- Needs an explicit PRD amendment to the "no LLM alpha" non-goal, voted on with the paper data in hand.
- Capital is one existing $140 slot.
- Wallet: a **smart-contract wallet with a session key restricted to swaps on a whitelisted router, with no transfers** (this keeps the spirit of "trading-only keys"). No plain hot-wallet key.
- All §6 limits apply unchanged.
