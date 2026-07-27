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
        UniqueConstraint("observation_id", "fingerprint_version", name="uq_tag_observation_version"),
        Index("ix_fingerprint_tags_key", "fingerprint_key"),
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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint_key: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_observation_ids: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
