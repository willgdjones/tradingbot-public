"""Stage-1 base-rate backtest of the "JEVUP" Robinhood Chain memecoin snipe rule
(tradingbot-x6a).

Pre-registered in ``docs/strategy-intake/2026-09-30-jevup-robinhood-chain-memecoins.md``
and ``docs/research/08-robinhood-chain-memecoins-plan.md``. This tests the *dumb*
gated rule with **no Jev, no wallet, no money** -- buy every new Uniswap V3 pool
that clears the post's hard gates, hold it under five fixed exit rules, and ask
whether the mean net return per launch is positive after realistic costs.

Design (and its deviations from the literal pre-registration) are justified in the
plan doc: the chain has ~hundreds of thousands of pools and the only permitted RPC
is a pruned, rate-limited public node (a dedicated provider needs an API key, which
needs owner approval per AGENTS.md), so the universe is estimated and the launches
are drawn as a **timeline-uniform random sample** rather than an exhaustive census.
The sample is fixed before returns are computed, preserving the pre-registration's
statistical intent (>=200 qualifying launches, Holm-adjusted p<0.10).

Everything is reconstructed from event logs (the node serves no historical state).
Collection (slow, RPC-bound) is resumable to a JSONL cache; analysis is pure/local.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import random
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.data.loader import local_engine
from tradingbot.db.models import Strategy, Trial
from tradingbot.ledger.stats import luck_probability, max_drawdown
from tradingbot.research import robinhood_chain as rc

# --- Pre-registered parameters ------------------------------------------------
POSITION_USD = 140.0
LATENCY_BLOCKS = 12            # ~2.1s snipe latency after pool creation (5.8 blk/s)
MEV_HAIRCUT_BPS_PER_SIDE = 50  # 0.5%/side sandwich haircut (1% round trip)
GAS_UNITS_ROUNDTRIP = 330_000  # 2 swaps + approve
GAS_PRICE_GWEI = 0.03          # ~current L2 gas; cost is a rounding error vs $140
LIQUIDITY_GATE_USD = 20_000.0
TP_MULT = 2.0                  # +100%
SL_MULT = 0.5                  # -50%
TRAIL_FRAC = 0.6              # exit at -40% from peak

HOLD_SECONDS = {"hold_5m": 300, "hold_1h": 3600, "hold_24h": 86400}
MAX_HOLD_SECONDS = 86400
EXIT_VARIANTS = ("hold_5m", "hold_1h", "hold_24h", "tp100_sl50", "trail40")


# --- Oracle / clock caching ---------------------------------------------------
def load_context(rpc: rc.RpcClient, cache_dir: Path, refresh: bool = False):
    cache_dir.mkdir(parents=True, exist_ok=True)
    ctx_path = cache_dir / "context.json"
    if ctx_path.exists() and not refresh:
        ctx = json.loads(ctx_path.read_text())
        clock = rc.BlockClock(**ctx["clock"])
        oracle = rc.EthUsdOracle(rpc, ctx["head"], clock, cache=ctx["oracle"])
        return ctx["head"], clock, oracle
    head = rpc.block_number()
    clock = rc.BlockClock.calibrate(rpc, head)
    oracle = rc.EthUsdOracle(rpc, head, clock)
    ctx = {"head": head, "genesis_ts": clock.t0,
           "clock": {"t0": clock.t0, "b0": clock.b0,
                     "secs_per_block": clock.secs_per_block},
           "oracle": oracle.to_cache()}
    ctx_path.write_text(json.dumps(ctx))
    return head, clock, oracle


# --- Sampling -----------------------------------------------------------------
def sample_pools(rpc: rc.RpcClient, lo: int, hi: int, n: int, *, seed: int,
                 probe: int = 4000) -> list[dict]:
    """Draw ~``n`` distinct WETH-paired pools whose creation block is uniform over
    [lo, hi]: for each random anchor, take the first WETH-paired pool created at or
    after it. Uniform-in-block ~= uniform-in-time (near-constant block cadence)."""
    rng = random.Random(seed)
    seen: dict[str, dict] = {}
    attempts = 0
    max_attempts = n * 6
    while len(seen) < n and attempts < max_attempts:
        attempts += 1
        anchor = rng.randint(lo, hi)
        logs = rpc.get_logs(address=rc.FACTORY, topics=[rc.T_POOL_CREATED],
                            from_block=anchor, to_block=min(anchor + probe, hi))
        logs.sort(key=lambda l: (rc._u(l["blockNumber"]), rc._u(l["logIndex"])))
        for lg in logs:
            w = rc._words(lg["data"])
            t0 = "0x" + lg["topics"][1][-40:]
            t1 = "0x" + lg["topics"][2][-40:]
            if t0.lower() != rc.WETH and t1.lower() != rc.WETH:
                continue
            pool = "0x" + w[1][-40:]
            if pool in seen:
                continue
            seen[pool] = {"pool": pool, "block": rc._u(lg["blockNumber"]),
                          "token0": t0, "token1": t1,
                          "fee": rc._u(lg["topics"][3]),
                          "tx": lg["transactionHash"]}
            break
    return list(seen.values())


# --- Ownership (point-in-time, from OwnershipTransferred logs) -----------------
def renounced_at(rpc: rc.RpcClient, token: str, creation_block: int,
                 entry_block: int) -> tuple[bool, str, int]:
    """Point-in-time ownership status at ``entry_block`` -> (renounced, category, n).

    The gate's intent is "no owner privilege can rug the position". That is met by
    an explicit renouncement (owner -> 0) *and* by tokens that never had an owner
    at all (non-Ownable / immutable code). On Robinhood Chain the latter dominates.

    Determination is point-in-time sound:
      * If the token emitted OwnershipTransferred at/before entry, the last such
        event is authoritative (renounced iff it set owner to 0).
      * Otherwise ownership cannot have changed, so ``owner()`` read at *latest*
        equals the entry-time state: "revert" (immutable) or 0 => renounced; a
        non-zero owner => a persistent owner that was never renounced.
    """
    lo = max(0, creation_block - 2_000_000)
    logs = rpc.get_logs(address=token, topics=[rc.T_OWNERSHIP],
                        from_block=lo, to_block=entry_block)
    if logs:
        logs.sort(key=lambda l: (rc._u(l["blockNumber"]), rc._u(l["logIndex"])))
        last_new_owner = "0x" + logs[-1]["topics"][2][-40:]
        if last_new_owner == rc.ZERO_ADDR:
            return (True, "renounced_via_event", len(logs))
        return (False, "has_owner", len(logs))
    owner = rc.token_owner(rpc, token)
    if owner == "revert":
        return (True, "no_owner_immutable", 0)
    if owner == rc.ZERO_ADDR:
        return (True, "owner_zero_no_event", 0)
    return (False, "has_owner", 0)


# --- Per-pool evaluation ------------------------------------------------------
@dataclass
class LaunchRecord:
    pool: str
    block: int
    entry_block: int
    fee: int
    token0: str
    token1: str
    meme: str
    weth_is_token0: bool
    eth_usd: float
    tvl_usd: float
    weth_reserve_usd: float
    liquidity: float
    n_swaps: int
    n_meme_sells: int
    n_meme_buys: int
    n_mints: int
    renounced: bool
    ownership_category: str
    n_ownership_events: int
    has_code: bool
    enterable: bool
    honeypot: bool
    gate_liquidity: bool
    qualifies: bool
    returns: dict          # variant -> net return (fraction), None if not qualifying
    exit_blocks: dict

    def to_json(self) -> dict:
        return self.__dict__


def _roundtrip_return(hist: rc.PoolHistory, entry_block: int, exit_block: int,
                      eth_usd: float, fee: int) -> float | None:
    """Net WETH-numeraire return of a $140 buy at ``entry_block`` and a sell at
    ``exit_block``, with pool fee + MEV haircut (both sides) + gas. None if the
    trade cannot execute (no entry/exit liquidity)."""
    sp_e = hist.price_at(entry_block); L_e = hist.liquidity_at(entry_block)
    sp_x = hist.price_at(exit_block); L_x = hist.liquidity_at(exit_block)
    if not sp_e or not sp_x or L_e <= 0 or L_x <= 0:
        return None
    fee_f = fee / 1_000_000.0
    mev = MEV_HAIRCUT_BPS_PER_SIDE / 10_000.0
    weth_in = POSITION_USD / eth_usd * 1e18
    # buy: WETH -> meme
    meme_out, _ = rc.quote_exact_in(sp_e, L_e, weth_in * (1 - fee_f),
                                    token0_in=hist.weth_is_token0)
    if meme_out <= 0:
        return None
    meme_held = meme_out * (1 - mev)
    # sell: meme -> WETH at exit state
    weth_out, _ = rc.quote_exact_in(sp_x, L_x, meme_held * (1 - fee_f),
                                    token0_in=not hist.weth_is_token0)
    weth_out *= (1 - mev)
    gas_weth = GAS_UNITS_ROUNDTRIP * GAS_PRICE_GWEI * 1e9  # wei
    return (weth_out - gas_weth) / weth_in - 1.0


def _time_exit_block(hist: rc.PoolHistory, clock: rc.BlockClock,
                     entry_block: int, hold_s: int, head: int) -> int:
    target_ts = clock.ts(entry_block) + hold_s
    return min(clock.block_at(target_ts), head)


def _rule_exit_block(hist: rc.PoolHistory, clock: rc.BlockClock, entry_block: int,
                     entry_mid: float, kind: str, head: int) -> int:
    """Exit block for TP/SL or trailing rules, scanning the swap price path from
    entry; falls back to the 24h block if never triggered."""
    cap = _time_exit_block(hist, clock, entry_block, MAX_HOLD_SECONDS, head)
    peak = entry_mid
    for s in hist.swaps:
        if s.block <= entry_block:
            continue
        if s.block > cap:
            break
        mid = rc.mid_weth_per_meme(s.sqrt_price_x96, hist.weth_is_token0)
        if kind == "tp100_sl50":
            if mid >= entry_mid * TP_MULT or mid <= entry_mid * SL_MULT:
                return s.block
        else:  # trail40
            if mid > peak:
                peak = mid
            if mid <= peak * TRAIL_FRAC:
                return s.block
    return cap


def evaluate_pool(rpc: rc.RpcClient, clock: rc.BlockClock, oracle: rc.EthUsdOracle,
                  head: int, cand: dict) -> LaunchRecord:
    pool, block, fee = cand["pool"], cand["block"], cand["fee"]
    token0, token1 = cand["token0"], cand["token1"]
    weth_is_token0 = token0.lower() == rc.WETH
    meme = token1 if weth_is_token0 else token0
    entry_block = block + LATENCY_BLOCKS
    window_end = min(_time_exit_block_static(clock, entry_block, MAX_HOLD_SECONDS), head)
    hist = rc.build_pool_history(rpc, pool, block, token0, token1, fee, window_end)

    eth_usd = oracle.at(entry_block)
    r0, r1 = hist.reserves_at(entry_block)
    weth_raw = r0 if weth_is_token0 else r1
    meme_raw = r1 if weth_is_token0 else r0
    sp_e = hist.price_at(entry_block)
    L_e = hist.liquidity_at(entry_block)
    mid_e = rc.mid_weth_per_meme(sp_e, weth_is_token0) if sp_e else 0.0
    weth_usd = weth_raw / 1e18 * eth_usd
    meme_usd = meme_raw * mid_e / 1e18 * eth_usd
    tvl_usd = weth_usd + meme_usd

    has_code = hist.n_mints >= 1  # a mint moved tokens in -> the token has code
    renounced, own_cat, n_own = renounced_at(rpc, meme, block, entry_block)
    honeypot = hist.n_meme_sells == 0  # no sell ever cleared -> cannot exit
    # Can a $140 buy actually fill at entry?
    enterable = bool(sp_e) and L_e > 0
    if enterable:
        fee_f = fee / 1e6
        meme_out, _ = rc.quote_exact_in(sp_e, L_e, (POSITION_USD / eth_usd * 1e18) * (1 - fee_f),
                                        token0_in=weth_is_token0)
        enterable = meme_out > 0

    gate_liq = tvl_usd >= LIQUIDITY_GATE_USD
    qualifies = bool(gate_liq and renounced and has_code and enterable)

    returns: dict = {v: None for v in EXIT_VARIANTS}
    exit_blocks: dict = {v: None for v in EXIT_VARIANTS}
    if qualifies:
        if honeypot:
            for v in EXIT_VARIANTS:
                returns[v] = -1.0
        else:
            for v in ("hold_5m", "hold_1h", "hold_24h"):
                xb = _time_exit_block(hist, clock, entry_block, HOLD_SECONDS[v], head)
                exit_blocks[v] = xb
                r = _roundtrip_return(hist, entry_block, xb, eth_usd, fee)
                returns[v] = -1.0 if r is None else r
            for v in ("tp100_sl50", "trail40"):
                xb = _rule_exit_block(hist, clock, entry_block, mid_e, v, head)
                exit_blocks[v] = xb
                r = _roundtrip_return(hist, entry_block, xb, eth_usd, fee)
                returns[v] = -1.0 if r is None else r

    return LaunchRecord(
        pool=pool, block=block, entry_block=entry_block, fee=fee,
        token0=token0, token1=token1, meme=meme,
        weth_is_token0=weth_is_token0, eth_usd=eth_usd, tvl_usd=tvl_usd,
        weth_reserve_usd=weth_usd, liquidity=L_e, n_swaps=len(hist.swaps),
        n_meme_sells=hist.n_meme_sells, n_meme_buys=hist.n_meme_buys,
        n_mints=hist.n_mints, renounced=renounced, ownership_category=own_cat,
        n_ownership_events=n_own, has_code=has_code, enterable=enterable,
        honeypot=honeypot, gate_liquidity=gate_liq, qualifies=qualifies,
        returns=returns, exit_blocks=exit_blocks)


def _time_exit_block_static(clock: rc.BlockClock, entry_block: int, hold_s: int) -> int:
    return clock.block_at(clock.ts(entry_block) + hold_s)


# --- Collection (resumable) ---------------------------------------------------
def collect(rpc: rc.RpcClient, clock, oracle, head: int, cands: list[dict],
            cache_path: Path, *, log=print) -> list[dict]:
    done = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["pool"]] = rec
    todo = [c for c in cands if c["pool"] not in done]
    log(f"collect: {len(done)} cached, {len(todo)} to fetch")
    with cache_path.open("a") as fh:
        for i, cand in enumerate(todo, 1):
            try:
                rec = evaluate_pool(rpc, clock, oracle, head, cand).to_json()
            except rc.RpcError as e:
                rec = {"pool": cand["pool"], "block": cand["block"], "error": str(e)}
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            done[cand["pool"]] = rec
            if i % 25 == 0:
                log(f"  {i}/{len(todo)} reqs={rpc.request_count}")
    return list(done.values())


# --- Analysis -----------------------------------------------------------------
def holm_adjust(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni step-down adjusted p-values."""
    items = sorted(((k, v) for k, v in pvals.items() if v is not None), key=lambda kv: kv[1])
    m = len(items)
    adj = {}
    running = 0.0
    for rank, (k, p) in enumerate(items):
        val = (m - rank) * p
        running = max(running, val)
        adj[k] = min(1.0, running)
    for k, v in pvals.items():
        if v is None:
            adj[k] = None
    return adj


