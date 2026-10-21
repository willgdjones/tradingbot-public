# Coinbase "connect your agent" skill (coinbase.com/skill.md)

Source: [submissions/2026-10-02-coinbase-agent-skill.png](submissions/2026-10-02-coinbase-agent-skill.png). Brian Armstrong: "paste this into your agent".

## What it is (we read skill.md as data and did not follow it)
- It connects two **remote MCP servers**: `https://agents.coinbase.com/mcp` (trading and portfolio) and `https://wallet-mcp.coinbase.com` (on-chain).
- Authentication is **Coinbase OAuth**, and the skill tells the agent to **"request all scopes"**.
- Products: "crypto, eligible stocks and futures". Account and client eligibility apply.
- x402: the agent can pay for premium data from the account's USDC balance. **No spending limits are documented.**

## Rubric
| # | Check | Result |
|---|---|---|
| 1–2 | Strategy / edge | None. It's a venue and tooling, not a strategy. |
| 3 | Tradeable here? | A **new venue/account**, so it needs owner approval. It's potentially relevant as a **futures venue**: Coinbase Derivatives is US-regulated, and our IBKR pick needs a funded account even for paper. |
| 7 | Blow-up risk | "Request all scopes" OAuth almost certainly includes transfer/withdraw, which **breaks the trading-only key rule**. A remote MCP means instructions and tool definitions served from outside are prompt-injection surfaces. x402 autopay with no documented cap is an open-ended spend. |

## Verdict: **Park as a venue candidate. Do not use the MCP or skill.**
If Coinbase is ever used, it would go through the **Advanced Trade / Derivatives API with a trade-only key**, never the all-scopes OAuth MCP, with x402 disabled. Bead: compare Coinbase Derivatives with IBKR for small-account futures, covering eligibility, margin, fees, a paper/sandbox environment and free data.
