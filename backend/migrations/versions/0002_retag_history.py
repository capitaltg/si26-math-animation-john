"""allow same-schema retag history

Revision ID: 0002_retag_history
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_retag_history"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 allowed multiple current tags when their fingerprint schema
    # versions differed. Keep the newest current revision deterministically
    # before enforcing the stronger invariant.
    dialect = op.get_context().dialect.name
    # Postgres booleans reject `= 1`; SQLite has no bool type and stores 0/1.
    if dialect == "postgresql":
        true_lit = "TRUE"
        false_lit = "FALSE"
    else:
        true_lit = "1"
        false_lit = "0"
    op.execute(
        sa.text(
            f"""
            UPDATE fingerprint_tags
            SET is_current = {false_lit}
            WHERE is_current = {true_lit}
              AND EXISTS (
                SELECT 1
                FROM fingerprint_tags AS newer
                WHERE newer.observation_id = fingerprint_tags.observation_id
                  AND newer.is_current = {true_lit}
                  AND (
                    newer.created_at > fingerprint_tags.created_at
                    OR (
                      newer.created_at = fingerprint_tags.created_at
                      AND newer.id > fingerprint_tags.id
                    )
                  )
              )
            """
        )
    )
    with op.batch_alter_table("fingerprint_tags") as batch_op:
        batch_op.drop_constraint("uq_tag_observation_version", type_="unique")
    # Partial unique index: needs the dialect-specific predicate kwarg on both
    # backends so retagging can still land the current-per-observation guard.
    op.create_index(
        "uq_current_tag_per_observation",
        "fingerprint_tags",
        ["observation_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current = TRUE"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "0002_retag_history is irreversible: the 0001 schema cannot preserve "
        "append-only retag history within one fingerprint schema version"
    )
