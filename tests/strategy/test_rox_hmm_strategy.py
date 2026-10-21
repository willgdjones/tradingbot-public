"""Event-choreography tests for HmmRegimeStrategy (tradingbot-rox).

DB-free: a fake context + synthetic open/close stream exercise the
observe-close -> month-end decide -> next-open execute -> terminal-liquidate
choreography. The HMM kernel itself is tested in test_rox_hmm_regime.py, so here
`infer_regime` is monkeypatched to a fast, deterministic recent-mean rule.
"""
from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import numpy as np

import tradingbot.strategy.rox_hmm_regime as rox
from tradingbot.strategy.interface import MarketEvent
from tradingbot.strategy.rox_hmm_regime import HmmRegimeStrategy, RegimeInference

NY = ZoneInfo("America/New_York")
SPY = 1


def fake_infer(returns, params):
    recent = np.asarray(returns[-20:], dtype=float) if len(returns) else np.array([0.0])
    long_ok = bool(recent.mean() > 0)
    return RegimeInference(n_states=2, current_state=0 if long_ok else 1,
                           risk_off_state=1, state_means=(0.001, -0.001), long_ok=long_ok)


class Ctx:
    def __init__(self):
        self.qty = D(0)
        self.cash = D(140)
        self.equity = D(140)
        self.book = None
        self._now = None

    @property
    def now(self): return self._now
    @property
    def mode(self): return "backtest"
    @property
    def params(self): return {}
    def position(self, iid): return self.qty if iid == SPY else D(0)
    def snapshot(self, iid): return self.book if iid == SPY else None
    def resting_tags(self, iid=None): return ()
    def available_cash(self, iid): return self.cash
    def marked_equity(self): return self.equity


def _params(month_ends, **over):
    base = {"symbol_id": SPY, "month_ends": list(month_ends), "target_weight": "0.95",
            "cash_reserve_weight": "0.05", "buy_fee_reserve_usd": "0.01",
            "quantity_step": "0.000000001", "slot_usd": "140",
            "n_states": 2, "features": "ret", "min_obs": 1}
    base.update(over)
    return base


def _close(ctx, day, price, *, month_end, next_open_in_partition):
    ts = datetime.fromisoformat(day + "T16:00:00").replace(tzinfo=NY)
    ctx._now = ts
    ctx.book = None
    meta = {"phase": "close", "ex_date_distribution": "0"}
    if month_end:
        meta["next_open_in_partition"] = next_open_in_partition
    return MarketEvent.quote(SPY, ts, mid=D(str(price)), meta=meta)


def _open(ctx, day, price, *, terminal=False):
    ts = datetime.fromisoformat(day + "T09:30:00").replace(tzinfo=NY)
    ctx._now = ts
    p = D(str(price))
    ctx.book = MarketEvent.quote(SPY, ts, bid=p, ask=p, mid=p).as_snapshot()
    return MarketEvent.quote(SPY, ts, bid=p, ask=p, mid=p, meta={"phase": "open", "terminal_open": terminal})


def _apply(ctx, orders):
    """Minimal fill model so the long/flat toggle advances (fees ignored)."""
    for order in orders:
        if order.side == "buy":
            ctx.qty = order.size
            ctx.cash = ctx.cash - order.size * order.limit_price
        else:
            ctx.cash = ctx.cash + order.size * order.limit_price
            ctx.qty = D(0)
    return orders


def _month_days(prefix, n):
    return [f"{prefix}-{d:02d}" for d in range(1, n + 1)]


def _run(bot, ctx, series):
    """series: list of (day, open_px, close_px, is_month_end, is_terminal_open).
    Emits each day's open (applying returned orders) then close; a month-end close
    whose next open is outside the series is marked next_open_in_partition=False."""
    placed = []
    for i, (day, op, cp, me, term) in enumerate(series):
        placed += _apply(ctx, bot.on_event(ctx, _open(ctx, day, op, terminal=term)))
        bot.on_event(ctx, _close(ctx, day, cp, month_end=me, next_open_in_partition=(i < len(series) - 1)))
    return placed


def _setup(series, **over):
    month_ends = [day for (day, _, _, me, _) in series if me]
    bot = HmmRegimeStrategy(_params(month_ends, **over))
    ctx = Ctx()
    bot.on_start(ctx)
    return bot, ctx


def test_buy_on_calm_then_sell_on_turbulent(monkeypatch):
    monkeypatch.setattr(rox, "infer_regime", fake_infer)
    up = [(d, 100 + j, 100 + j, False, False) for j, d in enumerate(_month_days("2020-01", 20))]
    up[-1] = (*up[-1][:3], True, False)                               # Jan month-end -> long
    down = [(d, 120 - j, 120 - j, False, False) for j, d in enumerate(_month_days("2020-02", 20))]
    down[-1] = (*down[-1][:3], True, False)                           # Feb month-end -> flat
    mid = [("2020-03-02", 101, 101, False, False)]                   # flat executes here (regime->flat)
    term = [("2020-03-03", 101, 101, False, True)]
    series = up + down + mid + term
    bot, ctx = _setup(series)
    placed = _run(bot, ctx, series)
    sides = [o.side for o in placed]
    assert sides[0] == "buy" and "sell" in sides
    assert any(o.reason == "C-ROX regime->flat" for o in placed)
    assert [d["target_weight"] for d in bot.decisions] == ["0.95", "0"]


def test_terminal_liquidation(monkeypatch):
    monkeypatch.setattr(rox, "infer_regime", fake_infer)
    up = [(d, 100 + j, 100 + j, False, False) for j, d in enumerate(_month_days("2020-01", 20))]
    up[-1] = (*up[-1][:3], True, False)                               # Jan month-end -> long
    entry = [("2020-02-03", 121, 121, False, False)]                 # buy executes here
    term = [("2020-02-04", 121, 121, False, True)]                   # terminal liquidation
    series = up + entry + term
    bot, ctx = _setup(series)
    placed = _run(bot, ctx, series)
    assert [o.side for o in placed] == ["buy", "sell"]
    assert placed[-1].reason == "C-ROX terminal liquidation"
    assert ctx.qty == D(0)


def test_ignores_other_instruments(monkeypatch):
    monkeypatch.setattr(rox, "infer_regime", fake_infer)
    bot, ctx = _setup([("2020-01-02", 100, 100, False, False)])
    ts = datetime.fromisoformat("2020-01-02T16:00:00").replace(tzinfo=NY)
    other = MarketEvent.quote(2, ts, mid=D("50"), meta={"phase": "close"})
    assert bot.on_event(ctx, other) == []
    assert bot._returns == []  # no close recorded for a foreign instrument


def test_month_end_entry_outside_partition_is_skipped(monkeypatch):
    monkeypatch.setattr(rox, "infer_regime", fake_infer)
    series = [(d, 100 + j, 100 + j, False, False) for j, d in enumerate(_month_days("2020-01", 20))]
    series[-1] = (*series[-1][:3], True, False)  # last day is a month-end -> its next open is outside the series
    bot, ctx = _setup(series)
    _run(bot, ctx, series)
    assert bot.decisions == []
    assert any(s["reason"] == "month-end entry open outside partition" for s in bot.skips)
