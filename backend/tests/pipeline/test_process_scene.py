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
