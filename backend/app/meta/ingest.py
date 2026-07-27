import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.fingerprint import canonical_fingerprint_key, store_tag, tag_candidate
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


def record_unsupported_shape(
    *,
    candidate_id: str,
    source_excerpt: str,
    classification: ClassificationResult,
    picked_template: TemplateName,
    scene_status: str,
) -> None:
    settings = get_settings()
    if not settings.meta_templates_enabled:
        return
    reason = classify_text_card_reason(classification, picked_template, scene_status)
    if reason is not TextCardReason.UNSUPPORTED_SHAPE:
        return

    now = datetime.now(timezone.utc)
    fingerprint = None
    observation_id = None

    try:
        with meta_session() as session:
            observation, created = record_observation(
                session,
                new_id=uuid4().hex,
                candidate_id=candidate_id,
                source_excerpt=source_excerpt,
                grade_level=classification.grade_level,
                observation_kind=OBSERVATION_KIND_UNSUPPORTED,
                created_at=now,
            )
            if not created:
                return  # already ingested and (re)tagged on a prior pass
            observation_id = observation.id

            try:
                fingerprint = tag_candidate(source_excerpt, classification.grade_level)
            except Exception:
                logger.warning(
                    "Fingerprint tagging failed for observation %s; leaving it untagged",
                    observation.id,
                    exc_info=True,
                )
                return  # observation is preserved; a retag pass can tag it later

            store_tag(
                session,
                observation_id=observation.id,
                fingerprint=fingerprint,
                tagger_model_id=settings.bedrock_model_id,
                tagger_prompt_version=settings.fingerprint_tagger_prompt_version,
                new_id=uuid4().hex,
                created_at=now,
            )
            # Commits here on clean exit — the observation + tag are now durable
            # regardless of what happens in the enqueue attempt below.
    except Exception:
        logger.warning(
            "Meta observation ingest failed for candidate %s; continuing without it",
            candidate_id,
            exc_info=True,
        )
        return

    if fingerprint is None or observation_id is None:
        return  # not created, or tagging failed — nothing to enqueue

    try:
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
                now=now,
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
