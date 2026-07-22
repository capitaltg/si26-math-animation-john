import logging
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import classify_candidate
from app.pipeline.extraction import TemplateMismatchError, extract_params
from app.render.full_render import render_scene_to_mp4
from app.templates.registry import get_template
from app.templates.text_card.params import TextCardParams

BACKOFF_SECONDS = 0.5
DEFAULT_FALLBACK_GRADE = 0
CLASSIFICATION_AMBIGUOUS_REASON = (
    "Classification ambiguous or unsupported: no template confidently fits this problem."
)
TECHNICAL_FAILURE_REASON = "Technical failure during extraction or render"
TEMPLATE_MISMATCH_REASON = (
    "This problem did not fit the chosen visual template; showing the problem text instead."
)

logger = logging.getLogger(__name__)


def _unique_output_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-{uuid4()}.mp4"


def _text_card_scene(
    candidate: Candidate,
    grade: int,
    output_dir: Path,
    *,
    reason: str | None = None,
) -> Scene:
    """Render a text card. With a reason it is an honest fallback from a failed or
    unavailable visual template; without one it is a deliberately chosen text card
    (status "approved"), so no fallback_reason is attached."""
    reason = reason or None  # normalize "" to None so the Scene invariant holds
    lines = [line for line in (candidate.source_excerpt, reason) if line and line.strip()]
    if not lines:
        lines = ["Unable to animate this problem"]
    headline = (candidate.one_line_summary or "").strip() or "Unable to animate this problem"
    params = TextCardParams(
        headline=headline,
        lines=lines,
    )
    render_path = None
    try:
        output_path = _unique_output_path(candidate, output_dir)
        render_scene_to_mp4(TemplateName.TEXT_CARD, params, output_path)
        render_path = output_path
    except Exception:
        logger.warning(
            "Text-card render failed for candidate %s; returning scene without a clip",
            candidate.candidate_id,
            exc_info=True,
        )
        render_path = None

    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=TemplateName.TEXT_CARD,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="fallback" if reason else "approved",
        fallback_reason=reason,
        render_path=render_path,
    )


def _fallback_scene(candidate: Candidate, grade: int, reason: str, output_dir: Path) -> Scene:
    return _text_card_scene(candidate, grade, output_dir, reason=reason)


def process_scene(
    candidate: Candidate,
    output_dir: Path,
    *,
    template: TemplateName | None = None,
    grade: int | None = None,
) -> Scene:
    if template is None:
        try:
            classification = classify_candidate(candidate.source_excerpt)
        except Exception:
            logger.exception("Classification failed for candidate %s", candidate.candidate_id)
            return _fallback_scene(
                candidate,
                DEFAULT_FALLBACK_GRADE,
                TECHNICAL_FAILURE_REASON,
                output_dir,
            )

        resolved_grade = classification.grade_level
        if classification.ambiguous or not classification.options:
            return _fallback_scene(
                candidate,
                resolved_grade,
                CLASSIFICATION_AMBIGUOUS_REASON,
                output_dir,
            )
        resolved_template = classification.options[0].template
    else:
        resolved_template = template
        resolved_grade = grade if grade is not None else DEFAULT_FALLBACK_GRADE

    # A text card carries the problem statement verbatim — there are no numeric params
    # to extract. Render it directly rather than routing through extract_params, which
    # would decline the non-numeric schema and then re-route here anyway.
    if resolved_template == TemplateName.TEXT_CARD:
        return _text_card_scene(candidate, resolved_grade, output_dir)

    _, params_cls = get_template(resolved_template)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            output_path = _unique_output_path(candidate, output_dir)
            render_scene_to_mp4(resolved_template, params, output_path)
            return Scene(
                scene_id=str(uuid4()),
                candidate_id=candidate.candidate_id,
                template=resolved_template,
                grade_level=resolved_grade,
                params=params.model_dump(mode="json"),
                status="approved",
                render_path=output_path,
            )
        except TemplateMismatchError as exc:
            # A structural mismatch will not change on retry — stop immediately.
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    # A ValidationError or TemplateMismatchError means extraction could not satisfy
    # the chosen template's structural contract. Preserve the user's content as an
    # honest text-card fallback.
    if isinstance(last_error, (ValidationError, TemplateMismatchError)):
        logger.info(
            "Candidate %s did not fit template %s; re-routing to text card",
            candidate.candidate_id,
            resolved_template,
        )
        return _fallback_scene(
            candidate,
            resolved_grade,
            TEMPLATE_MISMATCH_REASON,
            output_dir,
        )

    logger.exception(
        "Extraction/render failed after retries for candidate %s",
        candidate.candidate_id,
        exc_info=last_error,
    )
    return _fallback_scene(
        candidate,
        resolved_grade,
        TECHNICAL_FAILURE_REASON,
        output_dir,
    )
