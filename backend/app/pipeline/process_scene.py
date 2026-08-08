import logging
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName, TemplateRef
from app.pipeline.extraction import (
    TemplateMismatchError,
    extract_params,
    extract_stated_answer,
)
from app.render.full_render import render_scene_preview, render_scene_to_mp4
from app.templates.registry import get_template, is_static_template_name, static_ref
from app.templates.text_card.params import TextCardParams

BACKOFF_SECONDS = 0.5
TECHNICAL_FAILURE_REASON = "Technical failure during extraction or render"
TEMPLATE_MISMATCH_REASON = (
    "This problem did not fit the chosen visual template; showing the problem text instead."
)

logger = logging.getLogger(__name__)


def _unique_output_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-{uuid4()}.mp4"


def _unique_preview_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-preview-{uuid4()}.mp4"


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
    preview: bool = False,
) -> Scene:
    params = _text_card_params(candidate, reason)
    text_card_ref = static_ref(TemplateName.TEXT_CARD)

    render_path = None
    preview_path = None
    try:
        if preview:
            out = _unique_preview_path(candidate, output_dir)
            render_scene_preview(text_card_ref, params, out)
            preview_path = out
        else:
            out = _unique_output_path(candidate, output_dir)
            render_scene_to_mp4(text_card_ref, params, out)
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
        template=text_card_ref,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="fallback",
        fallback_reason=reason,
        render_path=render_path,
        preview_path=preview_path,
    )


def assemble_scene(
    candidate: Candidate,
    output_dir: Path,
    *,
    template: TemplateRef,
    grade: int,
) -> Scene:
    if template.name == TemplateName.TEXT_CARD:
        params = _text_card_params(candidate)
        preview_path = _unique_preview_path(candidate, output_dir)
        failure_kind = None
        try:
            render_scene_preview(template, params, preview_path)
        except Exception:
            logger.warning(
                "Preview render failed for candidate %s; returning scene without preview",
                candidate.candidate_id,
                exc_info=True,
            )
            preview_path = None
            failure_kind = "render_failure"
        return Scene(
            scene_id=str(uuid4()),
            candidate_id=candidate.candidate_id,
            template=template,
            grade_level=grade,
            params=params.model_dump(mode="json"),
            status="pending_review",
            failure_kind=failure_kind,
            preview_path=preview_path,
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
                candidate, grade, TEMPLATE_MISMATCH_REASON, output_dir, preview=True
            )
        return _fallback_scene(
            candidate, grade, TECHNICAL_FAILURE_REASON, output_dir, preview=True
        )

    if is_static_template_name(template.name):
        stated: tuple = extract_stated_answer(candidate.source_excerpt) or (None, None)
        stated_answer_value, stated_answer_source = stated
    else:
        stated_answer_value, stated_answer_source = None, None

    preview_path = _unique_preview_path(candidate, output_dir)
    try:
        render_scene_preview(template, params, preview_path)
    except Exception:
        logger.warning(
            "Preview render failed for candidate %s; returning scene without preview",
            candidate.candidate_id,
            exc_info=True,
        )
        preview_path = None
    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=template,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="pending_review",
        preview_path=preview_path,
        stated_answer=stated_answer_value,
        stated_answer_source=stated_answer_source,
    )
