"""initial meta-template tables

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fallback_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=128), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
        sa.Column("grade_level", sa.Integer(), nullable=False),
        sa.Column("observation_kind", sa.String(length=64), nullable=False),
        sa.Column("expected_result_json", sa.Text(), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.Column("excluded_by", sa.String(length=128), nullable=True),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "observation_kind", name="uq_observation_candidate_kind"),
    )
    op.create_table(
        "fingerprint_tags",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "observation_id",
            sa.String(length=36),
            sa.ForeignKey("fallback_observations.id"),
            nullable=False,
        ),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint_json", sa.Text(), nullable=False),
        sa.Column("fingerprint_key", sa.String(length=256), nullable=False),
        sa.Column("tagger_model_id", sa.String(length=128), nullable=False),
        sa.Column("tagger_prompt_version", sa.String(length=32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("observation_id", "fingerprint_version", name="uq_tag_observation_version"),
    )
    op.create_index("ix_fingerprint_tags_key", "fingerprint_tags", ["fingerprint_key"])
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("fingerprint_key", sa.String(length=256), nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint_json", sa.Text(), nullable=False),
        sa.Column("trigger_observation_ids", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_job_per_fingerprint",
        "generation_jobs",
        ["fingerprint_key"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_job_per_fingerprint", table_name="generation_jobs")
    op.drop_table("generation_jobs")
    op.drop_index("ix_fingerprint_tags_key", table_name="fingerprint_tags")
    op.drop_table("fingerprint_tags")
    op.drop_table("fallback_observations")
