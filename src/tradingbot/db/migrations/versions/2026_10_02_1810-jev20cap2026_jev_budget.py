"""Durable Jev spend reservations and calibration audit.

Revision ID: jev20cap2026
Revises: bcf10a202601
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "jev20cap2026"
down_revision = "bcf10a202601"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("jev_budget_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("halt_reason", sa.String(40)),
        sa.CheckConstraint("id = 1", name=op.f("ck_jev_budget_control_singleton")))
    op.create_table("jev_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_ts", sa.DateTime(timezone=True)),
        sa.Column("billing_month", sa.Date(), nullable=False),
        sa.Column("completed_month", sa.Date()),
        sa.Column("correlation_id", sa.String(256)),
        sa.Column("state_hash", sa.String(64)),
        sa.Column("questions", JSONB(), nullable=False),
        sa.Column("answers", JSONB()),
        sa.Column("requested_model", sa.String(60), nullable=False),
        sa.Column("model_id", sa.String(60)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("latency_ms", sa.BigInteger()),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("input_price_per_million", sa.Numeric(20, 12), nullable=False),
        sa.Column("pricing_version", sa.String(80), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(20, 12), nullable=False),
        sa.Column("actual_usd", sa.Numeric(20, 12)),
        sa.Column("outcomes", JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("reserved_usd >= 0", name=op.f("ck_jev_requests_nonnegative_reserved")),
        sa.CheckConstraint("actual_usd IS NULL OR actual_usd >= 0", name=op.f("ck_jev_requests_nonnegative_actual")),
        sa.CheckConstraint("status IN ('pending', 'ok', 'error', 'uncertain', 'refused')",
                           name=op.f("ck_jev_requests_status_valid")))
    op.create_index("ix_jev_requests_billing_month", "jev_requests", ["billing_month"])
    op.create_index("ix_jev_requests_correlation_id", "jev_requests", ["correlation_id"])


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM jev_requests) THEN
            RAISE EXCEPTION 'Cannot remove Jev spend or calibration records';
        END IF;
    END $$""")
    op.drop_table("jev_requests")
    op.drop_table("jev_budget_control")
