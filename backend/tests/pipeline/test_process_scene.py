from unittest.mock import patch


@patch("app.pipeline.process_scene.extract_stated_answer", return_value=None)
def test_assemble_scene_returns_pending_review_with_preview(mock_stated, tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep
    from app.templates.registry import static_ref

    candidate = Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )
    params = NumberLineParams(start=4, steps=[NumberLineStep(operation="add", amount=3)])
    ref = static_ref(TemplateName.NUMBER_LINE)

    with patch("app.pipeline.process_scene.extract_params", return_value=params), patch(
        "app.pipeline.process_scene.render_scene_preview"
    ) as thumb:
        scene = assemble_scene(candidate, tmp_path, template=ref, grade=1)

    assert scene.status == "pending_review"
    assert scene.template == ref
    assert scene.preview_path is not None
    assert scene.params["start"] == 4
    thumb.assert_called_once()


def test_assemble_scene_falls_back_on_template_mismatch(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.extraction import TemplateMismatchError
    from app.pipeline.process_scene import (
        TEMPLATE_MISMATCH_REASON,
        assemble_scene,
    )
    from app.templates.registry import static_ref

    candidate = Candidate(
        candidate_id="c2",
        source_excerpt="A list of 30 spelling words.",
        slide_index=0,
        one_line_summary="Detected: word list",
    )

    with patch(
        "app.pipeline.process_scene.extract_params",
        side_effect=TemplateMismatchError("no add/subtract sequence"),
    ), patch("app.pipeline.process_scene.render_scene_preview"):
        scene = assemble_scene(
            candidate, tmp_path, template=static_ref(TemplateName.NUMBER_LINE), grade=3
        )

    assert scene.status == "fallback"
    assert scene.template == static_ref(TemplateName.TEXT_CARD)
    assert scene.fallback_reason == TEMPLATE_MISMATCH_REASON
    assert scene.preview_path is not None


def test_assemble_scene_builds_selected_text_card_without_extraction(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.registry import static_ref

    candidate = Candidate(
        candidate_id="c3",
        source_excerpt="Plot one half and three quarters on a number line.",
        slide_index=0,
        one_line_summary="Detected: static plotting task",
    )

    with patch(
        "app.pipeline.process_scene.extract_params",
        side_effect=AssertionError("text cards must bypass extraction"),
    ) as extract, patch("app.pipeline.process_scene.render_scene_preview") as thumbnail:
        scene = assemble_scene(
            candidate, tmp_path, template=static_ref(TemplateName.TEXT_CARD), grade=3
        )

    assert scene.status == "pending_review"
    assert scene.template == static_ref(TemplateName.TEXT_CARD)
    assert scene.fallback_reason is None
    assert scene.params == {
        "headline": "Detected: static plotting task",
        "lines": ["Plot one half and three quarters on a number line."],
    }
    assert scene.preview_path is not None
    extract.assert_not_called()
    thumbnail.assert_called_once()


def test_selected_text_card_reports_preview_render_failure(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.registry import static_ref

    candidate = Candidate(
        candidate_id="c-render-failure",
        source_excerpt="Plot one half and three quarters on a number line.",
        slide_index=0,
        one_line_summary="Detected: static plotting task",
    )

    with patch(
        "app.pipeline.process_scene.render_scene_preview",
        side_effect=RuntimeError("preview failed"),
    ):
        scene = assemble_scene(
            candidate, tmp_path, template=static_ref(TemplateName.TEXT_CARD), grade=3
        )

    assert scene.status == "pending_review"
    assert scene.failure_kind == "render_failure"
    assert scene.preview_path is None


@patch("app.pipeline.process_scene.extract_stated_answer", return_value=None)
def test_assemble_scene_keeps_valid_params_when_preview_render_fails(mock_stated, tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep
    from app.templates.registry import static_ref

    candidate = Candidate(
        candidate_id="c4",
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )
    params = NumberLineParams(
        start=4,
        steps=[NumberLineStep(operation="add", amount=3)],
    )
    ref = static_ref(TemplateName.NUMBER_LINE)

    def fail_number_line_preview(template, *_args):
        if template.name == TemplateName.NUMBER_LINE:
            raise RuntimeError("preview failed")

    with patch(
        "app.pipeline.process_scene.extract_params", return_value=params
    ) as extract, patch(
        "app.pipeline.process_scene.render_scene_preview",
        side_effect=fail_number_line_preview,
    ):
        scene = assemble_scene(candidate, tmp_path, template=ref, grade=1)

    assert scene.status == "pending_review"
    assert scene.template == ref
    assert scene.fallback_reason is None
    assert scene.params == {
        "start": 4,
        "steps": [{"operation": "add", "amount": 3}],
    }
    assert scene.preview_path is None
    extract.assert_called_once()


@patch("app.pipeline.process_scene.extract_stated_answer")
@patch("app.pipeline.process_scene.extract_params")
def test_assemble_scene_populates_stated_answer(mock_extract, mock_answer, tmp_path):
    from fractions import Fraction

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep
    from app.templates.registry import static_ref

    mock_extract.return_value = NumberLineParams(
        start=3, steps=[NumberLineStep(operation="add", amount=5)]
    )
    mock_answer.return_value = (Fraction(9), "= 9")

    candidate = Candidate(
        candidate_id="c1",
        slide_index=0,
        source_excerpt="What is 3 + 5? = 9",
        one_line_summary="Add small",
    )
    template = static_ref(TemplateName.NUMBER_LINE)

    scene = assemble_scene(candidate, tmp_path, template=template, grade=2)

    assert scene.stated_answer == Fraction(9)
    assert scene.stated_answer_source == "= 9"


@patch("app.pipeline.process_scene.extract_stated_answer")
@patch("app.pipeline.process_scene.extract_params")
def test_assemble_scene_stated_answer_extractor_failure_is_non_fatal(
    mock_extract, mock_answer, tmp_path
):
    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep
    from app.templates.registry import static_ref

    mock_extract.return_value = NumberLineParams(
        start=3, steps=[NumberLineStep(operation="add", amount=5)]
    )
    mock_answer.return_value = None

    candidate = Candidate(
        candidate_id="c1",
        slide_index=0,
        source_excerpt="What is 3 + 5?",
        one_line_summary="Add small",
    )
    template = static_ref(TemplateName.NUMBER_LINE)

    scene = assemble_scene(candidate, tmp_path, template=template, grade=2)

    assert scene.stated_answer is None
    assert scene.stated_answer_source is None


@patch("app.pipeline.process_scene.extract_stated_answer")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.is_static_template_name")
def test_assemble_scene_skips_stated_answer_for_dynamic_templates(
    mock_is_static, mock_extract, mock_answer, tmp_path
):
    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep
    from app.templates.registry import static_ref

    mock_is_static.return_value = False
    mock_extract.return_value = NumberLineParams(
        start=3, steps=[NumberLineStep(operation="add", amount=5)]
    )

    candidate = Candidate(
        candidate_id="c1",
        slide_index=0,
        source_excerpt="What is 3 + 5?",
        one_line_summary="Add small",
    )
    template = static_ref(TemplateName.NUMBER_LINE)

    scene = assemble_scene(candidate, tmp_path, template=template, grade=2)

    assert scene.stated_answer is None
    assert scene.stated_answer_source is None
    mock_answer.assert_not_called()
