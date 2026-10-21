"""Immutable receipt-time event feed snapshots.

Revision ID: eventfeed01
Revises: iex40data
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "eventfeed01"
down_revision = "iex40data"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("event_feed_snapshots",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("scope", sa.String(16), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'unavailable')", name=op.f("ck_event_feed_snapshots_status_valid")))
    op.create_index("ix_event_feed_known", "event_feed_snapshots", ["observed_at"])
    op.execute("""CREATE FUNCTION protect_event_feed_evidence() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Event feed evidence is immutable'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER event_feed_immutable BEFORE UPDATE OR DELETE ON event_feed_snapshots
        FOR EACH ROW EXECUTE FUNCTION protect_event_feed_evidence();
    """)


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM event_feed_snapshots) THEN
            RAISE EXCEPTION 'Cannot remove captured event evidence';
        END IF;
    END $$""")
    op.drop_table("event_feed_snapshots")
    op.execute("DROP FUNCTION protect_event_feed_evidence()")
