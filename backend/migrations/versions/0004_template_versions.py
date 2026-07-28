"""add template_versions

Revision ID: 0004_template_versions
Revises: 0003_template_drafts
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_template_versions"
down_revision = "0003_template_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("fingerprint_key", sa.String(length=256), nullable=False),
        sa.Column("template_name", sa.String(length=128), nullable=False),
        sa.Column(
            "draft_id", sa.String(length=36), sa.ForeignKey("template_drafts.id"), nullable=True
        ),
        sa.Column("artifact_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_template_versions_fingerprint_key", "template_versions", ["fingerprint_key"])
    op.create_index("ix_template_versions_status", "template_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_template_versions_status", table_name="template_versions")
    op.drop_index("ix_template_versions_fingerprint_key", table_name="template_versions")
    op.drop_table("template_versions")
