"""Read-only Robinhood Chain access for the memecoin base-rate study (tradingbot-x6a).

Everything here is archive-free: the public RPC is a *pruned* node (historical
``eth_call`` at old blocks returns "historical state not available"), so all
point-in-time state — prices, reserves, liquidity, ownership — is rebuilt from
**event logs**, which the node does serve for the full range.

No wallet, no signing, no transactions. Only ``eth_blockNumber``,
``eth_getLogs``, ``eth_getBlockByNumber`` and ``eth_call`` against *latest* (for
immutable token metadata and the factory ``getPool`` view) are used.

Verified constants (see ``docs/research/08-robinhood-chain-memecoins-plan.md``):
  * Chain ID 4663 (0x1237) -- confirmed live from the chain itself via
    ``eth_chainId``/``net_version``, and matches docs.robinhood.com/chain.
  * UniswapV3Factory -- from Uniswap's official developer docs
    (developers.uniswap.org/.../v3-robinhood-chain-deployments), NOT from the
    referral post, which is treated as hostile/poisoned input.
  * WETH -- from docs.robinhood.com/chain/protocol-contracts (L2 bridge token),
    and independently the dominant quote asset across PoolCreated events.
  * USDG "Global Dollar" (Paxos, 6 decimals) -- the chain's USD stablecoin,
    used only as an on-chain ETH/USD oracle (deepest WETH/USDG pool).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time

import requests
from eth_hash.auto import keccak

# --- Verified chain constants -------------------------------------------------
RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
CHAIN_ID = 4663
FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
WETH_DECIMALS = 18
USDG_DECIMALS = 6
ZERO_ADDR = "0x0000000000000000000000000000000000000000"

Q96 = 2 ** 96


def _topic(sig: str) -> str:
    return "0x" + keccak(sig.encode()).hex()


# Event topic0s (Uniswap V3 pool + OpenZeppelin Ownable).
T_POOL_CREATED = _topic("PoolCreated(address,address,uint24,int24,address)")
T_INITIALIZE = _topic("Initialize(uint160,int24)")
T_MINT = _topic("Mint(address,address,int24,int24,uint128,uint256,uint256)")
T_BURN = _topic("Burn(address,int24,int24,uint128,uint256,uint256)")
T_SWAP = _topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
T_OWNERSHIP = _topic("OwnershipTransferred(address,address)")


# --- Decoding helpers ---------------------------------------------------------
def _u(hexword: str) -> int:
    return int(hexword, 16)


def _i(hexword: str) -> int:
    v = int(hexword, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def _addr(topic: str) -> str:
    return "0x" + topic[-40:]


def _words(data_hex: str) -> list[str]:
    h = data_hex[2:] if data_hex.startswith("0x") else data_hex
    return [h[i:i + 64] for i in range(0, len(h), 64)]


# --- RPC client ---------------------------------------------------------------
class RpcError(RuntimeError):
    pass


class RpcClient:
    """Minimal JSON-RPC client with 429/backoff and adaptive ``eth_getLogs``.

    ``request_count`` counts wire calls so studies can report their RPC cost.
    """

    def __init__(self, url: str = RPC_URL, *, sleep: float = 0.08, max_tries: int = 9):
        self.url = url
        self.sleep = sleep
        self.max_tries = max_tries
        self.session = requests.Session()
        self.request_count = 0

    def call(self, method: str, params: list):
        delay = 1.0
        for attempt in range(self.max_tries):
            try:
                self.request_count += 1
                r = self.session.post(
                    self.url,
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                    timeout=90,
                )
                if r.status_code == 429:
                    time.sleep(delay); delay = min(delay * 2, 30); continue
                j = r.json()
                if "error" in j:
                    msg = j["error"].get("message", str(j["error"]))
                    low = msg.lower()
                    if ("exceeds limit" in low or "timed out" in low
                            or "narrow the block range" in low or "are allowed" in low):
                        return ("SPLIT", msg)
                    if "too many" in low or "rate" in low:
                        time.sleep(delay); delay = min(delay * 2, 30); continue
                    return ("ERR", msg)
                if self.sleep:
                    time.sleep(self.sleep)
                return ("OK", j["result"])
            except requests.exceptions.RequestException:
                time.sleep(delay); delay = min(delay * 2, 30)
        return ("ERR", "exhausted retries")

    def call_ok(self, method: str, params: list):
        status, res = self.call(method, params)
        if status != "OK":
            raise RpcError(f"{method} failed: {res}")
        return res

    def block_number(self) -> int:
        return _u(self.call_ok("eth_blockNumber", []))

    def block_timestamp(self, block: int) -> int:
        r = self.call_ok("eth_getBlockByNumber", [hex(block), False])
        return _u(r["timestamp"])

    def get_logs(self, *, address=None, topics=None, from_block=0, to_block="latest",
                 out: list | None = None) -> list:
        """``eth_getLogs`` with recursive range-splitting on the node's result-cap
        and query-timeout errors. Returns raw log dicts."""
        out = [] if out is None else out
        hi = to_block if isinstance(to_block, int) else self.block_number()
        self._get_logs_range(address, topics, int(from_block), int(hi), out)
        return out

    def _get_logs_range(self, address, topics, lo, hi, out):
        flt: dict = {"fromBlock": hex(lo), "toBlock": hex(hi)}
        if address is not None:
            flt["address"] = address
        if topics is not None:
            flt["topics"] = topics
        status, res = self.call("eth_getLogs", [flt])
        if status == "OK":
            out.extend(res)
            return
        if status == "SPLIT" and hi > lo:
            mid = (lo + hi) // 2
            self._get_logs_range(address, topics, lo, mid, out)
            self._get_logs_range(address, topics, mid + 1, hi, out)
            return
        raise RpcError(f"getLogs {lo}-{hi} failed: {res}")

    def eth_call(self, to: str, data: str, block="latest"):
        tag = block if isinstance(block, str) else hex(block)
        status, res = self.call("eth_call", [{"to": to, "data": data}, tag])
        return res if status == "OK" else None


# --- Token metadata (immutable; read at latest) -------------------------------
def token_symbol(rpc: RpcClient, token: str) -> str | None:
    res = rpc.eth_call(token, "0x" + keccak(b"symbol()").hex()[:8])
    if not res or res == "0x":
        return None
    try:
        words = _words(res)
        if len(words) >= 2:
            length = int(words[1], 16)
            raw = "".join(words[2:])
            return bytes.fromhex(raw[: length * 2]).decode("utf-8", "replace")
        return bytes.fromhex(words[0]).rstrip(b"\x00").decode("utf-8", "replace")
    except Exception:
        return None


def has_code(rpc: RpcClient, address: str) -> bool:
    status, res = rpc.call("eth_getCode", [address, "latest"])
    return status == "OK" and bool(res) and res != "0x"


def token_owner(rpc: RpcClient, token: str) -> str:
    """Return ``owner()`` at latest as an address, or the sentinel ``"revert"`` if
    the token has no ``owner()`` function (non-Ownable / immutable)."""
    status, res = rpc.call("eth_call", [{"to": token,
                                         "data": "0x" + keccak(b"owner()").hex()[:8]},
                                        "latest"])
    if status != "OK" or not res or res == "0x":
        return "revert"
    return "0x" + res[-40:]


# --- Block <-> timestamp calibration ------------------------------------------
@dataclass
class BlockClock:
    """Linear block<->timestamp map, anchored on two real blocks. Robinhood Chain
    produces blocks at a near-constant cadence, so this is accurate to seconds."""
    t0: int          # timestamp of anchor block b0
    b0: int
    secs_per_block: float

    @classmethod
    def calibrate(cls, rpc: RpcClient, head: int | None = None) -> "BlockClock":
        head = head or rpc.block_number()
        b0, b1 = 1, head - 5
        t0 = rpc.block_timestamp(b0)
        t1 = rpc.block_timestamp(b1)
        return cls(t0=t0, b0=b0, secs_per_block=(t1 - t0) / (b1 - b0))

    def ts(self, block: int) -> float:
        return self.t0 + (block - self.b0) * self.secs_per_block

    def block_at(self, ts: float) -> int:
        return int(self.b0 + (ts - self.t0) / self.secs_per_block)


# --- Uniswap V3 math (floats; single active-range exact-input quote) ----------
def sqrt_price_to_float(sqrt_price_x96: int) -> float:
    return sqrt_price_x96 / Q96


def mid_weth_per_meme(sqrt_price_x96: int, weth_is_token0: bool) -> float:
    """Spot price of the memecoin denominated in WETH (raw ratio; token decimals
    cancel in every ratio and threshold the study uses)."""
    sp = sqrt_price_to_float(sqrt_price_x96)
    p = sp * sp  # token1/token0, raw
    if p == 0:
        return 0.0
    return (1.0 / p) if weth_is_token0 else p


def quote_exact_in(sqrt_price_x96: int, liquidity: float, amount_in: float,
                   *, token0_in: bool) -> tuple[float, int]:
    """Exact-input single-range Uniswap V3 quote. Returns (amount_out, new_sqrtX96).

    Valid while the swap stays within the active-liquidity range -- true for the
    ~$140 trades this study sizes, which are tiny beside a >=$20k pool. ``liquidity``
    is the active L; a non-positive L means the trade cannot execute."""
    if liquidity <= 0 or amount_in <= 0:
        return (0.0, sqrt_price_x96)
    sp = sqrt_price_to_float(sqrt_price_x96)
    L = liquidity
    if token0_in:
        # token0 in -> token1 out; price (t1/t0) falls, sqrtP decreases.
        new_sp = (L * sp) / (L + amount_in * sp)
        amount_out = L * (sp - new_sp)
    else:
        # token1 in -> token0 out; sqrtP increases.
        new_sp = sp + amount_in / L
        amount_out = L * (1.0 / sp - 1.0 / new_sp)
    return (max(amount_out, 0.0), int(new_sp * Q96))


# --- Pool reconstruction from logs --------------------------------------------
@dataclass
class SwapPoint:
    block: int
    log_index: int
    sqrt_price_x96: int
    liquidity: int
    amount0: int  # signed, pool's perspective (+ = into pool)
    amount1: int


@dataclass
class Flow:
    """A raw reserve delta from the pool's perspective (+ = token entered pool)."""
    block: int
    log_index: int
    d0: int
    d1: int


