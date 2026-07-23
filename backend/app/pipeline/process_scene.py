import logging
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import classify_candidate
from app.pipeline.extraction import TemplateMismatchError, extract_params
from app.render.full_render import render_scene_thumbnail, render_scene_to_mp4
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


def _unique_thumbnail_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-{uuid4()}.png"


def _fallback_scene(
    candidate: Candidate,
    grade: int,
    reason: str,
    output_dir: Path,
    *,
    thumbnail: bool = False,
) -> Scene:
    lines = [line for line in (candidate.source_excerpt, reason) if line and line.strip()]
    if not lines:
        lines = ["Unable to animate this problem"]
    headline = (candidate.one_line_summary or "").strip() or "Unable to animate this problem"
    params = TextCardParams(headline=headline, lines=lines)

    render_path = None
    thumbnail_path = None
    try:
        if thumbnail:
            out = _unique_thumbnail_path(candidate, output_dir)
            render_scene_thumbnail(TemplateName.TEXT_CARD, params, out)
            thumbnail_path = out
        else:
            out = _unique_output_path(candidate, output_dir)
            render_scene_to_mp4(TemplateName.TEXT_CARD, params, out)
            render_path = out
    except Exception:
        logger.warning(
            "Fallback render failed for candidate %s; returning fallback scene without media",
            candidate.candidate_id,
            exc_info=True,
        )

    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=TemplateName.TEXT_CARD,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="fallback",
        fallback_reason=reason,
        render_path=render_path,
        thumbnail_path=thumbnail_path,
    )


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


def assemble_scene(
    candidate: Candidate,
    output_dir: Path,
    *,
    template: TemplateName,
    grade: int,
) -> Scene:
    _, params_cls = get_template(template)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            thumb_path = _unique_thumbnail_path(candidate, output_dir)
            render_scene_thumbnail(template, params, thumb_path)
            return Scene(
                scene_id=str(uuid4()),
                candidate_id=candidate.candidate_id,
                template=template,
                grade_level=grade,
                params=params.model_dump(mode="json"),
                status="pending_review",
                thumbnail_path=thumb_path,
            )
        except TemplateMismatchError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    if isinstance(last_error, (ValidationError, TemplateMismatchError)):
        return _fallback_scene(
            candidate, grade, TEMPLATE_MISMATCH_REASON, output_dir, thumbnail=True
        )
    return _fallback_scene(
        candidate, grade, TECHNICAL_FAILURE_REASON, output_dir, thumbnail=True
    )
