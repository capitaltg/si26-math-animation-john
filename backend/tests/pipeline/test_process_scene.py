from unittest.mock import patch

from app.models.candidate import Candidate
from app.models.scene import TemplateName


def _candidate():
    return Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more, then gives 1 away.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3 - 1",
    )


def _number_line_params():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    return NumberLineParams(
        start=4,
        steps=[NumberLineStep(operation="add", amount=3), NumberLineStep(operation="subtract", amount=1)],
    )


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_clean_success_returns_approved_scene(mock_classify, mock_extract, mock_render, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import process_scene

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=2, ambiguous=False
    )
    mock_extract.return_value = _number_line_params()
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "approved"
    assert scene.template == TemplateName.NUMBER_LINE
    assert scene.render_path == tmp_path / "c1.mp4"
    assert scene.fallback_reason is None
    assert mock_extract.call_count == 1
    assert mock_render.call_count == 1


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_ambiguous_classification_falls_back_without_extracting(mock_classify, mock_extract, mock_render, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import CLASSIFICATION_AMBIGUOUS_REASON, process_scene

    mock_classify.return_value = ClassificationResult(template=None, grade_level=3, ambiguous=True)
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason == CLASSIFICATION_AMBIGUOUS_REASON
    assert mock_extract.call_count == 0  # no blind retry against the same input


@patch("app.pipeline.process_scene.time.sleep")
@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_validation_failure_retries_once_then_succeeds(mock_classify, mock_extract, mock_render, mock_sleep, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import process_scene

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=2, ambiguous=False
    )
    mock_extract.side_effect = [ValueError("bad extraction"), _number_line_params()]
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "approved"
    assert mock_extract.call_count == 2
    assert mock_sleep.call_count == 1


@patch("app.pipeline.process_scene.time.sleep")
@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_repeated_render_failure_falls_back_with_technical_reason(mock_classify, mock_extract, mock_render, mock_sleep, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import TECHNICAL_FAILURE_REASON, process_scene

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=2, ambiguous=False
    )
    mock_extract.return_value = _number_line_params()
    mock_render.side_effect = RuntimeError("manim boom")

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason.startswith(TECHNICAL_FAILURE_REASON)
    assert mock_extract.call_count == 2  # retried once before falling back
    assert scene.render_path is None  # even the fallback render failed


@patch("app.pipeline.process_scene.time.sleep")
@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_persistent_contract_mismatch_reroutes_to_text_card(mock_classify, mock_extract, mock_render, mock_sleep, tmp_path):
    """A single-operation problem routed to number_line yields params that can never
    satisfy the >=2-step guard. That is a template mismatch, not a technical failure,
    so the user should still get a readable text card with an honest reason."""
    from pydantic import ValidationError

    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import TEMPLATE_MISMATCH_REASON, TECHNICAL_FAILURE_REASON, process_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    try:
        NumberLineParams(start=6, steps=[NumberLineStep(operation="add", amount=3)])
        raise AssertionError("expected a ValidationError for a single-step number line")
    except ValidationError as exc:
        contract_error = exc

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=1, ambiguous=False
    )
    mock_extract.side_effect = contract_error
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason == TEMPLATE_MISMATCH_REASON
    assert scene.fallback_reason != TECHNICAL_FAILURE_REASON
    assert scene.render_path == tmp_path / "c1.mp4"  # content still rendered
    assert mock_extract.call_count == 2  # retried once (extraction is nondeterministic)


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.classify_candidate")
def test_blank_source_excerpt_falls_back_without_raising(mock_classify, mock_render, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import process_scene

    mock_classify.return_value = ClassificationResult(template=None, grade_level=3, ambiguous=True)
    mock_render.return_value = tmp_path / "c1.mp4"

    candidate = Candidate(
        candidate_id="c1", source_excerpt="   ", slide_index=0, one_line_summary="Detected: x"
    )

    scene = process_scene(candidate, tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.classify_candidate")
def test_whitespace_only_summary_falls_back_without_raising(mock_classify, mock_render, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import process_scene

    mock_classify.return_value = ClassificationResult(template=None, grade_level=3, ambiguous=True)
    mock_render.return_value = tmp_path / "c1.mp4"

    candidate = Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more, then gives 1 away.",
        slide_index=0,
        one_line_summary="   ",
    )

    scene = process_scene(candidate, tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_classification_exception_falls_back_technically(mock_classify, mock_extract, mock_render, tmp_path):
    from app.pipeline.process_scene import TECHNICAL_FAILURE_REASON, process_scene

    mock_classify.side_effect = RuntimeError("bedrock down")
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.fallback_reason.startswith(TECHNICAL_FAILURE_REASON)
    assert mock_extract.call_count == 0
