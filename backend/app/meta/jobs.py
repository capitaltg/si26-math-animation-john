import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, event, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.meta.models import (
    JOB_QUEUED,
    JOB_RUNNING,
    TEMPLATE_VERSION_ENABLED,
    FallbackObservation,
    FingerprintTag,
    GenerationJob,
    TemplateVersion,
)
from app.meta.models import JOB_FAILED, JOB_NEEDS_MANUAL, JOB_SUCCEEDED  # noqa: F401

_NAIVE_UTC_COLUMNS = ("lease_expires_at", "cooldown_until")


@event.listens_for(GenerationJob, "load")
def _reattach_utc_on_load(job: GenerationJob, _context) -> None:
    """Normalize naive datetimes read back from SQLite to UTC-aware.

    SQLite has no native timezone storage: SQLAlchemy's sqlite dialect always
    hands back naive datetimes on read, regardless of the timezone=True flag
    on the column. That breaks equality comparisons against tz-aware values
    (jobs.py constructs and compares leases/cooldowns using aware UTC
    datetimes throughout). This ORM-level "load" hook re-attaches UTC tzinfo
    immediately after a row is populated, so every read of GenerationJob is
    aware end to end without needing a custom column type in models.py.
    Uses set_committed_value so this normalization never marks the object
    dirty (it's not a real change relative to what the DB just returned).
    """
    for col in _NAIVE_UTC_COLUMNS:
        value = job.__dict__.get(col)
        if value is not None and value.tzinfo is None:
            set_committed_value(job, col, value.replace(tzinfo=timezone.utc))


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


def has_active_job(
    session: Session, fingerprint_key: str, owner_session_id: str | None = None
) -> bool:
    """Whether this owner already has a build in flight for this shape.

    Scoped to one owner, because ownership is the isolation boundary throughout
    this design: one teacher's private build must not refuse another teacher's
    request for the same problem, and the ownerless threshold queue is its own
    scope rather than something a teacher can block.

    ``IS NULL`` for the ownerless scope, so it is a real scope rather than a
    comparison that matches nothing.
    """
    owner_match = (
        GenerationJob.owner_session_id.is_(None)
        if owner_session_id is None
        else GenerationJob.owner_session_id == owner_session_id
    )
    stmt = select(func.count()).select_from(GenerationJob).where(
        GenerationJob.fingerprint_key == fingerprint_key,
        GenerationJob.status.in_((JOB_QUEUED, JOB_RUNNING)),
        owner_match,
    )
    return int(session.execute(stmt).scalar_one()) > 0


def has_enabled_version(session: Session, fingerprint_key: str) -> bool:
    stmt = select(func.count()).select_from(TemplateVersion).where(
        TemplateVersion.fingerprint_key == fingerprint_key,
        TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
    )
    return int(session.execute(stmt).scalar_one()) > 0


def has_version_available_to(
    session: Session, fingerprint_key: str, owner_session_id: str
) -> bool:
    """Whether this session can already reach an enabled version.

    Deliberately narrower than has_enabled_version: another session's private
    version is invisible to this one, so it must not block this session from
    building its own.
    """
    stmt = select(func.count()).select_from(TemplateVersion).where(
        TemplateVersion.fingerprint_key == fingerprint_key,
        TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
        or_(
            TemplateVersion.owner_session_id.is_(None),
            TemplateVersion.owner_session_id == owner_session_id,
        ),
    )
    return int(session.execute(stmt).scalar_one()) > 0


