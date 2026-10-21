# Stage 1 — Robinhood Chain memecoin base-rate backtest (results)

Bead: `tradingbot-x6a`. Method & verified constants:
[`08-robinhood-chain-memecoins-plan.md`](08-robinhood-chain-memecoins-plan.md).
Machine-readable: [`08-robinhood-chain-memecoins-results.json`](08-robinhood-chain-memecoins-results.json).
Read-only, archive-free, **no Jev, no wallet, no money.** Run `stage1-20260930`
(2,400 sampled WETH-quoted launches; 242 qualifying).

## Verdict: **FAIL → the intake moves to Reject**

Buying every new WETH-quoted Uniswap V3 pool on Robinhood Chain that clears the
post's hard gates (liquidity ≥ $20k, ownership renounced, has code) is a **large,
statistically unambiguous net loser** under all five pre-registered exits, in every
monthly regime, after realistic costs. No exit variant has a positive mean; the
one-sided p-values are ≈ 1.0 (the edge is negative, not merely insignificant), with
242 qualifying launches (> the pre-registered 200). Per the pre-registration, Stage 1
failing makes the verdict **Reject**, and Stage 2 (Jev on paper) does **not** proceed.

The result is driven by a structural fact the data makes undeniable: **most gated
launches cannot be exited for a profit.** ~70% of qualifying launches never had a
single sell clear within 24h (honeypot or dead-on-arrival ⇒ −100%), and the rare
multi-x winners (one +1,332%) come nowhere near offsetting the mass of total losses.
You are the exit liquidity. This is exactly the structural-edge failure the intake
rubric predicted (LLM "alpha", speed-race sniping and copy-trading are all PRD
non-goals), now confirmed with on-chain evidence rather than argument.

## Chain reality established (all from official sources / the chain itself)
- Robinhood Chain mainnet is live: chain ID **4663** (self-reported via `eth_chainId`,
  matching docs.robinhood.com), on-chain genesis **2026-04-30**, ~0.172 s blocks,
  head ≈ block 77.0M.
- It is a **firehose of pool creation** — on the order of **hundreds of thousands**
  of Uniswap V3 pools (≈270k by block 20M alone), overwhelmingly WETH-quoted
  memecoins. The public RPC is **pruned** (no historical state), so every figure here
  is reconstructed from event logs (a reconstructed last-swap price equals the live
  `slot0` to the integer).
- The post's claimed chain ID happened to be right, but the factory and WETH used
  here come from Uniswap's and Robinhood's official docs — never the post.

## Gate funnel (2,400 WETH-quoted launches, timeline-uniform sample)

| stage | count | of sample |
|---|---|---|
| sampled | 2,400 | 100% |
| has code | 2,379 | 99.1% |
| liquidity ≥ $20k | 249 | 10.4% |
| ownership renounced (incl. immutable / no-owner) | 2,257 | 94.0% |
| enterable ($140 fills) | 2,320 | 96.7% |
| **qualifying (all gates)** | **242** | **10.1%** |
| honeypot / no-exit within 24h, among qualifying | 170 | 70% of qualifying |

The binding filter is **liquidity ≥ $20k**: only ~10% of launches ever reach it.
"Ownership renounced" almost always means the token is **non-Ownable / immutable**
(no owner function at all) — 2,213/2,400 — which satisfies the gate's intent (no owner
privilege to rug). Only 30/2,400 renounce via an explicit event. We read the gate in
its faithful, generous sense; the strict event-only count is reported for
transparency.

## Per-launch net return, after all costs

| exit | n | mean | median | win% | p (1-sided) | p (Holm) | max DD $ | best |
|---|---|---|---|---|---|---|---|---|
| hold 5m | 242 | −58.3% | −100% | 13.2% | 1.00 | 1.00 | 19,950 | +1,332% |
| hold 1h | 242 | −59.7% | −100% | 9.5% | 1.00 | 1.00 | 20,733 | +1,332% |
| hold 24h | 242 | −59.3% | −100% | 8.3% | 1.00 | 1.00 | 20,573 | +1,332% |
| TP+100% / SL−50% | 242 | −59.7% | −100% | 11.2% | 1.00 | 1.00 | 20,480 | +1,332% |
| trail −40% | 242 | −60.0% | −100% | 10.3% | 1.00 | 1.00 | 20,798 | +1,332% |

