import time
from pathlib import Path
from uuid import uuid4

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


def _fallback_scene(candidate: Candidate, grade: int, reason: str, output_dir: Path) -> Scene:
    lines = [line for line in (candidate.source_excerpt, reason) if line and line.strip()]
    if not lines:
        lines = ["Unable to animate this problem"]
    params = TextCardParams(
        headline=candidate.one_line_summary or "Unable to animate this problem",
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
        return _fallback_scene(
            candidate, DEFAULT_FALLBACK_GRADE, f"{TECHNICAL_FAILURE_REASON}: {exc}", output_dir
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

    return _fallback_scene(candidate, grade, f"{TECHNICAL_FAILURE_REASON}: {last_error}", output_dir)
