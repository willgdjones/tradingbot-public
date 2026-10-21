"""Immutable receipt-time news and calendar snapshots."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EventFeedSnapshot(Base):
    __tablename__ = "event_feed_snapshots"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        Index("ix_event_feed_known", "observed_at"),
        CheckConstraint("status IN ('ok', 'unavailable')", name="status_valid"),
    )
