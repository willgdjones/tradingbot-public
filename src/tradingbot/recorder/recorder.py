"""The live market-data recorder driver.

Splits cleanly into a **synchronous core** (message handlers + :meth:`tick`) that
holds all the logic and is unit-tested with a fake sink and an injected clock,
and a **thin async runloop** (:meth:`run`) that owns the websocket lifecycle,
subscriptions and reconnection backoff. The Polymarket US market websocket
(:class:`polymarket_us.websocket.markets.MarketsWebSocket`) is an event emitter
whose callbacks fire synchronously on the asyncio loop, so the handlers mutate
in-process state and write to the sink without any locking.

What "staleness heartbeat for the risk engine" means here (PRD §6):

* every book update and trade is written straight through to the hypertables the
  risk engine reads;
* :meth:`tick` re-snapshots each subscribed market's top-of-book on a cadence
  under 30 s so a connected-but-quiet market never looks stale;
* when the feed falls silent past :data:`~tradingbot.recorder.heartbeat.FEED_SILENCE_SECONDS`,
  a connectivity incident is logged once — and, because the re-snapshots stop,
  the data legitimately ages out and the §6 gate halts trading on its own.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol

from ..db import enums
from .decode import (
    QuoteObs,
    TradeObs,
    decode_market_data,
    decode_market_data_lite,
    decode_trade,
)
from .heartbeat import (
    FEED_SILENCE_SECONDS,
    KEEPALIVE_INTERVAL_SECONDS,
    FeedHealth,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Sink(Protocol):
    """What the driver needs from a persistence layer (see :class:`store.DbSink`)."""

    def write_quotes(self, observations: Sequence[QuoteObs]) -> int: ...
    def write_trades(self, observations: Sequence[TradeObs]) -> int: ...
    def commit(self) -> None: ...


class RiskHook(Protocol):
    """The slice of the risk engine the recorder feeds: the API-error counter and
    the incident log (see :class:`tradingbot.risk.engine.RiskEngine`)."""

    def record_api_error(self, now: datetime | None = ...) -> None: ...
    def log_incident(self, **kwargs: object) -> object: ...


class Backoff:
    """Exponential reconnect backoff with a cap, reset on a clean connect."""

    def __init__(self, base: float = 1.0, cap: float = 30.0) -> None:
        self.base, self.cap, self._n = base, cap, 0

    def reset(self) -> None:
        self._n = 0

    def next(self) -> float:
        delay = min(self.cap, self.base * (2 ** self._n))
        self._n += 1
        return delay


class MarketDataRecorder:
    def __init__(
        self,
        *,
        sink: Sink,
        health: FeedHealth | None = None,
        risk: RiskHook | None = None,
        clock=_utcnow,
        keepalive_interval: float = KEEPALIVE_INTERVAL_SECONDS,
        silence_threshold: float = FEED_SILENCE_SECONDS,
        mode: str = enums.Mode.LIVE,
    ) -> None:
        self.sink = sink
        self.health = health or FeedHealth()
        self.risk = risk
        self.clock = clock
        self.keepalive_interval = keepalive_interval
        self.silence_threshold = silence_threshold
        self.mode = mode
        self._silence_logged = False

    # -- synchronous message handlers (called from the ws event loop) -------
    def handle_market_data(self, message: dict) -> None:
        self._ingest_quote(decode_market_data(message.get("marketData") or {}, recv_ts=self.clock()))

    def handle_market_data_lite(self, message: dict) -> None:
        self._ingest_quote(
            decode_market_data_lite(message.get("marketDataLite") or {}, recv_ts=self.clock())
        )

    def _ingest_quote(self, obs: QuoteObs) -> None:
        if not obs.market_slug:
            return
        now = obs.recv_ts
        self.health.record_quote(obs, now)
        self.sink.write_quotes([obs])
        self._silence_logged = False

    def handle_trade(self, message: dict) -> None:
        now = self.clock()
        try:
            obs = decode_trade(message.get("trade") or {}, recv_ts=now)
        except ValueError:
            return  # a malformed print is dropped, not fatal
        if not obs.market_slug:
            return
        self.health.record_trade(now)
        self.sink.write_trades([obs])
        self._silence_logged = False

    def handle_ws_heartbeat(self, *args: object) -> None:
        self.health.record_message(self.clock())

    def handle_open(self, *args: object) -> None:
        self.health.mark_connected(self.clock())
        self._silence_logged = False

    def handle_close(self, *args: object) -> None:
        self.health.mark_disconnected()

    def handle_error(self, error: object = None, *args: object) -> None:
        """A websocket error counts toward the §6 5-errors/minute API halt."""
        if self.risk is not None:
            self.risk.record_api_error(self.clock())
            self.risk.log_incident(
                severity=enums.Severity.WARNING,
                category=enums.IncidentCategory.CONNECTIVITY,
                mode=self.mode,
                message=f"market-data websocket error: {error}",
            )
        self.health.mark_disconnected()

    # -- periodic tick: keep-alive re-snapshot + silence detection ----------
    def tick(self, now: datetime | None = None) -> dict:
        """Re-snapshot quiet books and detect a silent feed. Called on the driver
        cadence (and directly in tests). Commits whatever has accumulated."""
        now = now or self.clock()
        keepalive = 0
        if self.health.due_for_keepalive(now, self.keepalive_interval):
            observations = self.health.keepalive_quotes(now)
            if observations:
                keepalive = self.sink.write_quotes(observations)
                self.health.last_keepalive_ts = now

        silent = self.health.is_silent(now, self.silence_threshold)
        if silent and not self._silence_logged:
            self._log_silence(now)
            self._silence_logged = True
        elif not silent:
            self._silence_logged = False

        self.sink.commit()
        return {"keepalive": keepalive, "silent": silent}

    def _log_silence(self, now: datetime) -> None:
        if self.risk is None:
            return
        since = self.health.seconds_since_message(now)
        self.risk.log_incident(
            severity=enums.Severity.WARNING,
            category=enums.IncidentCategory.CONNECTIVITY,
            mode=self.mode,
            message=(
                "market-data feed silent for "
                f"{since:.0f}s (>= {self.silence_threshold:.0f}s); "
                "data will age out and the §6 staleness gate will halt trading"
            ),
        )

    # -- async runloop (thin: lifecycle, subscribe, backoff) ----------------
    def _wire(self, ws) -> None:
        ws.on("open", self.handle_open)
        ws.on("market_data", self.handle_market_data)
        ws.on("market_data_lite", self.handle_market_data_lite)
        ws.on("trade", self.handle_trade)
        ws.on("heartbeat", self.handle_ws_heartbeat)
        ws.on("error", self.handle_error)
        ws.on("close", self.handle_close)

    async def _subscribe(self, ws, slugs: list[str], want_lite: bool) -> None:
        if want_lite:
            await ws.subscribe_market_data_lite("md-lite", slugs)
        else:
            await ws.subscribe_market_data("md", slugs)
        await ws.subscribe_trades("tr", slugs)

    async def run(
        self,
        *,
        ws_factory,
        slugs: list[str],
        want_lite: bool = False,
        tick_seconds: float = 1.0,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Connect, subscribe, and tick until ``stop`` is set, reconnecting with
        exponential backoff. ``ws_factory`` returns a fresh
        :class:`MarketsWebSocket` each attempt so a dropped socket is replaced."""
        backoff = Backoff()
        while stop is None or not stop.is_set():
            ws = ws_factory()
            self._wire(ws)
            try:
                await ws.connect()
                await self._subscribe(ws, slugs, want_lite)
                backoff.reset()
                while ws.is_connected and (stop is None or not stop.is_set()):
                    self.tick()
                    await asyncio.sleep(tick_seconds)
            except Exception as error:  # noqa: BLE001 - reconnect on any failure
                self.handle_error(error)
            finally:
                with contextlib.suppress(Exception):
                    await ws.close()
                self.handle_close()
            if stop is not None and stop.is_set():
                break
            await asyncio.sleep(backoff.next())
