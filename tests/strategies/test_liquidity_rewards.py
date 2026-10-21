from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tradingbot.strategy import CancelOrder, MarketEvent, PlaceOrder
from tradingbot.strategy.liquidity_rewards import LiquidityRewards, Terms, instant, qualifying_book, score_share, side_depth
from tradingbot.research.liquidity_rewards import rank_markets

NOW = instant("2026-09-30T18:00:00Z")


def terms(**kw):
    return {"program_id": "verified-test-period", "start": "2026-09-30T04:00:00Z", "end": "2026-10-01T04:00:00Z",
            "observed_at": "2026-09-30T17:59:00Z", "pool": "100", "target": "100", "discount": ".3", "tick": ".01",
            "status": "active", "pool_scope": "verified_market_period", **kw}


def book(**kw):
    return {"state": "open", "observed_at": NOW.isoformat(), "bids": [[".49", "50"], [".48", "60"], [".47", "500"]],
            "asks": [[".51", "100"], [".52", "100"]], **kw}


def params(**kw):
    return {"clip": "5", "markets": {"1": {"market_id": 7, "terms": terms(), "reviewed_non_sports": True,
            "insider_exposed": False, "review_note": "test-only public index review", "selected": True,
            "ranked_at": NOW.isoformat(), "minimum_quantity": ".01", "event_times": [],
            "events_reviewed_through": "2026-10-01T04:00:00Z"}}, **kw}


class Context:
    def __init__(self, mode="backtest"):
        self.now, self.mode = NOW, mode
        self.positions, self.tags = {}, {}

    def position(self, iid): return self.positions.get(iid, D(0))
    def resting_tags(self, iid=None): return tuple(self.tags.get(iid, ()))
    def snapshot(self, iid): return None


def event(*, raw=None, fills=None, complete=True, iid=1):
    return MarketEvent.quote(iid, NOW, meta={"full_book": raw or book(), "own_fills_complete": complete, "own_fills": fills or []})


def receipt(fid="a", side="buy", size="5", iid=1, at=NOW):
    return {"id": fid, "instrument_id": iid, "side": side, "size": size, "time": at.isoformat()}


def started(p=None, mode="backtest"):
    strategy, ctx = LiquidityRewards(p or params()), Context(mode)
    strategy.on_start(ctx)
    return strategy, ctx


def test_depth_uses_raw_target_and_entire_final_level():
    t = Terms.from_dict(terms())
    side = side_depth(book()["bids"], side="buy", terms=t)
    assert side.cutoff == D(".48") and side.raw_size == 110
    assert side.score == 68  # 50 at best + 60 * .3, not a truncated 50
    assert len(side.levels) == 2
    assert side_depth([[".49", "99"]], side="buy", terms=t) is None


def test_same_price_levels_aggregate_before_target_cutoff():
    t = Terms.from_dict(terms())
    side = side_depth([[".49", "100"], [".49", "100"], [".48", "500"]], side="buy", terms=t)
    assert side.raw_size == 200 and len(side.levels) == 1


def test_max_spread_uses_target_prices_and_equality_passes():
    t = Terms.from_dict(terms(max_spread=".015"))
    assert all(qualifying_book(book(), t))  # .51 - .48 == .03
    t = Terms.from_dict(terms(max_spread=".014"))
    assert qualifying_book(book(), t) == (None, None)
    thin = book(asks=[[".51", "99"]])
    assert qualifying_book(thin, Terms.from_dict(terms(max_spread=".1"))) == (None, None)
    buy, sell = qualifying_book(thin, Terms.from_dict(terms()))
    assert buy is not None and sell is None


def test_scoring_rewalks_with_own_order_and_has_no_payout_claim():
    t = Terms.from_dict(terms())
    assert score_share(book()["bids"], side="buy", price=".47", quantity="5", terms=t) == 0
    assert score_share(book()["bids"], side="buy", price=".49", quantity="50", terms=t) == D(".5")
    assert score_share([[".49", "95"]], side="buy", price=".49", quantity="5", terms=t) == D(".05")


@pytest.mark.parametrize("mode", ["backtest", "paper", "live"])
def test_same_strategy_two_sided_maker_in_every_mode(mode):
    strategy, ctx = started(mode=mode)
    intents = strategy.on_event(ctx, event())
    assert [(i.side, i.size, i.limit_price, i.intended_liquidity) for i in intents] == [
        ("buy", D(5), D(".49"), "maker"), ("sell", D(5), D(".51"), "maker")]


def test_cancel_ack_required_before_replacing():
    strategy, ctx = started()
    first = strategy.on_event(ctx, event())
    ctx.tags[1] = [i.tag for i in first]
    changed = book(bids=[[".48", "100"]], asks=[[".50", "100"]])
    assert all(isinstance(i, CancelOrder) for i in strategy.on_event(ctx, event(raw=changed)))
    assert all(isinstance(i, CancelOrder) for i in strategy.on_event(ctx, event(raw=changed)))
    ctx.tags[1] = []
    replacement = strategy.on_event(ctx, event(raw=changed))
    assert all(isinstance(i, PlaceOrder) for i in replacement)
    assert not set(i.tag for i in first) & set(i.tag for i in replacement)


@pytest.mark.parametrize("position", ["30", "-30", "50", "-50"])
def test_at_or_above_inventory_cap_only_reduce_never_flip(position):
    p = params(clip="100", max_fills=100)
    strategy, ctx = started(p)
    ctx.positions[1] = D(position)
    side = "buy" if D(position) > 0 else "sell"
    raw = book(bids=[[".49", "100"]], asks=[[".50", "100"]])
    intents = strategy.on_event(ctx, event(raw=raw, fills=[receipt(side=side, size=str(abs(D(position))))]))
    assert len(intents) == 1
    assert intents[0].side != side and intents[0].size <= abs(D(position))


