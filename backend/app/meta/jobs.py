import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.meta.models import (
    JOB_QUEUED,
    JOB_RUNNING,
    FallbackObservation,
    FingerprintTag,
    GenerationJob,
)


def count_eligible_observations(session: Session, fingerprint_key: str) -> int:
    stmt = (
        select(func.count())
        .select_from(FallbackObservation)
        .join(FingerprintTag, FingerprintTag.observation_id == FallbackObservation.id)
        .where(
            FingerprintTag.fingerprint_key == fingerprint_key,
            FingerprintTag.is_current.is_(True),
            FallbackObservation.excluded.is_(False),
        )
    )
    return int(session.execute(stmt).scalar_one())


def has_active_job(session: Session, fingerprint_key: str) -> bool:
    stmt = select(func.count()).select_from(GenerationJob).where(
        GenerationJob.fingerprint_key == fingerprint_key,
        GenerationJob.status.in_((JOB_QUEUED, JOB_RUNNING)),
    )
    return int(session.execute(stmt).scalar_one()) > 0


def has_enabled_version(session: Session, fingerprint_key: str) -> bool:
    # Phase 1 seam: no template_versions table exists yet. Phase 4 replaces this
    # with a real lookup against the enabled-version index.
    return False


def evaluate_and_enqueue(
    session: Session,
    *,
    fingerprint_key: str,
    fingerprint_version: int,
    fingerprint_json: str,
    trigger_observation_ids: list[str],
    threshold: int,
    new_id: str,
    now: datetime,
) -> GenerationJob | None:
    if has_enabled_version(session, fingerprint_key):
        return None
    if has_active_job(session, fingerprint_key):
        return None
    if count_eligible_observations(session, fingerprint_key) < threshold:
        return None

    job = GenerationJob(
        id=new_id,
        fingerprint_key=fingerprint_key,
        fingerprint_version=fingerprint_version,
        fingerprint_json=fingerprint_json,
        trigger_observation_ids=json.dumps(trigger_observation_ids),
        status=JOB_QUEUED,
        attempt=0,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        # Another writer inserted the active job first; the partial unique index
        # rejected ours. Roll back to the last savepoint and treat as a no-op.
        session.rollback()
        return None
    return job
