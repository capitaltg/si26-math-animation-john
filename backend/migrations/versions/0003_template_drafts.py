"""add template drafts, fixtures, and reviews

Revision ID: 0003_template_drafts
Revises: 0002_retag_history
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_template_drafts"
down_revision = "0002_retag_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("generation_jobs.id"), nullable=False),
        sa.Column("fingerprint_key", sa.String(length=256), nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_draft_id", sa.String(length=36), sa.ForeignKey("template_drafts.id"), nullable=True
        ),
        sa.Column("params_document_json", sa.Text(), nullable=False),
        sa.Column("guard_document_json", sa.Text(), nullable=False),
        sa.Column("answer_expression_json", sa.Text(), nullable=False),
        sa.Column("animation_document_json", sa.Text(), nullable=False),
        sa.Column("classifier_bullet", sa.Text(), nullable=False),
        sa.Column("dsl_schema_versions_json", sa.Text(), nullable=False),
        sa.Column("artifact_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validation_report_json", sa.Text(), nullable=True),
        sa.Column("preview_artifact_hash", sa.String(length=80), nullable=True),
        sa.Column("reviewer_feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_template_drafts_job", "template_drafts", ["job_id"])
    op.create_index("ix_template_drafts_fingerprint_key", "template_drafts", ["fingerprint_key"])

    op.create_table(
        "template_draft_fixtures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), sa.ForeignKey("template_drafts.id"), nullable=False),
        sa.Column(
            "observation_id",
            sa.String(length=36),
            sa.ForeignKey("fallback_observations.id"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("expected_outcome", sa.String(length=16), nullable=False),
        sa.Column("generation_method", sa.String(length=16), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("expected_result_json", sa.Text(), nullable=True),
        sa.Column("structural_check_passed", sa.Boolean(), nullable=True),
        sa.Column("structural_check_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_template_draft_fixtures_draft", "template_draft_fixtures", ["draft_id"])

    op.create_table(
        "template_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), sa.ForeignKey("template_drafts.id"), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewer_label", sa.String(length=128), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_template_reviews_draft", "template_reviews", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_template_reviews_draft", table_name="template_reviews")
    op.drop_table("template_reviews")
    op.drop_index("ix_template_draft_fixtures_draft", table_name="template_draft_fixtures")
    op.drop_table("template_draft_fixtures")
    op.drop_index("ix_template_drafts_fingerprint_key", table_name="template_drafts")
    op.drop_index("ix_template_drafts_job", table_name="template_drafts")
    op.drop_table("template_drafts")