def test_pending_quote_size_cannot_take_inventory_above_15():
    strategy, ctx = started(params(clip="100", max_fills=100))
    ctx.positions[1] = D(20)
    intents = strategy.on_event(ctx, event(fills=[receipt(size="20")]))
    buy, sell = intents
    assert (ctx.position(1) + buy.size) * D(".51") <= 15
    assert max(D(0), sell.size - ctx.position(1)) * D(".51") <= 15


def test_actual_batched_and_offsetting_fills_count_not_net_position():
    strategy, ctx = started(params(max_fills=2))
    ctx.tags[1] = [i.tag for i in strategy.on_event(ctx, event())]
    fills = [receipt("one", "buy", "1"), receipt("two", "sell", "1")]
    assert all(isinstance(i, CancelOrder) for i in strategy.on_event(ctx, event(fills=fills)))
    assert len(strategy.fill_times[1]) == 2 and ctx.position(1) == 0
    strategy.on_event(ctx, event(fills=fills))
    assert len(strategy.fill_times[1]) == 2  # duplicate receipts do not count again
    ctx.tags[1] = []
    ctx.now += timedelta(seconds=60)
    assert len(strategy.on_event(ctx, event(raw=book(observed_at=ctx.now.isoformat())))) == 2


@pytest.mark.parametrize("fault", ["missing", "mismatch", "conflict", "future"])
def test_fill_uncertainty_halts_quoting(fault):
    strategy, ctx = started(params(max_fills=100))
    ctx.tags[1] = [i.tag for i in strategy.on_event(ctx, event())]
    fills, complete = [], True
    if fault == "missing": complete = False
    if fault == "mismatch": ctx.positions[1] = D(1)
    if fault == "conflict": fills = [receipt(), receipt(size="6")]
    if fault == "future": fills = [receipt(at=NOW + timedelta(seconds=1))]
    result = strategy.on_event(ctx, event(fills=fills, complete=complete))
    assert result and all(isinstance(i, CancelOrder) for i in result)
    assert strategy.execution_unknown
    ctx.tags[1] = []
    assert not strategy.on_event(ctx, event())


@pytest.mark.parametrize("fault", ["insider", "sports_review", "calendar", "blackout", "rank_day", "rank_future", "terms_future", "stale", "depth", "crossed"])
def test_evidence_and_adverse_selection_guards(fault):
    p, raw = params(), book()
    m = p["markets"]["1"]
    if fault == "insider": m["insider_exposed"] = True
    if fault == "sports_review": m["reviewed_non_sports"] = False
    if fault == "calendar": m["events_reviewed_through"] = NOW.isoformat()
    if fault == "blackout": m["event_times"] = [(NOW + timedelta(seconds=299)).isoformat()]
    if fault == "rank_day": m["ranked_at"] = (NOW - timedelta(days=1)).isoformat()
    if fault == "rank_future": m["ranked_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if fault == "terms_future": m["terms"]["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if fault == "stale": raw["observed_at"] = (NOW - timedelta(seconds=31)).isoformat()
    if fault == "depth": raw["bids"] = [[".49", "1"]]
    if fault == "crossed": raw["asks"] = [[".48", "100"]]
    strategy, ctx = started(p)
    ctx.tags[1] = ["existing-buy", "existing-sell"]
    result = strategy.on_event(ctx, event(raw=raw))
    assert len(result) == 2 and all(isinstance(i, CancelOrder) for i in result)


def candidate(iid=1, pool="100"):
    return {"instrument_id": iid, "market_slug": f"test-{iid}", "terms": terms(pool=pool), "book": book(),
            "reviewed_non_sports": True, "insider_exposed": False, "review_note": "test review"}


def test_daily_rank_pool_per_competing_depth_with_deterministic_ties():
    ranked, rejected = rank_markets([candidate(2), candidate(3, "200"), candidate(1)], at=NOW)
    assert [r.instrument_id for r in ranked] == [3, 1, 2] and rejected == []
    assert D(ranked[0].competing_depth) == 210


def test_ranking_never_sums_repeated_template_pools_and_rejects_unknown_scope():
    a, b = candidate(1), candidate(1)
    ranked, rejected = rank_markets([a, b], at=NOW)
    assert len(ranked) == 1 and D(ranked[0].pool) == 100 and len(rejected) == 1
    a["terms"]["pool_scope"] = "public_template_only"
    assert rank_markets([a], at=NOW)[0] == []


def test_future_rank_data_and_unsafe_markets_are_excluded():
    a, b, c = candidate(1), candidate(2), candidate(3)
    a["book"]["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    b["insider_exposed"] = True
    c["terms"]["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    ranked, rejected = rank_markets([a, b, c], at=NOW)
    assert ranked == [] and len(rejected) == 3


def test_recent_fill_history_keeps_rolling_guard_after_flat_restart():
    strategy, ctx = started()
    e = event()
    e.meta["own_fill_history"] = [receipt("old-buy", "buy", "1", at=NOW - timedelta(seconds=10)),
                                receipt("old-sell", "sell", "1", at=NOW - timedelta(seconds=9))]
    assert strategy.on_event(ctx, e) == []
    assert not strategy.execution_unknown and len(strategy.fill_times[1]) == 2
    ctx.now += timedelta(seconds=60)
    assert len(strategy.on_event(ctx, event(raw=book(observed_at=ctx.now.isoformat())))) == 2
