"""Unit tests for PRD §5 strategy #1 (favourite–longshot bias), driven purely
with a fake context — fast, no database. End-to-end fill/settlement behaviour is
covered by tests/backtest/test_favourite_longshot_runner.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradingbot.db import enums
from tradingbot.strategy.favourite_longshot import FavouriteLongshotBias
from tradingbot.strategy.interface import (
    CancelOrder,
    MarketEvent,
    MarketSnapshot,
    PlaceOrder,
    StrategyContext,
)

TS = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
D = Decimal


class FakeContext(StrategyContext):
    def __init__(self, *, now=TS, positions=None, snaps=None, resting=None, params=None):
        self._now = now
        self._positions = positions or {}
        self._snaps = snaps or {}
        self._resting = resting or {}
        self._params = params or {}

    @property
    def now(self):
        return self._now

    @property
    def mode(self):
        return enums.Mode.BACKTEST

    @property
    def params(self):
        return self._params

    def position(self, instrument_id):
        return self._positions.get(instrument_id, Decimal(0))

    def snapshot(self, instrument_id):
        return self._snaps.get(instrument_id)

    def resting_tags(self, instrument_id=None):
        if instrument_id is None:
            return tuple(t for ts in self._resting.values() for t in ts)
        return tuple(self._resting.get(instrument_id, ()))


def snap(iid, price):
    return MarketSnapshot(iid, TS, mid=D(price))


def quote(iid, price=None):
    return MarketEvent.quote(iid, TS, mid=D(price) if price is not None else None)


def _strat(**params):
    base = {"market_of": {"1": 100, "2": 100}, "siblings": {"1": [2], "2": [1]}}
    strat = FavouriteLongshotBias({**base, **params})
    return strat


# -- buy_favourite ----------------------------------------------------------
def test_buy_favourite_rests_maker_buy_below_the_favourite():
    strat = _strat(side_rule="buy_favourite", offset="0.02", size="10")
    ctx = FakeContext(snaps={1: snap(1, "0.60"), 2: snap(2, "0.40")})
    strat.on_start(ctx)
    (intent,) = strat.on_event(ctx, quote(1, "0.60"))
    assert isinstance(intent, PlaceOrder)
    assert intent.side == enums.Side.BUY
    assert intent.limit_price == D("0.58")  # 0.60 - 0.02
    assert intent.intended_liquidity == enums.Liquidity.MAKER
    assert intent.size == D("10")


def test_buy_favourite_ignores_the_longshot_side():
    strat = _strat(side_rule="buy_favourite")
    ctx = FakeContext(snaps={1: snap(1, "0.60"), 2: snap(2, "0.40")})
    strat.on_start(ctx)
    assert strat.on_event(ctx, quote(2, "0.40")) == []  # 0.40 < 0.5 threshold


def test_buy_favourite_skips_a_non_extreme_side_even_above_threshold():
    # Both sides above 0.5 can't happen in a binary market, but the guard is that
    # we only buy the *highest* outcome: 0.55 is not the favourite vs a 0.60 sibling.
    strat = _strat(side_rule="buy_favourite")
    ctx = FakeContext(snaps={1: snap(1, "0.55"), 2: snap(2, "0.60")})
    strat.on_start(ctx)
    assert strat.on_event(ctx, quote(1, "0.55")) == []


# -- sell_longshot ----------------------------------------------------------
def test_sell_longshot_rests_maker_sell_above_the_longshot():
    strat = _strat(side_rule="sell_longshot", offset="0.02", size="10")
    ctx = FakeContext(snaps={1: snap(1, "0.30"), 2: snap(2, "0.70")})
    strat.on_start(ctx)
    (intent,) = strat.on_event(ctx, quote(1, "0.30"))
    assert intent.side == enums.Side.SELL
    assert intent.limit_price == D("0.32")  # 0.30 + 0.02
    assert intent.intended_liquidity == enums.Liquidity.MAKER


# -- guards -----------------------------------------------------------------
def test_price_band_excludes_near_certain_favourites():
    strat = _strat(side_rule="buy_favourite", max_price="0.97")
    ctx = FakeContext(snaps={1: snap(1, "0.98"), 2: snap(2, "0.02")})
    strat.on_start(ctx)
    assert strat.on_event(ctx, quote(1, "0.98")) == []


def test_one_side_per_market_holds_a_single_outcome():
    strat = _strat(side_rule="buy_favourite")
    ctx = FakeContext(snaps={1: snap(1, "0.60"), 2: snap(2, "0.40")})
    strat.on_start(ctx)
    assert strat.on_event(ctx, quote(1, "0.60"))  # commits market 100 -> inst 1
    # The other outcome's price later rises above 0.5; we must not start it too.
    ctx._snaps[2] = snap(2, "0.55")
    ctx._snaps[1] = snap(1, "0.45")
    assert strat.on_event(ctx, quote(2, "0.55")) == []


def test_does_not_stack_a_second_order_while_one_rests():
    strat = _strat(side_rule="buy_favourite")
    ctx = FakeContext(snaps={1: snap(1, "0.60"), 2: snap(2, "0.40")},
                      resting={1: ("fl-1-0",)})
    strat.on_start(ctx)
    assert strat.on_event(ctx, quote(1, "0.60")) == []


def test_fill_cap_cancels_the_resting_remainder():
    strat = _strat(side_rule="buy_favourite", max_fills_per_market=2)
    ctx = FakeContext(snaps={1: snap(1, "0.60"), 2: snap(2, "0.40")})
    strat.on_start(ctx)
    # Grow the position twice (two fill episodes) with an order still resting.
    ctx._positions[1] = D("10")
    ctx._resting[1] = ("fl-1-0",)
    strat.on_event(ctx, quote(1, "0.60"))  # fills -> 1
    ctx._positions[1] = D("20")
    out = strat.on_event(ctx, quote(1, "0.60"))  # fills -> 2 == cap
    assert out == [CancelOrder(tag="fl-1-0")]


def test_blackout_pulls_quotes_before_the_scheduled_event():
    event_ts = TS + timedelta(seconds=100)
    strat = _strat(
        side_rule="buy_favourite",
        entry_blackout_seconds=200,
        event_ts={"1": event_ts.isoformat()},
    )
    ctx = FakeContext(now=TS, snaps={1: snap(1, "0.60"), 2: snap(2, "0.40")},
                      resting={1: ("fl-1-0",)})
    strat.on_start(ctx)
    # now (TS) is within 200s before event_ts, so we cancel and never enter.
    assert strat.on_event(ctx, quote(1, "0.60")) == [CancelOrder(tag="fl-1-0")]
