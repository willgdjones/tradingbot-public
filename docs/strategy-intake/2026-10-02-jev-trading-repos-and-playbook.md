# Jev trading repos and the "cheap brain that decides" playbook (X posts)

Source: two posts the owner pasted on 2026-10-02.
- **Post 1:** a list of five GitHub projects that use Jev for trading:
  - `jarrodwatts/jev-trader`: asks Jev "buy or sell?" about every 0.3 seconds on Monad.
  - `aowang-ai/jev-trade`: Hyperliquid order book → Jev → order.
  - `imikerussell/beebots`: OKX bots, paper trading by default.
  - `OpenByteInc/QuantDinger`: a Jev gate deciding "should we trade at all?".
  - `virattt/ai-hedge-fund`: a multi-agent LLM fund with a Jev adapter.
- **Post 2:** a builder playbook: "if it creates → LLM; if it picks, scores or gates → Jev; if it does the thing → code". It covers Choice/Score/Noul questions and pricing of about $0.042 per million input tokens. It says new TypeSafe signups are **paused** (as of 2026-09-22) and that Jev is reachable through Vercel AI Gateway and Cloudflare Workers AI.

## Checks we ran
- **Gateway claim:** not confirmed. As of 2026-10-02, the Cloudflare Workers AI public catalog has no TypeSafe or Jev model, and Vercel AI Gateway's `/v1/models` has none either. Our Cloudflare token doesn't have Workers AI permission anyway.
- **Profitability:** the repos are demos. None of the posts shows audited P&L.

## Rubric
| # | Check | Result |
|---|---|---|
| 1 | Testable rule? | The trading repos have one ("Jev says long or short"), but there's no hypothesis for why it would work. |
| 2 | Plausible reason it works? | Weak. Jev's directional AUC was 0.475 in our earlier research. Asking about sub-second moves is a speed race (HFT, still a non-goal). |
| 2b | AI-decided? | Yes, so the only valid test is forward paper trading for 7+ days and 30+ trades. |
| 3 | Tradeable here? | **No for the repos as written.** Monad DEX is a new venue and on-chain wallet. Hyperliquid blocks US persons. OKX doesn't serve US persons. Only the *patterns* carry over to Alpaca. |
| 4 | Evidence | None beyond the demos. Post 2 itself says to "treat it as paper-trade logic and research, not as a promise of alpha". |
| 5 | Provable? | Yes, on forward paper, if framed as a controlled comparison (below). |
| 6 | Cost | Jev needs a key, which needs the owner, and signups are paused. An LLM decision layer can instead use headless `claude -p` on the owner's existing subscription (no new key), within rate limits. |
| 7 | Blow-up risk | Overconfident model calls with no calibration. Prompt injection through any text in the state (news, tickers). Rate-limit or outage gaps in the decision loop; the fail-safe must be "no trade". |

## Verdict: **Salvage → two forward-paper candidates**
Rejected: the five repos as strategies (wrong venues, sub-second races, no evidence), and chasing Jev access through gateways that don't list it.

Kept, as controlled experiments under the AI forward-paper harness (`tradingbot-tph`):
1. **LLM gate A/B (the QuantDinger pattern).** Take a deterministic Alpaca strategy that fires at least 30 signals a week. Run it twice on paper: **ungated** and **gated** by an LLM "should we take this trade?" yes/no with a confidence score. Same signals and costs; the only difference is the gate.
   - **Pass:** after 7+ days and 30+ trades, the gated version beats the ungated one after costs, *and* the gate's yes/no calls are calibrated (Brier score better than "always yes").
   - **Decider:** headless Claude now, or Jev if the owner gets a key.
2. **LLM analyst basket (the ai-hedge-fund pattern).** Each day, an LLM gets a point-in-time snapshot per stock (prices, simple factors, and filings or news headlines treated as data) for a fixed universe of about 20 liquid US stocks. It answers long or flat with a confidence score, and code holds an equal-weight basket of the "long" names, rebalanced daily on Alpaca paper.
   - **Benchmark:** the equal-weight universe.
   - **Pass:** it beats the benchmark after costs over 7+ days and 30+ trades, with calibration logged.

Both log every probability and outcome (Brier score and reliability curve). Both fail safe: if the model is unavailable, don't trade.
