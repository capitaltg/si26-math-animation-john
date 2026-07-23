def test_assemble_scene_returns_pending_review_with_thumbnail(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    candidate = Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )
    params = NumberLineParams(start=4, steps=[NumberLineStep(operation="add", amount=3)])

    with patch("app.pipeline.process_scene.extract_params", return_value=params), patch(
        "app.pipeline.process_scene.render_scene_thumbnail"
    ) as thumb:
        scene = assemble_scene(
            candidate, tmp_path, template=TemplateName.NUMBER_LINE, grade=1
        )

    assert scene.status == "pending_review"
    assert scene.template == TemplateName.NUMBER_LINE
    assert scene.thumbnail_path is not None
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

    candidate = Candidate(
        candidate_id="c2",
        source_excerpt="A list of 30 spelling words.",
        slide_index=0,
        one_line_summary="Detected: word list",
    )

    with patch(
        "app.pipeline.process_scene.extract_params",
        side_effect=TemplateMismatchError("no add/subtract sequence"),
    ), patch("app.pipeline.process_scene.render_scene_thumbnail"):
        scene = assemble_scene(
            candidate, tmp_path, template=TemplateName.NUMBER_LINE, grade=3
        )

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason == TEMPLATE_MISMATCH_REASON
    assert scene.thumbnail_path is not None


def test_assemble_scene_builds_selected_text_card_without_extraction(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene

    candidate = Candidate(
        candidate_id="c3",
        source_excerpt="Plot one half and three quarters on a number line.",
        slide_index=0,
        one_line_summary="Detected: static plotting task",
    )

    with patch(
        "app.pipeline.process_scene.extract_params",
        side_effect=AssertionError("text cards must bypass extraction"),
    ) as extract, patch("app.pipeline.process_scene.render_scene_thumbnail") as thumbnail:
        scene = assemble_scene(
            candidate, tmp_path, template=TemplateName.TEXT_CARD, grade=3
        )

    assert scene.status == "pending_review"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason is None
    assert scene.params == {
        "headline": "Detected: static plotting task",
        "lines": ["Plot one half and three quarters on a number line."],
    }
    assert scene.thumbnail_path is not None
    extract.assert_not_called()
    thumbnail.assert_called_once()


def test_assemble_scene_keeps_valid_params_when_thumbnail_render_fails(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

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

    def fail_number_line_preview(template, *_args):
        if template == TemplateName.NUMBER_LINE:
            raise RuntimeError("preview failed")

    with patch(
        "app.pipeline.process_scene.extract_params", return_value=params
    ) as extract, patch(
        "app.pipeline.process_scene.render_scene_thumbnail",
        side_effect=fail_number_line_preview,
    ):
        scene = assemble_scene(
            candidate, tmp_path, template=TemplateName.NUMBER_LINE, grade=1
        )

    assert scene.status == "pending_review"
    assert scene.template == TemplateName.NUMBER_LINE
    assert scene.fallback_reason is None
    assert scene.params == {
        "start": 4,
        "steps": [{"operation": "add", "amount": 3}],
    }
    assert scene.thumbnail_path is None
    extract.assert_called_once()
