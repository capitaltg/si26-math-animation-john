import logging
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import classify_candidate
from app.pipeline.extraction import extract_params
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


def _fallback_scene(candidate: Candidate, grade: int, reason: str, output_dir: Path) -> Scene:
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
        output_path = output_dir / f"{candidate.candidate_id}.mp4"
        render_scene_to_mp4(TemplateName.TEXT_CARD, params, output_path)
        render_path = output_path
    except Exception:
        render_path = None

    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=TemplateName.TEXT_CARD,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="fallback",
        fallback_reason=reason,
        render_path=render_path,
    )


def process_scene(candidate: Candidate, output_dir: Path) -> Scene:
    try:
        classification = classify_candidate(candidate.source_excerpt)
    except Exception as exc:
        logger.exception("Classification failed for candidate %s", candidate.candidate_id)
        return _fallback_scene(
            candidate, DEFAULT_FALLBACK_GRADE, TECHNICAL_FAILURE_REASON, output_dir
        )

    grade = classification.grade_level
    if classification.ambiguous or classification.template is None:
        return _fallback_scene(candidate, grade, CLASSIFICATION_AMBIGUOUS_REASON, output_dir)

    template = classification.template
    _, params_cls = get_template(template)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            output_path = output_dir / f"{candidate.candidate_id}.mp4"
            render_scene_to_mp4(template, params, output_path)
            return Scene(
                scene_id=str(uuid4()),
                candidate_id=candidate.candidate_id,
                template=template,
                grade_level=grade,
                params=params.model_dump(mode="json"),
                status="approved",
                render_path=output_path,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    # A ValidationError means the extracted params could not satisfy the template's
    # structural contract (e.g. a single-operation problem routed to number_line, which
    # needs 2-3 steps). That is a routing mismatch, not a technical failure: re-route to
    # a plain text card with an honest reason rather than mislabeling it.
    if isinstance(last_error, ValidationError):
        logger.info(
            "Candidate %s did not fit template %s; re-routing to text card",
            candidate.candidate_id,
            template,
        )
        return _fallback_scene(candidate, grade, TEMPLATE_MISMATCH_REASON, output_dir)

    logger.exception(
        "Extraction/render failed after retries for candidate %s", candidate.candidate_id, exc_info=last_error
    )
    return _fallback_scene(candidate, grade, TECHNICAL_FAILURE_REASON, output_dir)