Every variant loses ~60% of capital per launch on average, with a median of −100%.
Max drawdown on a sequential series of $140 bets is ~$20k. The exit rule barely
matters — the loss is set at entry by how many launches are untradeable to exit.

## Regime breakdown — negative in every month (mean net return)

| month | hold 5m | hold 1h | hold 24h | TP/SL | trail | n (24h) |
|---|---|---|---|---|---|---|
| 2026-05 | −45.9% | −48.2% | −48.2% | −50.7% | −53.5% | 20 |
| 2026-06 | −75.9% | −74.1% | −66.8% | −72.7% | −75.3% | 19 |
| 2026-07 | −84.6% | −85.1% | −85.1% | −85.1% | −85.0% | 79 |
| 2026-08 | −68.8% | −73.2% | −71.3% | −66.4% | −70.9% | 64 |
| 2026-09 | −10.9% | −11.3% | −13.9% | −17.9% | −12.8% | 60 |

The July retail-launch frenzy was the worst regime (−85%); no month is positive, and
even the mildest (September, −11% to −18%) is a clear loss.

## By fee tier (hold 24h)
The memecoins launch almost entirely at the **1% (10000) tier** (n=192, **−78.1%**)
and the 0.3% tier (n=21, −12.7%). The only positive cell is the **0.01% (100) tier**
(n=29, +31.4%) — those are stable/pegged pairs, not memecoins; including them only
makes the aggregate *more* generous, yet it is still ≈ −59%.

## Cost model (pre-registered; biased toward the strategy)
Pool fee each swap (×2 round trip), my own price impact at the $140 size at **both**
entry and exit (single-range V3 quote), a 50 bps/side MEV/sandwich haircut, and gas
(~$0.02, negligible on this L2). Honeypot / no-exit-within-24h = −100%. Several
modelling choices (TVL can be inflated by one-sided seeding; sell-taxes inside token
transfers are not captured; immutable tokens pass the renounce gate) all push the
estimate **upward** — a negative result is therefore robust.

## Why this fails (structural reading)
New-pool sniping is a negative-sum game for a naive late buyer: insiders and faster
snipers are the early liquidity and sell into the arrivals, a large fraction of
tokens are honeypots or rug on the first block of real sell pressure, and the $140
size still pays fees + impact + MEV every round trip. A dumb gated rule cannot escape
this, and — per the pre-registration — if the *dumb rule* has no edge, there is no
base on which Jev could add value, so Stage 2 is not run.

## Decision
- **Stage 1: FAIL.** Mean net return < 0 for all five exits (p ≈ 1.0, Holm-adjusted),
  242 qualifying launches, negative in every regime.
- **Intake verdict → Reject.** No revisit without new evidence (intake §Verdict).
- **Stage 2 (Jev paper) and Stage 3 (live) do not proceed.** Bead `tradingbot-rb1`
  (Jev paper test) is closed as blocked by this outcome.
- **Trials ledger:** strategy `rhmeme_fbc4716d6e221e8238b36eac` (id 4414) + five
  `Trial` rows (one per exit), all `complete`, recorded as failures per AGENTS.md.

## Limitations (honest)
Pruned-node → log-only reconstruction; WETH-quoted pools only; a timeline-uniform
sample (not an exhaustive census) because the chain has hundreds of thousands of
pools and only a rate-limited public RPC is permitted (a dedicated provider needs an
owner-approved API key). Honeypot detection is a log proxy (no sell cleared in 24h),
not a per-token sell simulation. None of these could plausibly flip a −60% mean.

## Reproduction
`uv run python -m tradingbot.research.robinhood_memecoins --run-id stage1-20260930 --sample 2400`
(resumable collection in `data/robinhood_chain/`, gitignored).
