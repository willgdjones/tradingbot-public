"""Append-only IEX feature evidence; event time never doubles as receipt time."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IexBar(Base):
    __tablename__ = "iex_minute_bars"
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(8), primary_key=True)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        Index("ix_iex_bars_symbol_start_known", "symbol", "bar_start", "observed_at"),
        Index("iex_minute_bars_observed_at_idx", observed_at.desc()),
        CheckConstraint("observed_at >= bar_start + interval '1 minute'", name="completed_bar"),
    )


class IexSnapshot(Base):
    __tablename__ = "iex_snapshots"
    boundary: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(8), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        Index("ix_iex_snapshots_known", "observed_at"),
        Index("iex_snapshots_boundary_idx", boundary.desc()),
        CheckConstraint("observed_at > boundary", name="after_boundary"),
    )


class IexRecorderHealth(Base):
    __tablename__ = "iex_recorder_health"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
