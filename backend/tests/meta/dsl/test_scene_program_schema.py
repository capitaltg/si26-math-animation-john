import pytest
from pydantic import ValidationError

from app.meta.dsl.scene_program import SceneProgramDocument


def _program():
    return {
        "scene_version": 3,
        "visuals": [{
            "kind": "ordered_values", "ref": "values",
            "values": [{"node": "field_ref", "field": f"v{i}"} for i in range(1, 8)],
            "initial_role": "neutral",
        }],
        "relations": [{
            "kind": "callout", "ref": "median_callout",
            "target": {"visual_ref": "values", "part": "item", "index": 3, "anchor": "bottom"},
            "text": "median",
        }],
        "timeline": [{
            "at_seconds": 0.0, "duration_seconds": 0.8, "beat_id": "reveal_values",
            "action": {"kind": "reveal", "targets": [{"visual_ref": "values"}], "mode": "together"},
        }],
        "total_duration_seconds": 6.0,
        "variation_seed": "median-demo",
        "style_recipe": {
            "palette": "ocean", "composition": "vertical_lesson", "motion_variant": "smooth",
        },
    }


def test_parameterized_program_keeps_anchor_refs_not_fixture_coordinates():
    program = SceneProgramDocument.model_validate(_program())
    assert program.relations[0].target.index == 3
    assert program.relations[0].target.anchor == "bottom"


def test_program_rejects_generated_coordinates():
    raw = SceneProgramDocument.model_json_schema()
    assert '"x"' not in str(raw)
    invalid = _program()
    invalid["x"] = 2.5
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)


@pytest.mark.parametrize("field,value", [
    ("total_duration_seconds", 5.99),
    ("total_duration_seconds", 12.01),
    ("timeline", [{"at_seconds": 0, "duration_seconds": 0.14, "beat_id": "x",
                    "action": {"kind": "draw", "target": {"visual_ref": "values"}}}]),
    ("timeline", [{"at_seconds": 0, "duration_seconds": 2.01, "beat_id": "x",
                    "action": {"kind": "draw", "target": {"visual_ref": "values"}}}]),
])
def test_program_enforces_shared_timing_bounds(field, value):
    invalid = _program()
    invalid[field] = value
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)


@pytest.mark.parametrize("bad_key,bad_value", [
    ("python", "scene.play(FadeIn(answer))"),
    ("url", "https://example.test"),
    ("color", "#ff8800"),
])
def test_program_forbids_renderer_controls(bad_key, bad_value):
    invalid = _program()
    invalid["relations"][0]["text"] = bad_value
    invalid["relations"][0][bad_key] = bad_value
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)


def test_all_program_models_forbid_extra_fields():
    invalid = _program()
    invalid["visuals"][0]["extra"] = True
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)