def analyze(records: list[dict], clock: rc.BlockClock) -> dict:
    valid = [r for r in records if "error" not in r]
    errored = [r for r in records if "error" in r]
    qualifying = [r for r in valid if r.get("qualifies")]
    qualifying.sort(key=lambda r: r["entry_block"])

    # Gate funnel.
    funnel = {
        "sampled": len(records),
        "errored": len(errored),
        "evaluated": len(valid),
        "has_code": sum(1 for r in valid if r.get("has_code")),
        "liquidity_ge_20k": sum(1 for r in valid if r.get("gate_liquidity")),
        "renounced": sum(1 for r in valid if r.get("renounced")),
        "enterable": sum(1 for r in valid if r.get("enterable")),
        "qualifying": len(qualifying),
        "honeypot_among_qualifying": sum(1 for r in qualifying if r.get("honeypot")),
        "ownership_categories": dict(Counter(r.get("ownership_category") for r in valid)),
        "renounced_strict_event_only": sum(
            1 for r in valid if r.get("ownership_category") == "renounced_via_event"),
    }

    per_variant = {}
    for v in EXIT_VARIANTS:
        rets = [r["returns"][v] for r in qualifying if r["returns"].get(v) is not None]
        pnls_usd = [D(str(x * POSITION_USD)) for x in rets]
        n = len(rets)
        mean = sum(rets) / n if n else None
        median = sorted(rets)[n // 2] if n else None
        wins = sum(1 for x in rets if x > 0)
        p = luck_probability(rets) if n >= 2 else None
        dd = float(max_drawdown(pnls_usd)) if pnls_usd else None
        per_variant[v] = {
            "n": n, "mean_net_return": mean, "median_net_return": median,
            "mean_net_usd": (mean * POSITION_USD) if mean is not None else None,
            "total_net_usd": sum(rets) * POSITION_USD if n else None,
            "win_rate": (wins / n) if n else None,
            "p_value_one_sided": p,
            "max_drawdown_usd": dd,
            "worst": min(rets) if n else None, "best": max(rets) if n else None,
        }
    holm = holm_adjust({v: per_variant[v]["p_value_one_sided"] for v in EXIT_VARIANTS})
    for v in EXIT_VARIANTS:
        per_variant[v]["p_value_holm"] = holm.get(v)

    # Regime breakdown: by calendar month of entry.
    regimes = defaultdict(lambda: {v: [] for v in EXIT_VARIANTS})
    for r in qualifying:
        month = datetime.fromtimestamp(clock.ts(r["entry_block"]), UTC).strftime("%Y-%m")
        for v in EXIT_VARIANTS:
            x = r["returns"].get(v)
            if x is not None:
                regimes[month][v].append(x)
    regime_summary = {}
    for month, byv in sorted(regimes.items()):
        regime_summary[month] = {
            v: {"n": len(xs),
                "mean_net_return": (sum(xs) / len(xs)) if xs else None}
            for v, xs in byv.items()}

    # Fee-tier breakdown (primary variant hold_24h).
    fee_summary = {}
    bucket = defaultdict(list)
    for r in qualifying:
        x = r["returns"].get("hold_24h")
        if x is not None:
            bucket[r["fee"]].append(x)
    for fee, xs in sorted(bucket.items()):
        fee_summary[str(fee)] = {"n": len(xs), "mean_net_return": sum(xs) / len(xs)}

    # Pass bar: mean>0 AND Holm p<0.10 for at least one variant.
    passes = [v for v in EXIT_VARIANTS
              if per_variant[v]["mean_net_return"] is not None
              and per_variant[v]["mean_net_return"] > 0
              and per_variant[v]["p_value_holm"] is not None
              and per_variant[v]["p_value_holm"] < 0.10]
    enough = len(qualifying) >= 200
    verdict = "PASS" if (passes and enough) else "FAIL"

    return {
        "funnel": funnel,
        "per_variant": per_variant,
        "regime_by_month": regime_summary,
        "by_fee_tier_hold_24h": fee_summary,
        "pass_bar": {"min_qualifying": 200, "qualifying": len(qualifying),
                     "n_sufficient": enough, "variants_passing": passes,
                     "verdict": verdict},
    }


# --- Trials ledger ------------------------------------------------------------
def record_trials(run_id: str, analysis: dict, params: dict, commit: str) -> dict:
    key = "rhmeme_" + hashlib.sha256(run_id.encode()).hexdigest()[:24]
    with Session(local_engine(), expire_on_commit=False) as session:
        if session.scalar(select(Strategy.id).where(Strategy.key == key)):
            raise ValueError(f"run already recorded: {run_id}; pick a new run-id")
        strat = Strategy(
            key=key, name=f"Robinhood Chain memecoin snipe base-rate {run_id}",
            status="backtest", allocation_usd=D(140),
            description="Stage-1 dumb gated buy-every-new-pool rule; no Jev, no wallet.",
            config={"research_only": True, "parent_strategy": "jevup_robinhood_memecoins",
                    **params})
        session.add(strat); session.commit(); sid = strat.id
        trial_ids = {}
        for v in EXIT_VARIANTS:
            pv = analysis["per_variant"][v]
            trial = Trial(
                strategy_id=sid, mode="backtest",
                params={"exit_variant": v, "run_id": run_id, **params},
                git_commit=commit, code_version="rhmeme-v1",
                status="complete", completed_ts=datetime.now(UTC),
                trade_count=pv["n"],
                pnl=(D(str(pv["total_net_usd"])) if pv["total_net_usd"] is not None else None),
                pnl_after_fees=(D(str(pv["total_net_usd"])) if pv["total_net_usd"] is not None else None),
                win_rate=(D(str(round(pv["win_rate"], 4))) if pv["win_rate"] is not None else None),
                max_drawdown=(D(str(pv["max_drawdown_usd"])) if pv["max_drawdown_usd"] is not None else None),
                luck_p_value=(D(str(round(pv["p_value_one_sided"], 6))) if pv["p_value_one_sided"] is not None else None),
                metrics={**pv, "holm_p_value": pv["p_value_holm"],
                         "funnel": analysis["funnel"]},
                notes=(f"Exit '{v}'. Pass-bar verdict (whole study): "
                       f"{analysis['pass_bar']['verdict']}. Mean net return "
                       f"{pv['mean_net_return']}. No real execution; log-reconstructed."))
            session.add(trial); session.commit()
            trial_ids[v] = trial.id
    return {"strategy_id": sid, "strategy_key": key, "trial_ids": trial_ids}


# --- Runner -------------------------------------------------------------------
def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--sample", type=int, default=2500)
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--cache-dir", type=Path, default=Path("data/robinhood_chain"))
    ap.add_argument("--out-dir", type=Path, default=Path("docs/research"))
    ap.add_argument("--refresh-context", action="store_true")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--analyze-only", action="store_true")
    args = ap.parse_args()

    rpc = rc.RpcClient()
    head, clock, oracle = load_context(rpc, args.cache_dir, args.refresh_context)
    genesis = datetime.fromtimestamp(clock.t0, UTC)
    print(f"head={head} genesis={genesis:%Y-%m-%d} secs/block={clock.secs_per_block:.4f} "
          f"oracle_points={len(oracle._blocks)}")

    # Sampling frame: leave a full 24h window after every launch.
    hi = clock.block_at(clock.ts(head) - MAX_HOLD_SECONDS)
    lo = 1
    cand_path = args.cache_dir / f"candidates_{args.run_id}.json"
    if cand_path.exists():
        cands = json.loads(cand_path.read_text())
    else:
        cands = sample_pools(rpc, lo, hi, args.sample, seed=args.seed)
        cand_path.write_text(json.dumps(cands))
    print(f"sampled {len(cands)} WETH-paired pools over blocks [{lo},{hi}]")

    cache_path = args.cache_dir / f"launches_{args.run_id}.jsonl"
    if not args.analyze_only:
        collect(rpc, clock, oracle, head, cands, cache_path)
    records = [json.loads(l) for l in cache_path.read_text().splitlines() if l.strip()]

    analysis = analyze(records, clock)
    params = {
        "position_usd": POSITION_USD, "latency_blocks": LATENCY_BLOCKS,
        "mev_haircut_bps_per_side": MEV_HAIRCUT_BPS_PER_SIDE,
        "gas_units_roundtrip": GAS_UNITS_ROUNDTRIP, "gas_price_gwei": GAS_PRICE_GWEI,
        "liquidity_gate_usd": LIQUIDITY_GATE_USD, "sample_target": args.sample,
        "seed": args.seed, "chain_id": rc.CHAIN_ID, "factory": rc.FACTORY,
        "weth": rc.WETH, "usdg": rc.USDG, "head_block": head,
        "genesis_date": f"{genesis:%Y-%m-%d}", "secs_per_block": clock.secs_per_block,
        "exit_variants": list(EXIT_VARIANTS),
    }
    commit = git_commit()
    artifact = {"run_id": args.run_id, "params": params, "analysis": analysis,
                "generated": datetime.now(UTC).isoformat()}

    if not args.no_ledger:
        artifact["ledger"] = record_trials(args.run_id, analysis, params, commit)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "08-robinhood-chain-memecoins-results.json"
    out.write_text(json.dumps(artifact, indent=2, default=str) + "\n")
    print(json.dumps({"funnel": analysis["funnel"],
                      "pass_bar": analysis["pass_bar"]}, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