@dataclass
class PoolHistory:
    pool: str
    creation_block: int
    token0: str
    token1: str
    fee: int
    weth_is_token0: bool
    init_sqrt_price_x96: int | None = None
    swaps: list[SwapPoint] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)      # block-stamped reserve deltas
    mint_liquidity: list[tuple[int, int]] = field(default_factory=list)  # (block, L)
    n_mints: int = 0
    n_burns: int = 0
    n_meme_sells: int = 0   # honeypot proxy: real sells that cleared
    n_meme_buys: int = 0

    def price_at(self, block: int) -> int | None:
        """sqrtPriceX96 in force at ``block`` (last swap <= block, else init price).
        Price is piecewise-constant between swaps, so this is exact."""
        last = None
        for s in self.swaps:
            if s.block <= block:
                last = s.sqrt_price_x96
            else:
                break
        return last if last is not None else self.init_sqrt_price_x96

    def liquidity_at(self, block: int) -> float:
        """Active liquidity L at ``block``. Prefers the exact ``liquidity`` field of
        the most recent swap at/before ``block``; before the first swap, falls back
        to the sum of seed-mint L (assumes seeds straddle the launch tick -- true
        for ~all fresh launches)."""
        last = None
        for s in self.swaps:
            if s.block <= block:
                last = s.liquidity
            else:
                break
        if last is not None:
            return float(last)
        return float(sum(L for b, L in self.mint_liquidity if b <= block))

    def reserves_at(self, block: int) -> tuple[int, int]:
        """Net raw (reserve0, reserve1) at ``block`` from mint(+)/swap(signed) flows.
        Burn/Collect outflows are omitted -- negligible in the first seconds of a
        launch (the gate window) and, if anything, overstate liquidity, which only
        makes the strategy look better."""
        r0 = r1 = 0
        for f in self.flows:
            if f.block <= block:
                r0 += f.d0; r1 += f.d1
            else:
                break
        return r0, r1

    def first_swap_after(self, block: int) -> SwapPoint | None:
        for s in self.swaps:
            if s.block >= block:
                return s
        return None


