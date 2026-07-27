from enum import Enum

from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult

OBSERVATION_KIND_UNSUPPORTED = "unsupported_shape"


class TextCardReason(str, Enum):
    UNSUPPORTED_SHAPE = "unsupported_shape"
    MANUAL_SELECTION = "manual_selection"
    AMBIGUOUS_OR_NON_PROBLEM = "ambiguous_or_non_problem"
    TECHNICAL_FAILURE = "technical_failure"


def classify_text_card_reason(
    classification: ClassificationResult,
    picked_template: TemplateName,
    scene_status: str,
) -> TextCardReason | None:
    # A mismatch/technical fallback surfaces as status="fallback"; it is never a
    # structural gap in the template catalogue.
    if scene_status == "fallback":
        return TextCardReason.TECHNICAL_FAILURE
    if picked_template != TemplateName.TEXT_CARD:
        return None
    structural = [
        option for option in classification.options if option.template != TemplateName.TEXT_CARD
    ]
    if structural:
        return TextCardReason.MANUAL_SELECTION
    if classification.ambiguous or classification.problem_kind == "not_a_problem":
        return TextCardReason.AMBIGUOUS_OR_NON_PROBLEM
    return TextCardReason.UNSUPPORTED_SHAPE


from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.meta.models import FallbackObservation


def record_observation(
    session: Session,
    *,
    new_id: str,
    candidate_id: str,
    source_excerpt: str,
    grade_level: int,
    observation_kind: str,
    created_at: datetime,
) -> tuple[FallbackObservation, bool]:
    existing = session.execute(
        select(FallbackObservation).where(
            FallbackObservation.candidate_id == candidate_id,
            FallbackObservation.observation_kind == observation_kind,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = FallbackObservation(
        id=new_id,
        candidate_id=candidate_id,
        source_excerpt=source_excerpt,
        grade_level=grade_level,
        observation_kind=observation_kind,
        excluded=False,
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row, True
