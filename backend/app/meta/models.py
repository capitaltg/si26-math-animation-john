from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.meta.db import Base

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_NEEDS_MANUAL = "needs_manual_authoring"


def text_status_active():
    return text("status IN ('queued', 'running')")


def text_tag_current():
    return text("is_current = 1")


def text_template_version_enabled():
    return text("status = 'enabled'")


def text_owner_scope():
    """The owner half of an owner-scoped unique index.

    ``coalesce`` rather than the bare column because SQLite treats NULLs as
    distinct inside a UNIQUE index — indexing ``owner_session_id`` directly
    would let two shared (NULL-owner) versions coexist for one fingerprint.
    See migration 0007_template_ownership.
    """
    return text("coalesce(owner_session_id, '')")


class FallbackObservation(Base):
    __tablename__ = "fallback_observations"
    __table_args__ = (
        UniqueConstraint("candidate_id", "observation_kind", name="uq_observation_candidate_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    grade_level: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FingerprintTag(Base):
    __tablename__ = "fingerprint_tags"
    __table_args__ = (
        Index("ix_fingerprint_tags_key", "fingerprint_key"),
        Index(
            "uq_current_tag_per_observation",
            "observation_id",
            unique=True,
            sqlite_where=text_tag_current(),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(36), ForeignKey("fallback_observations.id"), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint_key: Mapped[str] = mapped_column(String(256), nullable=False)
    tagger_model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tagger_prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index(
            "uq_active_job_per_fingerprint",
            "fingerprint_key",
            unique=True,
            sqlite_where=text_status_active(),
        ),
        Index("ix_generation_jobs_owner_session_id", "owner_session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint_key: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_observation_ids: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    #: NULL means threshold-triggered and ownerless — an admin reviews it. Set
    #: means one session asked for this build and owns the resulting drafts.
    owner_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


DRAFT_GENERATED = "generated"
DRAFT_VALIDATING = "validating"
DRAFT_PENDING_REVIEW = "pending_review"
DRAFT_FAILED_VALIDATION = "failed_validation"
DRAFT_REJECTED = "rejected"
DRAFT_SUPERSEDED = "superseded"
DRAFT_APPROVED = "approved"


class TemplateDraft(Base):
    __tablename__ = "template_drafts"
    __table_args__ = (
        Index("ix_template_drafts_job", "job_id"),
        Index("ix_template_drafts_fingerprint_key", "fingerprint_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("generation_jobs.id"), nullable=False)
    fingerprint_key: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_draft_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("template_drafts.id"), nullable=True
    )
    params_document_json: Mapped[str] = mapped_column(Text, nullable=False)
    guard_document_json: Mapped[str] = mapped_column(Text, nullable=False)
    answer_expression_json: Mapped[str] = mapped_column(Text, nullable=False)
    teaching_plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    scene_program_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    classifier_bullet: Mapped[str] = mapped_column(Text, nullable=False)
    dsl_schema_versions_json: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_artifact_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewer_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TemplateDraftFixture(Base):
    __tablename__ = "template_draft_fixtures"
    __table_args__ = (Index("ix_template_draft_fixtures_draft", "draft_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_drafts.id"), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("fallback_observations.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    generation_method: Mapped[str] = mapped_column(String(16), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    structural_check_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    structural_check_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TemplateReview(Base):
    __tablename__ = "template_reviews"
    __table_args__ = (Index("ix_template_reviews_draft", "draft_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_drafts.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_label: Mapped[str] = mapped_column(String(128), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    math_semantics_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


TEMPLATE_VERSION_ENABLED = "enabled"
TEMPLATE_VERSION_DISABLED = "disabled"
TEMPLATE_VERSION_REVOKED = "revoked"


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (
        Index("ix_template_versions_fingerprint_key", "fingerprint_key"),
        Index("ix_template_versions_status", "status"),
        Index(
            "uq_enabled_version_per_fingerprint",
            "fingerprint_key",
            text_owner_scope(),
            unique=True,
            sqlite_where=text_template_version_enabled(),
        ),
        Index(
            "uq_enabled_version_per_template_name",
            "template_name",
            text_owner_scope(),
            unique=True,
            sqlite_where=text_template_version_enabled(),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint_key: Mapped[str] = mapped_column(String(256), nullable=False)
    template_name: Mapped[str] = mapped_column(String(128), nullable=False)
    draft_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("template_drafts.id"), nullable=True
    )
    artifact_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    #: NULL means shared with every session. Set means enabled only for the
    #: session that approved it.
    owner_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
