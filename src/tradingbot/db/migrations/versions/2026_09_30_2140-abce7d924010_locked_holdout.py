"""Persist locked dataset boundaries and one final attempt per strategy version.

Revision ID: abce7d924010
Revises: 98b1835af012
"""
from alembic import op
import sqlalchemy as sa

revision = "abce7d924010"
down_revision = "98b1835af012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("backtest_datasets",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("data_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("holdout_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("data_start < holdout_start AND holdout_start < data_end", name=op.f("ck_backtest_datasets_ordered_split")))
    op.add_column("trials", sa.Column("dataset_key", sa.String(128)))
    op.add_column("trials", sa.Column("holdout_start", sa.DateTime(timezone=True)))
    op.add_column("trials", sa.Column("strategy_version", sa.String(64)))
    op.add_column("trials", sa.Column("final_holdout", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_foreign_key(op.f("fk_trials_dataset_key_backtest_datasets"), "trials", "backtest_datasets", ["dataset_key"], ["key"])
    op.create_index("uq_trials_final_holdout_version", "trials", ["strategy_version"], unique=True,
                    postgresql_where=sa.text("final_holdout"))
    op.create_check_constraint(op.f("ck_trials_holdout_identity"), "trials",
        "NOT final_holdout OR (mode = 'backtest' AND strategy_version IS NOT NULL AND dataset_key IS NOT NULL AND holdout_start IS NOT NULL)")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM trials WHERE final_holdout) THEN
            RAISE EXCEPTION 'Cannot remove consumed holdout records';
        END IF;
    END $$""")
    op.drop_constraint(op.f("ck_trials_holdout_identity"), "trials", type_="check")
    op.drop_index("uq_trials_final_holdout_version", table_name="trials")
    op.drop_constraint(op.f("fk_trials_dataset_key_backtest_datasets"), "trials", type_="foreignkey")
    for name in ("final_holdout", "strategy_version", "holdout_start", "dataset_key"):
        op.drop_column("trials", name)
    op.drop_table("backtest_datasets")
