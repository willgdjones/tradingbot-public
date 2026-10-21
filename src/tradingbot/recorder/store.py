"""Persistence for the recorder: resolve subscriptions and write observations.

The recorder speaks in venue *market slugs*; the ledger and risk engine speak in
``instrument_id``. :func:`resolve_subscriptions` bridges the two once at startup,
and :class:`DbSink` turns decoded observations into ``quotes`` / ``trades`` rows
(the TimescaleDB hypertables the risk engine reads for its §6 staleness gate).

The sink *flushes* on every write so rows are visible within the session, but it
does not *commit* — the driver commits on its own cadence
(:meth:`DbSink.commit`), which is what makes rows visible to the separate
risk-engine / dashboard sessions. Tests run inside a rolled-back transaction and
assert on flushed rows without ever committing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import enums
from ..db.models import Instrument, Market, Quote, Trade, Venue
from .decode import QuoteObs, TradeObs

PM_US = "polymarket_us"


class SubscriptionError(LookupError):
    """A requested slug has no resolvable Polymarket US instrument."""


def _resolve_one(session: Session, venue_id: int, slug: str) -> int | None:
    """Resolve one slug to an ``instrument_id`` on Polymarket US.

    Canonical first: the loader (tradingbot-pu9) keys a market by
    ``markets.external_id = slug`` and stores the Yes (long) / No legs as
    ``instruments.external_id = "<slug>:yes" / "<slug>:no"``; a PM US market's
    book is quoted on the Yes side, so that is the line we record. Falls back to
    an instrument whose ``symbol`` equals the slug for hand-seeded data.
    """
    market_id = session.scalar(
        select(Market.id).where(Market.venue_id == venue_id, Market.external_id == slug)
    )
    if market_id is not None:
        yes_id = session.scalar(
            select(Instrument.id).where(
                Instrument.market_id == market_id,
                Instrument.instrument_type == enums.InstrumentType.BINARY_YES,
            )
        )
        if yes_id is not None:
            return yes_id
        inst_ids = session.scalars(
            select(Instrument.id).where(Instrument.market_id == market_id)
        ).all()
        if len(inst_ids) == 1:
            return inst_ids[0]
    return session.scalar(
        select(Instrument.id).where(
            Instrument.venue_id == venue_id, Instrument.symbol == slug
        )
    )


def resolve_subscriptions(session: Session, slugs: Iterable[str]) -> dict[str, int]:
    """Map each market slug to the ``instrument_id`` to record it against.

    Raises :class:`SubscriptionError` for any slug that cannot be resolved — the
    recorder fails fast at startup rather than silently dropping a feed. The
    market/instrument rows themselves are created by the loader (tradingbot-pu9)
    or the seed; the recorder only reads them.
    """
    venue_id = session.scalar(select(Venue.id).where(Venue.key == PM_US))
    if venue_id is None:
        raise SubscriptionError(f"venue {PM_US!r} is not seeded")

    mapping: dict[str, int] = {}
    for slug in slugs:
        inst_id = _resolve_one(session, venue_id, slug)
        if inst_id is None:
            raise SubscriptionError(
                f"no Polymarket US instrument for slug {slug!r}; "
                "seed or load the market first"
            )
        mapping[slug] = inst_id
    return mapping


class DbSink:
    """Writes decoded observations to the ``quotes`` / ``trades`` hypertables."""

    def __init__(self, session: Session, subscriptions: dict[str, int]) -> None:
        self.session = session
        self.subscriptions = subscriptions

    def _instrument_id(self, slug: str) -> int | None:
        return self.subscriptions.get(slug)

    def write_quotes(self, observations: Sequence[QuoteObs]) -> int:
        """Insert one ``quotes`` row per observation for a subscribed slug.
        Observations for unknown slugs are skipped. Returns rows written."""
        rows = [
            Quote(
                time=obs.recv_ts,
                instrument_id=iid,
                bid=obs.bid,
                ask=obs.ask,
                bid_size=obs.bid_size,
                ask_size=obs.ask_size,
                mid=obs.mid,
                last=obs.last,
                metadata_=obs.meta or None,
            )
            for obs in observations
            if (iid := self._instrument_id(obs.market_slug)) is not None
        ]
        if rows:
            self.session.add_all(rows)
            self.session.flush()
        return len(rows)

    def write_trades(self, observations: Sequence[TradeObs]) -> int:
        """Insert one ``trades`` row per observation for a subscribed slug."""
        rows = [
            Trade(
                time=obs.recv_ts,
                instrument_id=iid,
                price=obs.price,
                size=obs.size,
                aggressor_side=obs.aggressor_side,
                external_trade_id=obs.external_trade_id,
                metadata_=obs.meta or None,
            )
            for obs in observations
            if (iid := self._instrument_id(obs.market_slug)) is not None
        ]
        if rows:
            self.session.add_all(rows)
            self.session.flush()
        return len(rows)

    def commit(self) -> None:
        """Make flushed rows durable and visible to other sessions."""
        self.session.commit()
