"""MarketDataRecorder synchronous core: fake sink, fake risk, injected clock."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradingbot.db import enums
from tradingbot.recorder.heartbeat import (
    FEED_SILENCE_SECONDS,
    KEEPALIVE_INTERVAL_SECONDS,
)
from tradingbot.recorder.recorder import Backoff, MarketDataRecorder

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, start: datetime = T0):
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


class FakeSink:
    def __init__(self):
        self.quotes = []   # list of observation-batches
        self.trades = []
        self.commits = 0

    def write_quotes(self, observations):
        obs = list(observations)
        self.quotes.append(obs)
        return len(obs)

    def write_trades(self, observations):
        obs = list(observations)
        self.trades.append(obs)
        return len(obs)

    def commit(self):
        self.commits += 1

    # convenience
    @property
    def all_quotes(self):
        return [o for batch in self.quotes for o in batch]

    @property
    def all_trades(self):
        return [o for batch in self.trades for o in batch]


class FakeRisk:
    def __init__(self):
        self.api_errors = 0
        self.incidents = []

    def record_api_error(self, now=None):
        self.api_errors += 1

    def log_incident(self, **kwargs):
        self.incidents.append(kwargs)
        return kwargs


def amount(value: str) -> dict:
    return {"value": value, "currency": "USD"}


def md_message(slug: str, bid: str, ask: str) -> dict:
    return {"marketData": {
        "marketSlug": slug,
        "bids": [{"px": amount(bid), "qty": "10"}],
        "offers": [{"px": amount(ask), "qty": "10"}],
        "state": "MARKET_STATE_OPEN",
    }}


def make(clock=None, risk=None):
    sink = FakeSink()
    rec = MarketDataRecorder(sink=sink, risk=risk, clock=(clock or Clock()))
    return rec, sink


def test_market_data_writes_a_quote_and_updates_book():
    rec, sink = make()
    rec.handle_open()
    rec.handle_market_data(md_message("m", "0.40", "0.44"))
    assert len(sink.all_quotes) == 1
    q = sink.all_quotes[0]
    assert q.market_slug == "m" and q.bid == Decimal("0.40") and q.ask == Decimal("0.44")
    assert rec.health.last_book["m"].bid == Decimal("0.40")
    assert rec.health.last_quote_ts == T0


def test_trade_writes_a_trade_and_stamps_health():
    clock = Clock()
    rec, sink = make(clock)
    rec.handle_open()
    rec.handle_trade({"trade": {
        "marketSlug": "m", "price": amount("0.5"), "quantity": amount("3"),
        "taker": {"side": "SIDE_SELL"},
    }})
    assert len(sink.all_trades) == 1
    assert sink.all_trades[0].aggressor_side == enums.Side.SELL
    assert rec.health.last_trade_ts == T0


def test_empty_slug_and_malformed_trade_are_dropped():
    rec, sink = make()
    rec.handle_open()
    rec.handle_market_data({"marketData": {"marketSlug": "", "bids": [], "offers": []}})
    rec.handle_trade({"trade": {"marketSlug": "m", "price": amount("0.5")}})  # no quantity
    assert sink.all_quotes == [] and sink.all_trades == []


def test_tick_reemits_keepalive_only_after_interval_and_only_while_connected():
    clock = Clock()
    rec, sink = make(clock)
    rec.handle_open()
    rec.handle_market_data(md_message("m", "0.40", "0.44"))
    baseline = len(sink.all_quotes)

    # Before the interval: no keep-alive.
    clock.advance(KEEPALIVE_INTERVAL_SECONDS - 1)
    assert rec.tick()["keepalive"] == 0
    assert len(sink.all_quotes) == baseline

    # After the interval: one keep-alive re-snapshot, flagged as such.
    clock.advance(2)
    result = rec.tick()
    assert result["keepalive"] == 1
    ka = sink.all_quotes[-1]
    assert ka.meta["source"] == "keepalive" and ka.bid == Decimal("0.40")

    # Disconnected: keep-alives stop, so data will age out and the §6 gate fires.
    rec.handle_close()
    clock.advance(KEEPALIVE_INTERVAL_SECONDS + 5)
    assert rec.tick()["keepalive"] == 0


def test_tick_commits_each_call():
    rec, sink = make()
    rec.handle_open()
    rec.tick()
    rec.tick()
    assert sink.commits == 2


def test_silent_feed_logs_one_connectivity_incident():
    clock = Clock()
    risk = FakeRisk()
    rec, _ = make(clock, risk)
    rec.handle_open()
    rec.handle_market_data(md_message("m", "0.40", "0.44"))

    # Go quiet past the silence threshold.
    clock.advance(FEED_SILENCE_SECONDS + 1)
    assert rec.tick()["silent"] is True
    # A second silent tick does not re-log.
    clock.advance(1)
    assert rec.tick()["silent"] is True
    connectivity = [i for i in risk.incidents
                    if i["category"] == enums.IncidentCategory.CONNECTIVITY]
    assert len(connectivity) == 1
    assert connectivity[0]["severity"] == enums.Severity.WARNING
    assert connectivity[0]["mode"] == enums.Mode.LIVE

    # A fresh frame clears the latch; a later silence logs again.
    clock.advance(1)
    rec.handle_market_data(md_message("m", "0.41", "0.45"))
    clock.advance(FEED_SILENCE_SECONDS + 1)
    rec.tick()
    connectivity = [i for i in risk.incidents
                    if i["category"] == enums.IncidentCategory.CONNECTIVITY]
    assert len(connectivity) == 2


def test_ws_error_records_api_error_and_disconnects():
    risk = FakeRisk()
    rec, _ = make(risk=risk)
    rec.handle_open()
    assert rec.health.connected is True
    rec.handle_error(RuntimeError("boom"))
    assert risk.api_errors == 1
    assert rec.health.connected is False
    assert any(i["category"] == enums.IncidentCategory.CONNECTIVITY for i in risk.incidents)


def test_backoff_grows_then_resets():
    b = Backoff(base=1.0, cap=8.0)
    assert [b.next() for _ in range(5)] == [1.0, 2.0, 4.0, 8.0, 8.0]
    b.reset()
    assert b.next() == 1.0


class FakeWS:
    """Minimal stand-in for MarketsWebSocket: same on()/emit contract, emits one
    book and one trade on connect, and stays connected until closed."""

    def __init__(self):
        self._listeners = {}
        self._connected = False
        self.subscribed_md = None
        self.subscribed_trades = None

    def on(self, event, cb):
        self._listeners.setdefault(event, []).append(cb)
        return self

    def _emit(self, event, *args):
        for cb in self._listeners.get(event, []):
            cb(*args)

    async def connect(self):
        self._connected = True
        self._emit("open")
        self._emit("market_data", md_message("m", "0.40", "0.44"))
        self._emit("trade", {"trade": {
            "marketSlug": "m", "price": amount("0.5"), "quantity": amount("1"),
            "taker": {"side": "SIDE_BUY"}}})

    @property
    def is_connected(self):
        return self._connected

    async def subscribe_market_data(self, request_id, slugs):
        self.subscribed_md = slugs

    async def subscribe_market_data_lite(self, request_id, slugs):
        self.subscribed_md = slugs

    async def subscribe_trades(self, request_id, slugs):
        self.subscribed_trades = slugs

    async def close(self):
        self._connected = False


def test_run_smoke_subscribes_ticks_and_stops_cleanly():
    ws = FakeWS()

    async def scenario():
        rec, sink = make()
        stop = asyncio.Event()

        async def stopper():
            await asyncio.sleep(0.05)
            stop.set()

        await asyncio.gather(
            rec.run(ws_factory=lambda: ws, slugs=["m"], tick_seconds=0.005, stop=stop),
            stopper(),
        )
        return rec, sink

    rec, sink = asyncio.run(scenario())
    assert ws.subscribed_md == ["m"] and ws.subscribed_trades == ["m"]
    assert len(sink.all_quotes) >= 1 and len(sink.all_trades) >= 1
    assert sink.commits >= 1
    assert rec.health.connected is False  # closed on stop