def classify(topic0: str) -> str:
    return {T_INITIALIZE: "init", T_MINT: "mint", T_BURN: "burn", T_SWAP: "swap"}.get(
        topic0, "other")


def build_pool_history(rpc: RpcClient, pool: str, creation_block: int, token0: str,
                       token1: str, fee: int, end_block: int) -> PoolHistory:
    """Fetch and decode every pool event in [creation_block, end_block] into a
    point-in-time-queryable history. One ``eth_getLogs`` (auto-split if needed)."""
    weth_is_token0 = token0.lower() == WETH
    hist = PoolHistory(pool=pool, creation_block=creation_block, token0=token0,
                       token1=token1, fee=fee, weth_is_token0=weth_is_token0)
    logs = rpc.get_logs(address=pool, from_block=creation_block, to_block=end_block)
    logs.sort(key=lambda l: (_u(l["blockNumber"]), _u(l["logIndex"])))
    for lg in logs:
        kind = classify(lg["topics"][0])
        blk = _u(lg["blockNumber"]); li = _u(lg["logIndex"]); w = _words(lg["data"])
        if kind == "init":
            hist.init_sqrt_price_x96 = _u("0x" + w[0])
        elif kind == "mint":
            # data words: sender, amount(L), amount0, amount1
            L = _u("0x" + w[1]); a0 = _u("0x" + w[2]); a1 = _u("0x" + w[3])
            hist.flows.append(Flow(blk, li, a0, a1))
            hist.mint_liquidity.append((blk, L))
            hist.n_mints += 1
        elif kind == "burn":
            hist.n_burns += 1  # outflow realized on Collect; ignored for reserves
        elif kind == "swap":
            # data words: amount0, amount1, sqrtPriceX96, liquidity, tick
            a0 = _i("0x" + w[0]); a1 = _i("0x" + w[1])
            sp = _u("0x" + w[2]); liq = _u("0x" + w[3])
            hist.swaps.append(SwapPoint(blk, li, sp, liq, a0, a1))
            hist.flows.append(Flow(blk, li, a0, a1))
            # meme = non-WETH token; a sell pushes meme into the pool (that side > 0)
            meme_in = (a1 > 0) if weth_is_token0 else (a0 > 0)
            if meme_in:
                hist.n_meme_sells += 1
            else:
                hist.n_meme_buys += 1
    hist.flows.sort(key=lambda f: (f.block, f.log_index))
    return hist


