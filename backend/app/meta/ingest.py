import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep
from uuid import uuid4

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.fingerprint import Fingerprint, canonical_fingerprint_key, store_tag, tag_candidate
from app.meta.jobs import enqueue_on_demand, evaluate_and_enqueue, has_version_available_to
from app.meta.models import FallbackObservation, FingerprintTag
from app.meta.observations import (
    OBSERVATION_KIND_UNSUPPORTED,
    TextCardReason,
    classify_text_card_reason,
    record_observation,
)
from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult

logger = logging.getLogger(__name__)


def _tag_with_retry(
    source_excerpt: str,
    grade_level: int,
    *,
    max_attempts: int,
    backoff_seconds: float,
) -> Fingerprint:
    attempts = max(1, max_attempts)
    for attempt in range(attempts):
        try:
            return tag_candidate(source_excerpt, grade_level)
        except Exception:
            if attempt == attempts - 1:
                raise
            sleep(backoff_seconds * (2**attempt))
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class BuildRequestOutcome:
    """What became of one teacher's explicit request to build a template."""

    fingerprint_key: str | None = None
    error: str | None = None
    #: The request was declined because a usable template already exists for this
    #: session. Carried separately from `error` because nothing went wrong, and a
    #: benign outcome must not be presented as a failure.
    already_available: bool = False


# Refusals a teacher reads, not codes. Each says what happened and what to do,
# because this is the only feedback the band has to work with.
_ALREADY_AVAILABLE = (
    "There is already a visual for this kind of problem — ask for visualizations "
    "again to see it."
)
_ALREADY_BUILDING = (
    "A visual for this kind of problem is already being built. Try again in a few "
    "minutes."
)
_TAGGING_FAILED = (
    "We could not work out what kind of problem this is, so there is nothing to "
    "build from yet."
)


def _tag_and_store(observation_id: str, source_excerpt: str, grade_level: int, now):
    """The observation's current fingerprint, tagging it first if it has none."""
    settings = get_settings()
    with meta_session() as session:
        current_tag = (
            session.query(FingerprintTag)
            .filter_by(observation_id=observation_id, is_current=True)
            .one_or_none()
        )
        if current_tag is not None:
            return Fingerprint.model_validate_json(current_tag.fingerprint_json)

    # Network calls must not hold SQLite's single-writer lock.
    fingerprint = _tag_with_retry(
        source_excerpt,
        grade_level,
        max_attempts=settings.fingerprint_tagger_max_attempts,
        backoff_seconds=settings.fingerprint_tagger_backoff_seconds,
    )
    with meta_session() as session:
        store_tag(
            session,
            observation_id=observation_id,
            fingerprint=fingerprint,
            tagger_model_id=settings.bedrock_model_id,
            tagger_prompt_version=settings.fingerprint_tagger_prompt_version,
            new_id=uuid4().hex,
            created_at=now,
        )
    return fingerprint


def request_template_build(
    *,
    candidate_id: str,
    source_excerpt: str,
    grade_level: int,
    owner_session_id: str,
) -> BuildRequestOutcome:
    """File one problem and queue a build for it, on a teacher's explicit ask.

    The threshold path (``record_unsupported_shape``) waits for a pattern across
    many teachers' decks. This does not: the teacher in front of us has one
    problem and no built-in template fits it, so the observation is filed and the
    job queued immediately, owned by their session.

    Runs in a background task -- tagging is a Bedrock round trip -- so its only
    channel back to the teacher is the returned outcome, recorded on the session.
    """
    now = datetime.now(timezone.utc)
    try:
        with meta_session() as session:
            observation, _ = record_observation(
                session,
                new_id=uuid4().hex,
                candidate_id=candidate_id,
                source_excerpt=source_excerpt,
                grade_level=grade_level,
                observation_kind=OBSERVATION_KIND_UNSUPPORTED,
                created_at=now,
            )
            observation_id = observation.id
            tag_source_excerpt = observation.source_excerpt
            tag_grade_level = observation.grade_level
    except Exception:
        logger.warning(
            "Could not file an on-demand observation for candidate %s", candidate_id,
            exc_info=True,
        )
        return BuildRequestOutcome(error=_TAGGING_FAILED)

    try:
        fingerprint = _tag_and_store(observation_id, tag_source_excerpt, tag_grade_level, now)
    except Exception:
        logger.warning(
            "Fingerprint tagging failed for on-demand observation %s", observation_id,
            exc_info=True,
        )
        return BuildRequestOutcome(error=_TAGGING_FAILED)

    key = canonical_fingerprint_key(fingerprint)
    try:
        with meta_session() as session:
            if has_version_available_to(session, key, owner_session_id):
                return BuildRequestOutcome(
                    fingerprint_key=key, error=_ALREADY_AVAILABLE, already_available=True
                )
            job = enqueue_on_demand(
                session,
                fingerprint_key=key,
                fingerprint_version=fingerprint.fingerprint_version,
                fingerprint_json=fingerprint.model_dump_json(),
                trigger_observation_ids=_eligible_observation_ids(session, key),
                owner_session_id=owner_session_id,
                new_id=uuid4().hex,
                now=datetime.now(timezone.utc),
            )
    except Exception:
        logger.warning(
            "On-demand enqueue failed for observation %s; the observation is still durable",
            observation_id,
            exc_info=True,
        )
        return BuildRequestOutcome(fingerprint_key=key, error=_TAGGING_FAILED)

    if job is None:
        return BuildRequestOutcome(fingerprint_key=key, error=_ALREADY_BUILDING)
    return BuildRequestOutcome(fingerprint_key=key)


