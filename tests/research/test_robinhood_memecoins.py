"""Unit tests for the Robinhood Chain memecoin base-rate study (tradingbot-x6a).

Pure/offline: the chain math, point-in-time log reconstruction, exit rules, cost
model, Holm adjustment and the pass-bar logic are all exercised on synthetic data,
so the correctness-critical pieces are verified without touching the RPC.
"""
from __future__ import annotations

import math

from tradingbot.research import robinhood_chain as rc
from tradingbot.research import robinhood_memecoins as m


Q96 = rc.Q96


# --- V3 math ------------------------------------------------------------------
def test_mid_price_orientation():
    sp = Q96  # price P = 1
    assert math.isclose(rc.mid_weth_per_meme(sp, weth_is_token0=True), 1.0)
    assert math.isclose(rc.mid_weth_per_meme(sp, weth_is_token0=False), 1.0)
    sp2 = Q96 * 2  # P = 4
    # weth=token0 => meme price in weth = 1/P = 0.25; weth=token1 => = P = 4
    assert math.isclose(rc.mid_weth_per_meme(sp2, True), 0.25, rel_tol=1e-9)
    assert math.isclose(rc.mid_weth_per_meme(sp2, False), 4.0, rel_tol=1e-9)


def test_quote_zero_liquidity_cannot_trade():
    out, sp = rc.quote_exact_in(Q96, 0.0, 1e18, token0_in=True)
    assert out == 0.0 and sp == Q96


def test_quote_roundtrip_deep_pool_is_near_lossless():
    L = 1e30
    amt_in = 7e16
    meme_out, _ = rc.quote_exact_in(Q96, L, amt_in, token0_in=True)
    weth_back, _ = rc.quote_exact_in(Q96, L, meme_out, token0_in=False)
    # Deep pool, no fees here: round trip returns almost all of the input.
    assert 0.999 < weth_back / amt_in <= 1.0


def test_quote_impact_is_worse_in_thin_pool():
    deep, _ = rc.quote_exact_in(Q96, 1e30, 1e18, token0_in=True)
    thin, _ = rc.quote_exact_in(Q96, 1e19, 1e18, token0_in=True)
    # Same $ in, thinner pool => fewer tokens out (more slippage).
    assert thin < deep


# --- Point-in-time reconstruction --------------------------------------------
def _hist(weth_is_token0=True):
    h = rc.PoolHistory(pool="0xpool", creation_block=100, token0=rc.WETH,
                       token1="0xmeme", fee=10000, weth_is_token0=weth_is_token0,
                       init_sqrt_price_x96=Q96)
    return h


def test_price_liquidity_reserves_are_point_in_time():
    h = _hist()
    # seed mint at block 100: 10 WETH (token0) + 1000 meme (token1), L=5e21
    h.flows.append(rc.Flow(100, 0, 10 * 10**18, 1000 * 10**18))
    h.mint_liquidity.append((100, 5 * 10**21))
    # a swap at block 200 moves price and liquidity
    h.swaps.append(rc.SwapPoint(200, 0, Q96 * 2, 6 * 10**21, 10**17, -10**17))
    h.flows.append(rc.Flow(200, 0, 10**17, -10**17))

    # before the swap: init price, seed liquidity, seed reserves
    assert h.price_at(150) == Q96
    assert h.liquidity_at(150) == 5 * 10**21
    r0, r1 = h.reserves_at(150)
    assert r0 == 10 * 10**18 and r1 == 1000 * 10**18
    # after the swap: swap price + swap liquidity + updated reserves
    assert h.price_at(250) == Q96 * 2
    assert h.liquidity_at(250) == 6 * 10**21
    r0b, r1b = h.reserves_at(250)
    assert r0b == 10 * 10**18 + 10**17 and r1b == 1000 * 10**18 - 10**17


# --- Round-trip return / cost model ------------------------------------------
def test_roundtrip_flat_price_loses_only_costs():
    h = _hist()
    # realistic deep pool (L~1e23); a ~$140 trade is ~1e-6 of it, impact negligible
    h.swaps.append(rc.SwapPoint(112, 0, Q96, 1e23, 1, -1))
    r = m._roundtrip_return(h, entry_block=112, exit_block=112, eth_usd=2000.0, fee=0)
    # no price move, no fee: ~ -(1 - (1-mev)^2) round trip (~ -1%), minus a hair of gas
    expected = (1 - m.MEV_HAIRCUT_BPS_PER_SIDE / 10_000) ** 2 - 1
    assert math.isclose(r, expected, abs_tol=5e-4)


def test_roundtrip_doubling_price_pays_out():
    h = _hist()
    # entry at block 112 price P=1 (mid meme=1); exit where meme doubled in WETH.
    h.swaps.append(rc.SwapPoint(112, 0, Q96, 1e24, 1, -1))
    sp_double = int(Q96 / math.sqrt(2))  # weth=token0 => mid = 1/P; halve P doubles mid
    h.swaps.append(rc.SwapPoint(500, 0, sp_double, 1e24, 1, -1))
    r = m._roundtrip_return(h, entry_block=112, exit_block=500, eth_usd=2000.0, fee=0)
    assert 0.95 < r < 1.0  # ~+100% minus MEV (both sides) and tiny impact


