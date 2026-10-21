"""Build a time-ordered :class:`MarketEvent` stream from TimescaleDB.

Reads the ``quotes`` / ``trades`` hypertables for a set of instruments over a time
window and yields events in ``(time, id)`` order, with trades ordered before
quotes at an identical timestamp so a trade fills resting orders before the book
update at the same instant.

Normalization follows ``data/LOADING.md``:

* Live quotes carry real BBO columns. Historical *display / sampled* prices land
  in ``quotes`` with all BBO columns NULL and the value in
  ``metadata.historical.price`` — surfaced here as :attr:`MarketEvent.mid` (a
  mark), never as an executable touch.
* A trade is maker-fill eligible only when the loader flagged it
  (``metadata.historical.maker_fill_eligible``) or it is a live recorder print
  (``metadata.source == "trade"``). Display/sampled observations are quotes and
  are never eligible (PRD §7).
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Iterator
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Quote, Trade
from ..strategy.interface import MarketEvent


def _hist(meta: object) -> dict:
    if isinstance(meta, dict):
        hist = meta.get("historical")
        if isinstance(hist, dict):
            return hist
    return {}


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _truthy(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _quote_event(row: Quote) -> MarketEvent:
    meta = row.metadata_ or {}
    bid, ask, mid, last = row.bid, row.ask, row.mid, row.last
    if bid is None and ask is None and mid is None and last is None:
        # A historical display/sampled observation: value lives in metadata and is
        # a mark, not an executable touch.
        mid = _dec(_hist(meta).get("price"))
    return MarketEvent.quote(
        row.instrument_id, row.time, bid=bid, ask=ask, mid=mid, last=last,
        bid_size=row.bid_size, ask_size=row.ask_size, meta={"quote_id": row.id},
    )


def _trade_event(row: Trade) -> MarketEvent:
    meta = row.metadata_ or {}
    eligible = _truthy(_hist(meta).get("maker_fill_eligible")) or meta.get("source") == "trade"
    return MarketEvent.trade(
        row.instrument_id, row.time, price=row.price, size=row.size,
        aggressor_side=row.aggressor_side, maker_fill_eligible=eligible,
        meta={"trade_id": row.id},
    )


def market_events(
    session: Session,
    instrument_ids: Iterable[int],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Iterator[MarketEvent]:
    """Yield the merged quote+trade stream for ``instrument_ids`` in ``[start, end)``.

    ``start`` is inclusive, ``end`` exclusive. Trades precede quotes at an equal
    timestamp.
    """
    ids = list(instrument_ids)
    if not ids:
        return

    def rows(model, builder):
        stmt = select(model).where(model.instrument_id.in_(ids))
        if start is not None:
            stmt = stmt.where(model.time >= start)
        if end is not None:
            stmt = stmt.where(model.time < end)
        stmt = stmt.order_by(model.time, model.id)
        for row in session.scalars(stmt):
            yield builder(row)

    yield from heapq.merge(
        rows(Trade, _trade_event),   # rank 0 at equal time
        rows(Quote, _quote_event),   # rank 1
        key=lambda e: (e.time, 0 if e.is_trade else 1),
    )
