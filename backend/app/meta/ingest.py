import logging
from datetime import datetime, timezone
from time import sleep
from uuid import uuid4

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.fingerprint import Fingerprint, canonical_fingerprint_key, store_tag, tag_candidate
from app.meta.jobs import evaluate_and_enqueue
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
