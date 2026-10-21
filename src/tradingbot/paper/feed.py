"""Incremental forward-only adapter for committed live-recorder rows.

Keep received time for freshness and the original trade_time for causality.
Historical display/sampled observations are excluded, even when their IDs are new.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, literal, select, union_all
from sqlalchemy.orm import Session

from tradingbot.db.models import Quote, Trade
from tradingbot.fees.core import aware
from tradingbot.strategy import MarketEvent

QUOTE_SOURCES = ("market_data", "market_data_lite", "keepalive")


@dataclass(frozen=True)
class FeedCursor:
    quote_id: int = 0
    trade_id: int = 0


def quote_event(row: Quote) -> MarketEvent:
    return MarketEvent.quote(row.instrument_id, row.time, bid=row.bid, ask=row.ask,
                             mid=row.mid, last=row.last, bid_size=row.bid_size, ask_size=row.ask_size,
                             meta={**(row.metadata_ or {}), "row_id": row.id})


def trade_event(row: Trade) -> MarketEvent:
    meta = {**(row.metadata_ or {}), "row_id": row.id, "external_trade_id": row.external_trade_id}
    return MarketEvent.trade(row.instrument_id, row.time, price=row.price, size=row.size,
                             aggressor_side=row.aggressor_side,
                             maker_fill_eligible=meta.get("source") == "trade" and bool(meta.get("trade_time")),
                             meta=meta)


def live_events(session: Session, instrument_ids: list[int], *, since: datetime,
                through: datetime, cursor: FeedCursor, batch_size: int = 500) -> list[MarketEvent]:
    """Read the earliest bounded prefix of the merged recorder channels.

    Cursors advance only when the engine commits the corresponding event. This
    expects received times to follow IDs within each live-recorder channel; a
    late commit behind a consumed ID is conservatively skipped, never replayed
    as new executable volume. Both channel heads and their payloads are read in
    one database statement/snapshot, so a commit between separate channel reads
    cannot expose a later trade while hiding an already earlier quote.
    """
    aware(since)
    aware(through)
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    heads = []
    for model, priority, after, sources in (
        (Quote, 1, cursor.quote_id, QUOTE_SOURCES),
        (Trade, 0, cursor.trade_id, ("trade",)),
    ):
        head = select(model.id.label("id"), model.time.label("time"),
                      literal(priority).label("priority")).where(
            model.instrument_id.in_(instrument_ids), model.id > after,
            model.time >= since, model.time <= through,
            model.metadata_["source"].as_string().in_(sources),
        ).order_by(model.id).limit(batch_size).subquery()
        heads.append(select(head))
    merged = union_all(*heads).subquery()
    # Taking N from each ordered channel is sufficient to find the first N
    # overall, but returning all 2N would let one channel overtake omitted rows
    # in the other. Preserve the existing trade-before-quote tie convention.
    batch = select(merged).order_by(merged.c.time, merged.c.priority,
                                    merged.c.id).limit(batch_size).subquery()
    rows = session.execute(select(Quote, Trade).select_from(batch).outerjoin(
        Quote, and_(batch.c.priority == 1, Quote.id == batch.c.id, Quote.time == batch.c.time),
    ).outerjoin(
        Trade, and_(batch.c.priority == 0, Trade.id == batch.c.id, Trade.time == batch.c.time),
    ).order_by(batch.c.time, batch.c.priority, batch.c.id))
    return [trade_event(trade) if trade is not None else quote_event(quote)
            for quote, trade in rows]
