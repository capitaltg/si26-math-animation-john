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
    scene = Scene(scene_id="s1", grade_level=2)
    assert scene.status == "pending_review"
    assert scene.template is None
    assert scene.fallback_reason is None


def test_scene_accepts_a_template_name():
    scene = Scene(scene_id="s2", grade_level=3, template=TemplateName.NUMBER_LINE)
    assert scene.template == TemplateName.NUMBER_LINE