def _eligible_observation_ids(session, fingerprint_key: str) -> list[str]:
    return [
        row.id
        for row in session.query(FallbackObservation)
        .join(FingerprintTag, FingerprintTag.observation_id == FallbackObservation.id)
        .filter(
            FingerprintTag.fingerprint_key == fingerprint_key,
            FingerprintTag.is_current.is_(True),
            FallbackObservation.excluded.is_(False),
        )
        .all()
    ]


def record_unsupported_shape(
    *,
    candidate_id: str,
    source_excerpt: str,
    classification: ClassificationResult,
    picked_template: TemplateName,
    scene_status: str,
    failure_kind: str | None = None,
) -> None:
    settings = get_settings()
    if not settings.meta_templates_enabled:
        return
    reason = classify_text_card_reason(
        classification,
        picked_template,
        scene_status,
        failure_kind=failure_kind,
    )
    if reason is not TextCardReason.UNSUPPORTED_SHAPE:
        return

    now = datetime.now(timezone.utc)
    try:
        with meta_session() as session:
            observation, _ = record_observation(
                session,
                new_id=uuid4().hex,
                candidate_id=candidate_id,
                source_excerpt=source_excerpt,
                grade_level=classification.grade_level,
                observation_kind=OBSERVATION_KIND_UNSUPPORTED,
                created_at=now,
            )
            observation_id = observation.id
            tag_source_excerpt = observation.source_excerpt
            tag_grade_level = observation.grade_level
            current_tag = (
                session.query(FingerprintTag)
                .filter_by(observation_id=observation.id, is_current=True)
                .one_or_none()
            )
            fingerprint = (
                Fingerprint.model_validate_json(current_tag.fingerprint_json)
                if current_tag is not None
                else None
            )
    except Exception:
        logger.warning(
            "Meta observation ingest failed for candidate %s; continuing without it",
            candidate_id,
            exc_info=True,
        )
        return

    if fingerprint is None:
        try:
            # Network calls must not hold SQLite's single-writer lock.
            fingerprint = _tag_with_retry(
                tag_source_excerpt,
                tag_grade_level,
                max_attempts=settings.fingerprint_tagger_max_attempts,
                backoff_seconds=settings.fingerprint_tagger_backoff_seconds,
            )
        except Exception:
            logger.warning(
                "Fingerprint tagging failed for observation %s; leaving it untagged",
                observation_id,
                exc_info=True,
            )
            return

        try:
            with meta_session() as session:
                store_tag(
                    session,
                    observation_id=observation_id,
                    fingerprint=fingerprint,
                    tagger_model_id=settings.bedrock_model_id,
                    tagger_prompt_version=settings.fingerprint_tagger_prompt_version,
                    new_id=uuid4().hex,
                    created_at=now,
                )
        except Exception:
            logger.warning(
                "Fingerprint persistence failed for observation %s",
                observation_id,
                exc_info=True,
            )
            return

    try:
        enqueue_now = datetime.now(timezone.utc)
        with meta_session() as session:
            key = canonical_fingerprint_key(fingerprint)
            eligible = [
                row.id
                for row in session.query(FallbackObservation)
                .join(
                    FingerprintTag,
                    FingerprintTag.observation_id == FallbackObservation.id,
                )
                .filter(
                    FingerprintTag.fingerprint_key == key,
                    FingerprintTag.is_current.is_(True),
                    FallbackObservation.excluded.is_(False),
                )
                .all()
            ]
            evaluate_and_enqueue(
                session,
                fingerprint_key=key,
                fingerprint_version=fingerprint.fingerprint_version,
                fingerprint_json=fingerprint.model_dump_json(),
                trigger_observation_ids=eligible,
                threshold=settings.fingerprint_observation_threshold,
                new_id=uuid4().hex,
                now=enqueue_now,
                max_attempts=settings.job_max_attempts,
            )
            # A race here (IntegrityError → rollback inside evaluate_and_enqueue)
            # only affects this transaction — the observation/tag committed above
            # is untouched.
    except Exception:
        logger.warning(
            "Meta job enqueue failed for observation %s; observation is still durable",
            observation_id,
            exc_info=True,
        )
