"""persist meta-template DSL v3 documents

Revision ID: 0006_meta_template_v3
Revises: 0005_approval_gate
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_meta_template_v3"
down_revision = "0005_approval_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("template_drafts") as batch:
        batch.add_column(sa.Column("teaching_plan_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("scene_program_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("quality_report_json", sa.Text(), nullable=True))
        batch.drop_column("animation_document_json")


def downgrade() -> None:
    raise RuntimeError("0006_meta_template_v3 is intentionally irreversible")
