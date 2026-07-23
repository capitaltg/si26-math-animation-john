import logging
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.extraction import TemplateMismatchError, extract_params
from app.render.full_render import render_scene_thumbnail, render_scene_to_mp4
from app.templates.registry import get_template
from app.templates.text_card.params import TextCardParams

BACKOFF_SECONDS = 0.5
TECHNICAL_FAILURE_REASON = "Technical failure during extraction or render"
TEMPLATE_MISMATCH_REASON = (
    "This problem did not fit the chosen visual template; showing the problem text instead."
)

logger = logging.getLogger(__name__)


def _unique_output_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-{uuid4()}.mp4"


def _unique_thumbnail_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-{uuid4()}.png"


def _text_card_params(candidate: Candidate, reason: str | None = None) -> TextCardParams:
    lines = [line for line in (candidate.source_excerpt, reason) if line and line.strip()]
    if not lines:
        lines = ["Unable to animate this problem"]
    headline = (candidate.one_line_summary or "").strip() or "Unable to animate this problem"
    return TextCardParams(headline=headline, lines=lines)


def _fallback_scene(
    candidate: Candidate,
    grade: int,
    reason: str,
    output_dir: Path,
    *,
    thumbnail: bool = False,
) -> Scene:
    params = _text_card_params(candidate, reason)

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


def assemble_scene(
    candidate: Candidate,
    output_dir: Path,
    *,
    template: TemplateName,
    grade: int,
) -> Scene:
    if template == TemplateName.TEXT_CARD:
        params = _text_card_params(candidate)
        thumb_path = _unique_thumbnail_path(candidate, output_dir)
        try:
            render_scene_thumbnail(template, params, thumb_path)
        except Exception:
            logger.warning(
                "Thumbnail render failed for candidate %s; returning scene without preview",
                candidate.candidate_id,
                exc_info=True,
            )
            thumb_path = None
        return Scene(
            scene_id=str(uuid4()),
            candidate_id=candidate.candidate_id,
            template=template,
            grade_level=grade,
            params=params.model_dump(mode="json"),
            status="pending_review",
            thumbnail_path=thumb_path,
        )

    _, params_cls = get_template(template)

    last_error: Exception | None = None
    params = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            break
        except TemplateMismatchError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    if params is None:
        if isinstance(last_error, (ValidationError, TemplateMismatchError)):
            return _fallback_scene(
                candidate, grade, TEMPLATE_MISMATCH_REASON, output_dir, thumbnail=True
            )
        return _fallback_scene(
            candidate, grade, TECHNICAL_FAILURE_REASON, output_dir, thumbnail=True
        )

    thumb_path = _unique_thumbnail_path(candidate, output_dir)
    try:
        render_scene_thumbnail(template, params, thumb_path)
    except Exception:
        logger.warning(
            "Thumbnail render failed for candidate %s; returning scene without preview",
            candidate.candidate_id,
            exc_info=True,
        )
        thumb_path = None
    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=template,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="pending_review",
        thumbnail_path=thumb_path,
    )
