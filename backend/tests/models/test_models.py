from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName


def test_candidate_round_trips_through_json():
    candidate = Candidate(
        candidate_id="c1", source_excerpt="3 + 4", slide_index=2,
        one_line_summary="Detected: 3 + 4",
    )
    restored = Candidate.model_validate_json(candidate.model_dump_json())
    assert restored == candidate


def test_scene_defaults_to_pending_review():
    scene = Scene(scene_id="s1", candidate_id="c1", grade_level=2)
    assert scene.status == "pending_review"
    assert scene.template is None
    assert scene.fallback_reason is None


def test_scene_accepts_a_template_name():
    scene = Scene(
        scene_id="s2",
        candidate_id="c2",
        grade_level=3,
        template=TemplateName.NUMBER_LINE,
    )
    assert scene.template == TemplateName.NUMBER_LINE


def test_scene_round_trip_retains_manual_source_and_stated_answer():
    scene = Scene(
        scene_id="s3",
        grade_level=4,
        manual_source_text="Three halves plus two halves equals five halves.",
        stated_answer=Fraction(5, 2),
    )

    restored = Scene.model_validate_json(scene.model_dump_json())

    assert restored.manual_source_text == scene.manual_source_text
    assert restored.stated_answer == Fraction(5, 2)


@pytest.mark.parametrize("grade_level", [-1, 9])
def test_scene_rejects_grade_outside_k_to_eight(grade_level):
    with pytest.raises(ValidationError):
        Scene(scene_id="s4", candidate_id="c4", grade_level=grade_level)


def test_scene_requires_exactly_one_source():
    with pytest.raises(ValidationError):
        Scene(scene_id="s5", grade_level=2)

    with pytest.raises(ValidationError):
        Scene(
            scene_id="s6",
            candidate_id="c6",
            manual_source_text="Four plus three",
            grade_level=2,
        )


def test_fallback_scene_requires_a_reason():
    with pytest.raises(ValidationError):
        Scene(scene_id="s7", candidate_id="c7", grade_level=2, status="fallback")


def test_approved_fallback_scene_keeps_its_reason():
    scene = Scene(
        scene_id="s8",
        candidate_id="c8",
        template=TemplateName.TEXT_CARD,
        grade_level=2,
        status="fallback",
        fallback_reason="This problem did not fit the chosen visual template.",
    )
    assert scene.status == "fallback"
    assert scene.fallback_reason


def test_scene_accepts_candidate_ids_as_the_sole_source():
    from app.models.scene import Scene

    scene = Scene(
        scene_id="s1",
        candidate_ids=["c1", "c2"],
        grade_level=2,
        status="approved",
    )
    assert scene.candidate_ids == ["c1", "c2"]
    assert scene.candidate_id is None


def test_scene_rejects_both_candidate_id_and_candidate_ids():
    from pydantic import ValidationError

    from app.models.scene import Scene

    with pytest.raises(ValidationError):
        Scene(
            scene_id="s1",
            candidate_id="c1",
            candidate_ids=["c2", "c3"],
            grade_level=2,
            status="approved",
        )


def test_scene_rejects_none_of_the_three_sources():
    from pydantic import ValidationError

    from app.models.scene import Scene

    with pytest.raises(ValidationError):
        Scene(scene_id="s1", grade_level=2, status="approved")