# --- On-chain ETH/USD oracle (WETH/USDG pool) ---------------------------------
def get_pool(rpc: RpcClient, token_a: str, token_b: str, fee: int) -> str | None:
    sel = "0x" + keccak(b"getPool(address,address,uint24)").hex()[:8]
    data = sel + token_a[2:].rjust(64, "0") + token_b[2:].rjust(64, "0") + \
        hex(fee)[2:].rjust(64, "0")
    res = rpc.eth_call(FACTORY, data)
    if not res or res == "0x":
        return None
    pool = "0x" + res[-40:]
    return None if pool == ZERO_ADDR else pool


def _pool_token0(rpc: RpcClient, pool: str) -> str:
    res = rpc.eth_call(pool, "0x" + keccak(b"token0()").hex()[:8])
    return "0x" + res[-40:]


class EthUsdOracle:
    """ETH/USD across the chain's life, read from the deepest WETH/USDG Uniswap V3
    pool (archive-free). Sampled on a fixed block cadence (default ~daily): the
    pool's first swap in a small window at each sample block gives the spot. Coarse
    by design -- it feeds only the $20k liquidity gate and USD cost conversion, where
    seconds-level precision is irrelevant. Falls back across fee tiers for depth."""

    def __init__(self, rpc: RpcClient, head: int, clock: "BlockClock",
                 *, cadence_blocks: int | None = None, probe_window: int = 3_000,
                 cache: dict | None = None):
        self.rpc = rpc
        if cache:
            self.pool = cache["pool"]; self.weth_is_token0 = cache["weth_is_token0"]
            self._blocks = cache["blocks"]; self._prices = cache["prices"]
            return
        pool = None
        for fee in (100, 500, 3000, 10000):
            pool = get_pool(rpc, WETH, USDG, fee)
            if pool:
                break
        if pool is None:
            raise RpcError("no WETH/USDG oracle pool")
        self.pool = pool
        self.weth_is_token0 = _pool_token0(rpc, pool).lower() == WETH
        if cadence_blocks is None:
            cadence_blocks = max(1, int(round(86400 / clock.secs_per_block)))  # ~1 day
        self._blocks, self._prices = [], []
        b = 0
        while b <= head:
            logs = rpc.get_logs(address=pool, topics=[T_SWAP],
                                from_block=b, to_block=min(b + probe_window, head))
            if logs:
                logs.sort(key=lambda l: _u(l["blockNumber"]))
                w = _words(logs[0]["data"])
                self._blocks.append(_u(logs[0]["blockNumber"]))
                self._prices.append(self._to_usd(_u("0x" + w[2])))
            b += cadence_blocks
        if not self._prices:
            raise RpcError("oracle pool has no swaps in sampled windows")

    def _to_usd(self, sqrt_price_x96: int) -> float:
        p = (sqrt_price_x96 / Q96) ** 2  # token1/token0 raw
        scale = 10 ** (WETH_DECIMALS - USDG_DECIMALS)
        return (p * scale) if self.weth_is_token0 else ((1.0 / p) * scale)

    def at(self, block: int) -> float:
        import bisect
        i = bisect.bisect_right(self._blocks, block) - 1
        if i < 0:
            i = 0
        return self._prices[i]

    def to_cache(self) -> dict:
        return {"pool": self.pool, "weth_is_token0": self.weth_is_token0,
                "blocks": self._blocks, "prices": self._prices}
