"""add approval gate persistence

Revision ID: 0005_approval_gate
Revises: 0004_template_versions
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_approval_gate"
down_revision = "0004_template_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "template_reviews",
        sa.Column("math_semantics_confirmed", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "uq_enabled_version_per_fingerprint",
        "template_versions",
        ["fingerprint_key"],
        unique=True,
        sqlite_where=sa.text("status = 'enabled'"),
    )
    op.create_index(
        "uq_enabled_version_per_template_name",
        "template_versions",
        ["template_name"],
        unique=True,
        sqlite_where=sa.text("status = 'enabled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_enabled_version_per_template_name", table_name="template_versions")
    op.drop_index("uq_enabled_version_per_fingerprint", table_name="template_versions")
    with op.batch_alter_table("template_reviews") as batch_op:
        batch_op.drop_column("math_semantics_confirmed")
