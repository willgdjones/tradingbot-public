# Stage 1 — Robinhood Chain memecoin base-rate backtest (plan & methodology)

Bead: `tradingbot-x6a`. Pre-registration:
[`docs/strategy-intake/2026-09-30-jevup-robinhood-chain-memecoins.md`](../strategy-intake/2026-09-30-jevup-robinhood-chain-memecoins.md)
§"Stage 1". This document records the **verified chain constants**, the exact
method, and every deviation from the literal pre-registration (with its reason),
*before* results are read. Results live in
[`08-robinhood-chain-memecoins-results.md`](08-robinhood-chain-memecoins-results.md).

Read-only research: **no wallet, no signing, no transactions, no Jev, no money.**

## 1. Verified constants (official sources only — never the post)

The referral post supplied a chain ID and contract addresses. Per the intake's
blow-up note ("poisoned contract addresses copied from shill posts"), the post is
treated as hostile input. Every constant below is verified independently:

| Constant | Value | Verified from |
|---|---|---|
| Chain ID | **4663** (`0x1237`) | The chain itself: `eth_chainId` → `0x1237`, `net_version` → `4663`; matches docs.robinhood.com/chain |
| Mainnet RPC | `https://rpc.mainnet.chain.robinhood.com` | docs.robinhood.com/chain (public, rate-limited; **pruned, not archive**) |
| UniswapV3Factory | `0x1f7d7550b1b028f7571e69a784071f0205fd2efa` | Uniswap official dev docs: `developers.uniswap.org/docs/protocols/v3/deployments/v3-robinhood-chain-deployments` |
| QuoterV2 / SwapRouter02 | `0x33e885…a9e7` / `0xcaf681…5cb2` | same Uniswap deployment page (recorded for reference; not used — read-only) |
| WETH (L2) | `0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73` | docs.robinhood.com/chain/protocol-contracts; also the dominant quote asset in `PoolCreated` events |
| USDG "Global Dollar" | `0x5fc5360d0400a0fd4f2af552add042d716f1d168` (6 dp) | On-chain `symbol()`/`name()`; used only as an ETH/USD oracle |

The post's claimed chain ID (4663) happened to be correct, but we confirmed it
from the chain and the docs rather than trusting it. The post's *contract
addresses* are not used at all; the factory comes from Uniswap's governance-
maintained deployment list.

On-chain facts established at build time (2026-10-01):
- Genesis (block 1) timestamp **2026-04-30**; head ≈ block 77.0M. Average block
  time **0.172 s** (≈5.81 blocks/s) — *not* the nominal 100 ms, so all time-based
  exits use real block→timestamp calibration from two anchor blocks.