def latest_job(session: Session, fingerprint_key: str) -> GenerationJob | None:
    return session.execute(
        select(GenerationJob)
        .where(GenerationJob.fingerprint_key == fingerprint_key)
        .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_owned_job(
    session: Session, fingerprint_key: str, owner_session_id: str
) -> GenerationJob | None:
    """The most recent job for this fingerprint that belongs to this owner.

    Ownership is the isolation boundary for the teacher's build surface: a status
    lookup that ignored it would let one session read another session's job id
    and draft id whenever both filed the same problem shape. Strict equality on
    ``owner_session_id`` (never NULL) because a teacher's on-demand build always
    carries their session id; the ownerless threshold queue is its own scope and
    must not be visible here.
    """
    return session.execute(
        select(GenerationJob)
        .where(
            GenerationJob.fingerprint_key == fingerprint_key,
            GenerationJob.owner_session_id == owner_session_id,
        )
        .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
        .limit(1)
    ).scalar_one_or_none()


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
    max_attempts: int = 5,
) -> GenerationJob | None:
    if has_enabled_version(session, fingerprint_key):
        return None
    # The threshold path owns nothing, so it is gated by other ownerless jobs.
    if has_active_job(session, fingerprint_key, None):
        return None
    if count_eligible_observations(session, fingerprint_key) < threshold:
        return None

    prior_job = latest_job(session, fingerprint_key)
    attempt = 0
    if prior_job is not None:
        if prior_job.status in (JOB_SUCCEEDED, JOB_NEEDS_MANUAL):
            return None
        if prior_job.status == JOB_FAILED:
            if prior_job.attempt >= max_attempts:
                return None
            if prior_job.cooldown_until is not None and prior_job.cooldown_until > now:
                return None
            prior_ids = set(json.loads(prior_job.trigger_observation_ids))
            if not set(trigger_observation_ids) - prior_ids:
                return None
            attempt = prior_job.attempt

    job = GenerationJob(
        id=new_id,
        fingerprint_key=fingerprint_key,
        fingerprint_version=fingerprint_version,
        fingerprint_json=fingerprint_json,
        trigger_observation_ids=json.dumps(trigger_observation_ids),
        status=JOB_QUEUED,
        attempt=attempt,
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


def enqueue_on_demand(
    session: Session,
    *,
    fingerprint_key: str,
    fingerprint_version: int,
    fingerprint_json: str,
    trigger_observation_ids: list[str],
    owner_session_id: str,
    new_id: str,
    now: datetime,
) -> GenerationJob | None:
    """Queue a build one session explicitly asked for.

    Unlike ``evaluate_and_enqueue`` this ignores the observation threshold and
    the terminal-status guards: a teacher pressing the button is a fresh intent,
    not the accumulation of evidence, so a fingerprint whose earlier job
    succeeded or needed manual authoring is eligible again and the attempt count
    starts over.

    Returns None when the request is pointless (this session can already reach a
    version) or premature (a build is already in flight); the caller turns that
    into a stated refusal.
    """
    if has_version_available_to(session, fingerprint_key, owner_session_id):
        return None
    if has_active_job(session, fingerprint_key, owner_session_id):
        return None

    job = GenerationJob(
        id=new_id,
        fingerprint_key=fingerprint_key,
        fingerprint_version=fingerprint_version,
        fingerprint_json=fingerprint_json,
        trigger_observation_ids=json.dumps(trigger_observation_ids),
        status=JOB_QUEUED,
        owner_session_id=owner_session_id,
        attempt=0,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        # Lost the race to another writer's active job for this fingerprint,
        # exactly as evaluate_and_enqueue treats it.
        session.rollback()
        return None
    return job


def _claimable(now: datetime):
    return or_(
        and_(
            GenerationJob.status == JOB_QUEUED,
            or_(GenerationJob.cooldown_until.is_(None), GenerationJob.cooldown_until <= now),
        ),
        and_(GenerationJob.status == JOB_RUNNING, GenerationJob.lease_expires_at <= now),
    )


def claim_next_job(
    session: Session, *, owner: str, lease_seconds: int, now: datetime
) -> GenerationJob | None:
    candidate = session.execute(
        select(GenerationJob)
        .where(_claimable(now))
        .order_by(GenerationJob.created_at, GenerationJob.id)
        .limit(1)
    ).scalar_one_or_none()
    if candidate is None:
        return None

    lease_expires = now + timedelta(seconds=lease_seconds)
    result = session.execute(
        update(GenerationJob)
        .where(GenerationJob.id == candidate.id, _claimable(now))
        .values(
            status=JOB_RUNNING,
            lease_owner=owner,
            lease_expires_at=lease_expires,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None  # lost the race; caller may retry
    candidate.status = JOB_RUNNING
    candidate.lease_owner = owner
    candidate.lease_expires_at = lease_expires
    candidate.updated_at = now
    return candidate


def complete_job(session: Session, *, job_id: str, owner: str, now: datetime) -> bool:
    result = session.execute(
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status == JOB_RUNNING,
            GenerationJob.lease_owner == owner,
        )
        .values(status=JOB_SUCCEEDED, lease_owner=None, lease_expires_at=None, updated_at=now)
    )
    return result.rowcount == 1


def fail_job(
    session: Session,
    *,
    job_id: str,
    owner: str,
    error_summary: str,
    backoff_base_seconds: int,
    max_attempts: int,
    now: datetime,
) -> bool:
    job = session.get(GenerationJob, job_id)
    if job is None or job.status != JOB_RUNNING or job.lease_owner != owner:
        return False

    next_attempt = job.attempt + 1
    if next_attempt >= max_attempts:
        new_status = JOB_NEEDS_MANUAL
        cooldown = None
    else:
        new_status = JOB_FAILED
        cooldown = now + timedelta(seconds=backoff_base_seconds * (2 ** (next_attempt - 1)))

    result = session.execute(
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status == JOB_RUNNING,
            GenerationJob.lease_owner == owner,
        )
        .values(
            status=new_status,
            attempt=next_attempt,
            cooldown_until=cooldown,
            error_summary=error_summary,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    return result.rowcount == 1


def mark_needs_manual(session: Session, *, job_id: str, now: datetime) -> bool:
    result = session.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id)
        .values(status=JOB_NEEDS_MANUAL, lease_owner=None, lease_expires_at=None, updated_at=now)
    )
    return result.rowcount == 1
