"""Lossless public tape numerics and historical-data compression policies.

Revision ID: 98b1835af012
Revises: 603bae9dd448
"""

from alembic import op
import sqlalchemy as sa

revision = "98b1835af012"
down_revision = "603bae9dd448"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.alter_column("trades", "price", type_=sa.Numeric(), existing_type=sa.Numeric(18, 8))
    op.alter_column("trades", "size", type_=sa.Numeric(), existing_type=sa.Numeric(28, 10))
    for table in ("quotes", "trades"):
        op.execute(f"ALTER TABLE {table} SET (timescaledb.compress, "
                   "timescaledb.compress_segmentby = 'instrument_id', "
                   "timescaledb.compress_orderby = 'time DESC, id DESC')")
        # Leave the initial bulk import time to finish. The capture workflow also
        # compresses completed old chunks explicitly, with its disk gate.
        op.execute(f"SELECT add_compression_policy('{table}', compress_after => INTERVAL '7 days', "
                   "schedule_interval => INTERVAL '1 day', initial_start => now() + INTERVAL '1 day', "
                   "if_not_exists => true)")


def downgrade():
    # Refuse a lossy downgrade. No rounding/deletion of historical evidence.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM trades WHERE price <> round(price, 8)
                   OR abs(price) >= 10000000000 OR size <> round(size, 10)
                   OR abs(size) >= 1000000000000000000) THEN
            RAISE EXCEPTION 'Cannot narrow public tape NUMERIC without losing source precision';
        END IF;
    END $$""")
    for table in ("quotes", "trades"):
        op.execute(f"SELECT remove_compression_policy('{table}', if_exists => true)")
        op.execute(f"SELECT decompress_chunk(c, if_compressed => true) FROM show_chunks('{table}') c")
        op.execute(f"ALTER TABLE {table} SET (timescaledb.compress = false)")
    op.alter_column("trades", "price", type_=sa.Numeric(18, 8), existing_type=sa.Numeric())
    op.alter_column("trades", "size", type_=sa.Numeric(28, 10), existing_type=sa.Numeric())
