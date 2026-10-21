"""Durable intraday Jev turn claims and observations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "jevturn01"
down_revision = "eventfeed01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("jev_intraday_turns",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("trial_id", sa.BigInteger(), sa.ForeignKey("trials.id"), nullable=False),
        sa.Column("boundary", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("trial_id", "boundary"))


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM jev_intraday_turns) THEN
            RAISE EXCEPTION 'Cannot remove captured Jev turns';
        END IF;
    END $$""")
    op.drop_table("jev_intraday_turns")
