"""Feed-health / staleness heartbeat — pure and clock-injected.

The recorder's job is to keep the risk engine's per-instrument staleness gate
honest (PRD §6: halt if the freshest data is more than 30 seconds old). Two
consequences follow, and this module models both without doing any I/O:

* **While connected, re-snapshot each market's top-of-book on a cadence well
  under 30 s.** A quiet-but-connected market sends no book updates, yet it is
  *not* stale — we are still watching it. Re-emitting its last known book with a
  fresh timestamp keeps the gate from firing falsely. The cadence is derived
  from the risk limit itself (:data:`KEEPALIVE_INTERVAL_SECONDS`) so the two can
  never silently drift apart.

* **When the feed goes silent, stop.** On a disconnect or gateway outage the
  re-snapshots cease, so genuinely stale data *does* trip the gate — the safe
  default (PRD §9 accepts there is no dead-man protection beyond this).

We import :data:`STALE_DATA_MAX_SECONDS` read-only to derive our cadence; the
risk limits themselves are never touched here (AGENTS.md, PRD §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from ..risk.limits import STALE_DATA_MAX_SECONDS
from .decode import QuoteObs

# Re-snapshot top-of-book this often while connected — a fraction of the 30 s
# risk gate, so a connected-but-quiet market stays comfortably fresh.
KEEPALIVE_INTERVAL_SECONDS: float = STALE_DATA_MAX_SECONDS / 6  # 5 s

# Treat the feed as silent (worth a connectivity incident) after this long with
# no frame of any kind — including the venue's own websocket heartbeat.
FEED_SILENCE_SECONDS: float = STALE_DATA_MAX_SECONDS / 2  # 15 s


@dataclass
class FeedHealth:
    """Mutable liveness state for one recorder connection. All decisions take an
    explicit ``now`` so callers control the clock (and tests are deterministic)."""

    connected: bool = False
    last_message_ts: datetime | None = None  # any frame, incl. ws heartbeat
    last_quote_ts: datetime | None = None    # a change-driven book update
    last_trade_ts: datetime | None = None
    last_keepalive_ts: datetime | None = None
    # Latest top-of-book per slug, re-emitted as keep-alives while connected.
    last_book: dict[str, QuoteObs] = field(default_factory=dict)

    def mark_connected(self, now: datetime) -> None:
        self.connected = True
        self.last_message_ts = now

    def mark_disconnected(self) -> None:
        self.connected = False

    def record_message(self, now: datetime) -> None:
        self.last_message_ts = now

    def record_quote(self, obs: QuoteObs, now: datetime) -> None:
        self.last_book[obs.market_slug] = obs
        self.last_quote_ts = now
        self.last_message_ts = now

    def record_trade(self, now: datetime) -> None:
        self.last_trade_ts = now
        self.last_message_ts = now

    # -- queries -----------------------------------------------------------
    def seconds_since_message(self, now: datetime) -> float | None:
        if self.last_message_ts is None:
            return None
        return (now - self.last_message_ts).total_seconds()

    def _seconds_since_fresh_write(self, now: datetime) -> float | None:
        """Seconds since we last *wrote* a book row (a real update or a
        keep-alive) — the quantity that governs when the next keep-alive is due."""
        stamps = [t for t in (self.last_quote_ts, self.last_keepalive_ts) if t is not None]
        if not stamps:
            return None
        return (now - max(stamps)).total_seconds()

    def due_for_keepalive(
        self, now: datetime, interval: float = KEEPALIVE_INTERVAL_SECONDS
    ) -> bool:
        """True when connected, holding at least one book, and the freshest book
        write is older than ``interval``."""
        if not self.connected or not self.last_book:
            return False
        since = self._seconds_since_fresh_write(now)
        return since is None or since >= interval

    def is_silent(
        self, now: datetime, threshold: float = FEED_SILENCE_SECONDS
    ) -> bool:
        """True when no frame has arrived for ``threshold`` seconds. A feed that
        never connected (no message yet) is not reported silent — that is the
        driver's connect/backoff concern, not a data-staleness signal."""
        since = self.seconds_since_message(now)
        return since is not None and since >= threshold

    def keepalive_quotes(self, now: datetime) -> list[QuoteObs]:
        """Copies of every held top-of-book stamped at ``now`` and flagged as a
        keep-alive re-snapshot (``meta.source = "keepalive"``), so downstream can
        tell a heartbeat re-write from a change-driven update."""
        out: list[QuoteObs] = []
        for obs in self.last_book.values():
            meta = {**obs.meta, "source": "keepalive"}
            out.append(replace(obs, recv_ts=now, meta=meta))
        return out


def keepalive_interval() -> timedelta:
    """The keep-alive cadence as a :class:`timedelta` (for the driver's sleep)."""
    return timedelta(seconds=KEEPALIVE_INTERVAL_SECONDS)


__all__ = [
    "FEED_SILENCE_SECONDS",
    "KEEPALIVE_INTERVAL_SECONDS",
    "FeedHealth",
    "keepalive_interval",
]
