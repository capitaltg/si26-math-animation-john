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
    op.execute(
        sa.text(
            """
            UPDATE fingerprint_tags
            SET is_current = 0
            WHERE is_current = 1
              AND EXISTS (
                SELECT 1
                FROM fingerprint_tags AS newer
                WHERE newer.observation_id = fingerprint_tags.observation_id
                  AND newer.is_current = 1
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
    op.create_index(
        "uq_current_tag_per_observation",
        "fingerprint_tags",
        ["observation_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "0002_retag_history is irreversible: the 0001 schema cannot preserve "
        "append-only retag history within one fingerprint schema version"
    )