- The public RPC is **pruned**: historical `eth_call` at old blocks returns
  "historical state not available". Therefore **all point-in-time state (price,
  reserves, liquidity, ownership) is reconstructed from event logs**, which the
  node serves across the full range. This is archive-free and exact (a reconstructed
  last-swap `sqrtPriceX96` equals the pool's live `slot0` to the integer).
- `eth_getLogs` limits: 10M-block span and 10k results per query, plus occasional
  server-side timeouts — all handled by recursive range-splitting.

## 2. The binding pre-registration (unchanged)

- **Universe:** every new Uniswap V3 pool on Robinhood Chain since launch.
- **Entry:** buy every pool that clears the hard gates at the first feasible block
  after creation plus a fixed latency of N blocks.
- **Hard gates:** liquidity ≥ $20k, ownership renounced, contract has code.
- **Five pre-registered exits (all go in the trials ledger):** hold 5m / 1h / 24h;
  TP +100% / SL −50%; trailing stop −40% from peak.
- **Costs:** gas, pool fee, price impact at the ≈$140 slot size, and an MEV/sandwich
  haircut. Honeypots (tokens that can't be sold) count as −100%.
- **Pass bar:** mean net return per launch > 0 after costs, **p < 0.10
  (Holm-adjusted across the 5 variants)**, with **≥ 200 qualifying launches**.
  Report max drawdown and a per-regime breakdown.
- If Stage 1 fails, the intake verdict becomes **Reject**.

## 3. Method

### 3.1 Universe & sampling (deviation — justified)
The chain has on the order of **hundreds of thousands** of Uniswap V3 pools
(≈270k by block 20M alone), and the only permitted data source is the pruned,
rate-limited public RPC — a dedicated/archive provider needs a new API key, which
needs owner approval (AGENTS.md). An exhaustive per-pool census ("every pool") is
therefore infeasible under the rules.

**Deviation:** the universe size is *estimated*, and launches are drawn as a
**timeline-uniform random sample** (fixed RNG seed): random anchor blocks across
`[genesis, head − 24h]`, taking the first WETH-paired pool created at/after each
anchor. Near-constant block cadence makes uniform-in-block ≈ uniform-in-time. The
sample and the funnel are fixed **before** returns are computed, so the pass bar's
statistical intent (≥200 qualifying launches, Holm-adjusted p<0.10, with CIs
available from the sample) is preserved. This is the only material deviation.

Scope note: the study restricts to **WETH-quoted** pools (the dominant quote asset
chain-wide). USDG- and stock-token-quoted pools are out of scope for the snipe rule.

### 3.2 Gates (point-in-time, from logs)
- **has code:** the token received ≥1 `Mint` (a transferFrom moved it into the
  pool ⇒ it is a real contract). Avoids an extra per-token call.
- **liquidity ≥ $20k:** total pool TVL at the entry block =
  `WETH_reserves·ETH/USD + meme_reserves·mid_price·ETH/USD`, reserves rebuilt from
  `Mint`+`Swap` flows (Burn/Collect outflows ignored — negligible in the first
  seconds, and if anything this *overstates* liquidity, i.e. is generous to the
  strategy). ETH/USD from the on-chain WETH/USDG oracle (daily-sampled).
- **ownership renounced:** the last `OwnershipTransferred` at/before entry set the
  owner to the zero address. Tokens that emit no `OwnershipTransferred` are counted
  as *not* confirmed-renounced (conservative). Point-in-time correct (log-based).
- **enterable:** active liquidity L>0 and a $140 WETH buy quotes a positive meme
  amount at entry.

### 3.3 Entry, exits, and the return
- **Entry** at `creation + N` blocks (N = 12 ≈ 2.1 s). Price/liquidity in force at
  that block (last swap ≤ block, else the `Initialize` price / seed-mint L).
- **Exits** (5): hold 5m/1h/24h exit at the block nearest `entry_ts + Δ`; TP/SL and
  trailing scan the swap price path and exit at the first trigger, else at 24h.
- **Return** is WETH-numeraire (isolates the memecoin edge from ETH/USD noise over
  the ≤24h hold): buy $140 of WETH→meme and sell the held meme→WETH, each leg a
  single-range Uniswap V3 exact-input quote so **my own price impact at both entry
  and exit is included**. Decimals cancel in every ratio.
- **Costs:** pool fee on each swap input (×2 round trip); MEV/sandwich haircut 50
  bps per side (100 bps round trip); gas 330k units × 0.03 gwei (≈$0.02 — a
  rounding error on this L2, included for completeness). **Honeypot** (no meme sell
  ever cleared in the observed window) ⇒ −100%. A failed entry/exit quote ⇒ −100%.

### 3.4 Statistics & pass bar
Per variant: one-sided t-test of per-launch net return against a zero-edge null
(`ledger.stats.luck_probability`), Holm-adjusted across the 5 variants. The study
**passes** only if some variant has mean net return > 0 **and** Holm p < 0.10
**and** there are ≥200 qualifying launches. Max drawdown (sequential $140 bets, in
entry-time order) and per-month + per-fee-tier regime breakdowns are reported.

## 4. Known limitations (reported honestly)
- **Sell taxes / transfer fees** inside token contracts are not captured by pool
  price logs, so returns are *optimistic* for taxed tokens. This biases *toward* the
  strategy — a negative result is therefore robust.
- Honeypot detection is a log proxy ("no sell ever cleared"), not a per-token sell
  simulation (which would need archive state).
- TVL can be inflated by one-sided seeding; again generous to the strategy.
- WETH-quoted pools only; latency/MEV/gas are fixed pre-registered estimates, with
  sensitivity reported in the results.

## 5. Reproduction
`uv run python -m tradingbot.research.robinhood_memecoins --run-id <id> --sample N`
— collection is resumable to `data/robinhood_chain/launches_<id>.jsonl` (gitignored);
analysis writes `08-robinhood-chain-memecoins-results.json` and records one
`Strategy` + five `Trial` rows (one per exit) in the Postgres trials ledger.
