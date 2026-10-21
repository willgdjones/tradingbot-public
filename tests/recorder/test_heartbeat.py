"""FeedHealth / staleness-heartbeat logic (pure, clock-injected)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradingbot.recorder.decode import QuoteObs
from tradingbot.recorder.heartbeat import (
    FEED_SILENCE_SECONDS,
    KEEPALIVE_INTERVAL_SECONDS,
    FeedHealth,
)
from tradingbot.risk.limits import STALE_DATA_MAX_SECONDS

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def book(slug: str, bid: str, ask: str, ts: datetime) -> QuoteObs:
    return QuoteObs(slug, ts, Decimal(bid), Decimal(ask), None, None, None, None,
                    {"source": "market_data"})


def test_cadence_is_derived_from_and_safely_under_the_risk_gate():
    # The recorder must keep data fresher than the §6 30 s gate, and warn before
    # the gate would actually fire.
    assert KEEPALIVE_INTERVAL_SECONDS < FEED_SILENCE_SECONDS < STALE_DATA_MAX_SECONDS


def test_no_message_yet_is_neither_silent_nor_measurable():
    health = FeedHealth()
    assert health.seconds_since_message(T0) is None
    assert health.is_silent(T0) is False


def test_record_quote_updates_book_and_stamps():
    health = FeedHealth()
    health.mark_connected(T0)
    obs = book("m", "0.4", "0.5", at(1))
    health.record_quote(obs, at(1))
    assert health.last_book["m"] is obs
    assert health.last_quote_ts == at(1)
    assert health.last_message_ts == at(1)


def test_keepalive_due_only_when_connected_with_a_book_and_interval_elapsed():
    health = FeedHealth()
    # Not connected → never due.
    assert health.due_for_keepalive(at(100)) is False

    health.mark_connected(T0)
    # Connected but no book → nothing to re-snapshot.
    assert health.due_for_keepalive(at(100)) is False

    health.record_quote(book("m", "0.4", "0.5", at(0)), at(0))
    # Just wrote → not yet due.
    assert health.due_for_keepalive(at(KEEPALIVE_INTERVAL_SECONDS - 1)) is False
    # Interval elapsed → due.
    assert health.due_for_keepalive(at(KEEPALIVE_INTERVAL_SECONDS + 1)) is True


def test_keepalive_quotes_are_restamped_copies_flagged_as_heartbeat():
    health = FeedHealth()
    health.mark_connected(T0)
    original = book("m", "0.4", "0.5", at(0))
    health.record_quote(original, at(0))

    keepalives = health.keepalive_quotes(at(5))
    assert len(keepalives) == 1
    ka = keepalives[0]
    assert ka.recv_ts == at(5)
    assert ka.bid == Decimal("0.4") and ka.ask == Decimal("0.5")
    assert ka.meta["source"] == "keepalive"
    # The stored book is untouched (frozen copy).
    assert health.last_book["m"] is original
    assert original.meta["source"] == "market_data"


def test_is_silent_after_threshold_of_no_frames():
    health = FeedHealth()
    health.mark_connected(T0)
    health.record_message(at(1))
    assert health.is_silent(at(1 + FEED_SILENCE_SECONDS - 1)) is False
    assert health.is_silent(at(1 + FEED_SILENCE_SECONDS + 1)) is True
