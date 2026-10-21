"""Persist strategy-family exposure across versions and renamed datasets.

Revision ID: bcf10a202601
Revises: abce7d924010
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "bcf10a202601"
down_revision = "abce7d924010"
branch_labels = None
depends_on = None


def legacy_family(config, params):
    """Frozen migration mapping: do not import mutable runtime code."""
    identity = (params.get("_holdout") or {}).get("identity") or params.get("_frozen") or {}
    reactor = identity.get("key")
    families = set()
    for value in (config.get("candidate"), reactor, config.get("research_family")):
        if not isinstance(value, str):
            continue
        match = re.match(r"^(?:sweep_)?(c[0-9]{2})(?:$|[-_])", value.lower())
        family = match[1] if match else {
            "turn_of_month": "turn_of_month", "tom_random_window_control": "turn_of_month",
            "longshot": "longshot", "letf_eod": "letf_eod", "rewards": "rewards"}.get(value)
        if family:
            families.add(family)
    if config.get("research_family"):
        explicit = config["research_family"].lower()
        if not re.match(r"^(?:sweep_)?c[0-9]{2}(?:$|[-_])", explicit):
            families.add(explicit)
    if len(families) != 1:
        raise RuntimeError("Unmapped/conflicting legacy final family; review before migration")
    return families.pop(), reactor


def backfill_receipts(connection):
    # Read declared SOURCE bounds, never the first/last actual trade of a run.
    rows = connection.execute(sa.text("""
        SELECT t.id, t.strategy_id, t.dataset_key, t.params, s.config,
               d.data_start, d.holdout_start, d.data_end
        FROM trials t JOIN strategies s ON s.id = t.strategy_id
        JOIN backtest_datasets d ON d.key = t.dataset_key
        WHERE t.final_holdout AND NOT EXISTS (
            SELECT 1 FROM family_holdout_spends h WHERE h.trial_id = t.id)
        ORDER BY t.id
    """)).mappings().all()
    for row in rows:
        family, reactor = legacy_family(row["config"] or {}, row["params"] or {})
        aliases = [f"strategy:{row['strategy_id']}"] + (["reactor:" + reactor] if reactor else [])
        for alias in aliases:
            connection.execute(sa.text("""
                INSERT INTO holdout_family_aliases(alias, family_key) VALUES (:alias, :family)
                ON CONFLICT (alias) DO NOTHING
            """), {"alias": alias, "family": family})
            actual = connection.scalar(sa.text("SELECT family_key FROM holdout_family_aliases WHERE alias=:alias"), {"alias": alias})
            if actual != family:
                raise RuntimeError("Conflicting legacy family alias; review before migration")
        connection.execute(sa.text("""
            INSERT INTO family_holdout_spends
                (trial_id, family_key, dataset_key, data_start, holdout_start, data_end)
            VALUES (:id, :family, :dataset_key, :data_start, :holdout_start, :data_end)
        """), {**row, "family": family})


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Block admissions by older processes until the historical backfill commits.
    op.execute("LOCK TABLE trials IN SHARE ROW EXCLUSIVE MODE")
    op.create_table("holdout_family_aliases",
        sa.Column("alias", sa.String(256), primary_key=True),
        sa.Column("family_key", sa.String(128), nullable=False))
    op.create_index("ix_holdout_family_aliases_family_key", "holdout_family_aliases", ["family_key"])
    op.create_table("family_holdout_spends",
        sa.Column("trial_id", sa.BigInteger(), sa.ForeignKey("trials.id"), primary_key=True),
        sa.Column("family_key", sa.String(128), nullable=False),
        sa.Column("dataset_key", sa.String(128), sa.ForeignKey("backtest_datasets.key"), nullable=False),
        sa.Column("data_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("holdout_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_end", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("data_start < holdout_start AND holdout_start < data_end", name=op.f("ck_family_holdout_spends_ordered_split")))
    op.create_index("ix_family_holdout_spends_family_key", "family_holdout_spends", ["family_key"])
    backfill_receipts(op.get_bind())
    # Historical trial rows and hashes are deliberately never updated.
    op.execute("""CREATE FUNCTION refuse_holdout_audit_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'Holdout family bindings and exposure receipts are immutable';
        END $$""")
    for table in ("holdout_family_aliases", "family_holdout_spends"):
        op.execute(f"CREATE TRIGGER immutable_holdout_audit BEFORE UPDATE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION refuse_holdout_audit_update()")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM family_holdout_spends) THEN
            RAISE EXCEPTION 'Cannot remove consumed family holdout records';
        END IF;
    END $$""")
    op.drop_table("family_holdout_spends")
    op.drop_table("holdout_family_aliases")
    op.execute("DROP FUNCTION refuse_holdout_audit_update()")
