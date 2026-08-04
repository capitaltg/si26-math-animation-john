"""scope enabled template versions to an owning session

Revision ID: 0007_template_ownership
Revises: 0006_meta_template_v3

A teacher can approve a generated template for their own session; an admin
promotes one to everyone by clearing its owner. That makes "one enabled version
per fingerprint" a per-owner invariant rather than a global one, so 0005's two
single-column partial indexes are replaced.

Both replacements index ``coalesce(owner_session_id, '')`` rather than the
column itself. SQLite treats NULLs as distinct inside a UNIQUE index, so
indexing the raw column would let two *shared* (NULL-owner) versions coexist
for one fingerprint and silently drop the invariant 0005 established.
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_template_ownership"
down_revision = "0006_meta_template_v3"
branch_labels = None
depends_on = None

_ENABLED = "status = 'enabled'"


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column("owner_session_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "template_versions",
        sa.Column("owner_session_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_generation_jobs_owner_session_id", "generation_jobs", ["owner_session_id"]
    )

    op.drop_index("uq_enabled_version_per_template_name", table_name="template_versions")
    op.drop_index("uq_enabled_version_per_fingerprint", table_name="template_versions")
    op.execute(
        "CREATE UNIQUE INDEX uq_enabled_version_per_fingerprint "
        "ON template_versions (fingerprint_key, coalesce(owner_session_id, '')) "
        f"WHERE {_ENABLED}"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_enabled_version_per_template_name "
        "ON template_versions (template_name, coalesce(owner_session_id, '')) "
        f"WHERE {_ENABLED}"
    )


def downgrade() -> None:
    raise RuntimeError("0007_template_ownership is intentionally irreversible")