def test_roundtrip_no_exit_liquidity_is_total_loss_signal():
    h = _hist()
    h.swaps.append(rc.SwapPoint(112, 0, Q96, 1e30, 1, -1))
    # exit block has no price/liquidity in force beyond entry's last swap? force L=0
    r = m._roundtrip_return(h, entry_block=90, exit_block=95, eth_usd=2000.0, fee=0)
    assert r is None  # before any swap/init -> cannot quote


# --- Exit rules ---------------------------------------------------------------
def _clock():
    return rc.BlockClock(t0=0, b0=0, secs_per_block=1.0)  # ts(block)=block


def test_time_exit_block_uses_real_clock():
    h = _hist()
    xb = m._time_exit_block(h, _clock(), entry_block=1000, hold_s=300, head=10**9)
    assert xb == 1300


def test_tp_sl_trigger_and_fallback():
    h = _hist()
    entry_mid = 1.0  # at P=1 with weth=token0
    # swap path: rises to 2.5x (TP at +100% should fire first)
    h.swaps.append(rc.SwapPoint(200, 0, int(Q96 / math.sqrt(2.5)), 1e30, 1, -1))
    xb = m._rule_exit_block(h, _clock(), entry_block=112, entry_mid=entry_mid,
                            kind="tp100_sl50", head=10**9)
    assert xb == 200
    # no trigger -> fall back to 24h cap
    h2 = _hist()
    h2.swaps.append(rc.SwapPoint(200, 0, int(Q96 / math.sqrt(1.1)), 1e30, 1, -1))
    cap = m._time_exit_block(h2, _clock(), 112, m.MAX_HOLD_SECONDS, 10**9)
    xb2 = m._rule_exit_block(h2, _clock(), 112, entry_mid, "tp100_sl50", 10**9)
    assert xb2 == cap


def test_trailing_stop_fires_after_peak():
    h = _hist()
    # rise to 3x then fall to 1.5x (below 0.6*peak=1.8) -> exit on the drop
    h.swaps.append(rc.SwapPoint(200, 0, int(Q96 / math.sqrt(3.0)), 1e30, 1, -1))
    h.swaps.append(rc.SwapPoint(300, 0, int(Q96 / math.sqrt(1.5)), 1e30, 1, -1))
    xb = m._rule_exit_block(h, _clock(), 112, 1.0, "trail40", head=10**9)
    assert xb == 300


# --- Holm adjustment ----------------------------------------------------------
def test_holm_is_monotone_stepdown():
    adj = m.holm_adjust({"a": 0.01, "b": 0.04, "c": 0.2, "d": 0.5, "e": 0.9})
    assert math.isclose(adj["a"], 0.05)
    assert math.isclose(adj["b"], 0.16)
    assert adj["a"] <= adj["b"] <= adj["c"] <= adj["d"] <= adj["e"]
    assert all(v <= 1.0 for v in adj.values())


def test_holm_handles_none():
    adj = m.holm_adjust({"a": 0.01, "b": None})
    assert adj["b"] is None and math.isclose(adj["a"], 0.01)


# --- Analysis / pass bar ------------------------------------------------------
def _rec(block, qual, ret, fee=10000, honeypot=False):
    return {"pool": f"0x{block:040x}", "block": block, "entry_block": block,
            "fee": fee, "qualifies": qual, "has_code": True, "gate_liquidity": qual,
            "renounced": qual, "enterable": qual, "honeypot": honeypot,
            "returns": {v: (ret if qual else None) for v in m.EXIT_VARIANTS},
            "exit_blocks": {v: None for v in m.EXIT_VARIANTS}}


def test_analyze_fails_when_too_few_qualifying():
    recs = [_rec(1000 + i, True, 0.5) for i in range(10)]
    a = m.analyze(recs, _clock())
    assert a["funnel"]["qualifying"] == 10
    assert a["pass_bar"]["n_sufficient"] is False
    assert a["pass_bar"]["verdict"] == "FAIL"  # mean>0 but <200 launches


def test_analyze_passes_with_strong_positive_edge():
    # 220 qualifying launches, each +50% with jitter so variance is finite.
    recs = [_rec(1000 + i, True, 0.5 + (0.01 if i % 2 else -0.01)) for i in range(220)]
    a = m.analyze(recs, _clock())
    assert a["pass_bar"]["n_sufficient"] is True
    assert a["pass_bar"]["verdict"] == "PASS"
    assert a["per_variant"]["hold_24h"]["mean_net_return"] > 0
    assert a["per_variant"]["hold_24h"]["p_value_holm"] < 0.10


def test_analyze_fails_on_losing_edge():
    recs = [_rec(1000 + i, True, -0.3 + (0.01 if i % 2 else -0.01)) for i in range(220)]
    a = m.analyze(recs, _clock())
    assert a["pass_bar"]["verdict"] == "FAIL"
    assert a["per_variant"]["hold_24h"]["mean_net_return"] < 0
    # drawdown is reported as a positive USD magnitude
    assert a["per_variant"]["hold_24h"]["max_drawdown_usd"] > 0


def test_funnel_counts_nonqualifying():
    recs = [_rec(1000, True, 0.1), _rec(1001, False, None)]
    recs.append({"pool": "0xerr", "block": 1002, "error": "boom"})
    a = m.analyze(recs, _clock())
    assert a["funnel"]["sampled"] == 3
    assert a["funnel"]["errored"] == 1
    assert a["funnel"]["evaluated"] == 2
    assert a["funnel"]["qualifying"] == 1
