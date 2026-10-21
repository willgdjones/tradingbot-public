"""Versioned IEX bars, immutable quarter-hour snapshots, recorder health.

Revision ID: iex40data
Revises: jev20cap2026
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "iex40data"
down_revision = "jev20cap2026"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("iex_minute_bars",
        sa.Column("observed_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("symbol", sa.String(8), primary_key=True),
        sa.Column("bar_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.CheckConstraint("observed_at >= bar_start + interval '1 minute'",
                           name=op.f("ck_iex_minute_bars_completed_bar")))
    op.create_index("ix_iex_bars_symbol_start_known", "iex_minute_bars",
                    ["symbol", "bar_start", "observed_at"])
    op.create_table("iex_snapshots",
        sa.Column("boundary", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("symbol", sa.String(8), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.CheckConstraint("observed_at > boundary", name=op.f("ck_iex_snapshots_after_boundary")))
    op.create_index("ix_iex_snapshots_known", "iex_snapshots", ["observed_at"])
    op.execute("SELECT create_hypertable('iex_minute_bars', by_range('observed_at', INTERVAL '7 days'))")
    op.execute("SELECT create_hypertable('iex_snapshots', by_range('boundary', INTERVAL '7 days'))")
    op.create_table("iex_recorder_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", JSONB(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_iex_recorder_health_singleton")))


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM iex_minute_bars) OR EXISTS (SELECT 1 FROM iex_snapshots) THEN
            RAISE EXCEPTION 'Cannot remove captured IEX evidence';
        END IF;
    END $$""")
    op.drop_table("iex_recorder_health")
    op.drop_table("iex_snapshots")
    op.drop_table("iex_minute_bars")
