import pytest
from pydantic import ValidationError

from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dsl.v3_common import TargetRef


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
        "total_duration_seconds": 12.0,
        "variation_seed": "median-demo",
        "style_recipe": {
            "palette": "ocean", "composition": "vertical_lesson", "motion_variant": "smooth",
        },
    }


def test_parameterized_program_keeps_anchor_refs_not_fixture_coordinates():
    program = SceneProgramDocument.model_validate(_program())
    assert program.relations[0].target.index == 3
    assert program.relations[0].target.anchor == "bottom"


@pytest.mark.parametrize("total_duration_seconds,duration_seconds", [
    (6.0, 0.15),
    (11.99, 1.0),
    (8.5, 1.9),
])
def test_program_still_accepts_pre_2x_stored_totals(total_duration_seconds, duration_seconds):
    """Published templates were stored under the old 6-12s / 0.15-2.0s floor.
    `dynamic_templates.load` deserializes their frozen `scene_program_json` on
    every render, so `SceneProgramDocument` must keep accepting those values
    even after the generator's new floor took the current-era minimum to 12s.
    """
    stored = _program()
    stored["total_duration_seconds"] = total_duration_seconds
    stored["timeline"][0]["duration_seconds"] = duration_seconds
    SceneProgramDocument.model_validate(stored)


def test_program_rejects_generated_coordinates():
    raw = SceneProgramDocument.model_json_schema()
    assert "x" not in raw.get("properties", {})
    invalid = _program()
    invalid["x"] = 2.5
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)


@pytest.mark.parametrize("field,value", [
    ("total_duration_seconds", 5.99),
    ("total_duration_seconds", 24.01),
    ("timeline", [{"at_seconds": 0, "duration_seconds": 0.14, "beat_id": "x",
                    "action": {"kind": "draw", "target": {"visual_ref": "values"}}}]),
    ("timeline", [{"at_seconds": 0, "duration_seconds": 4.01, "beat_id": "x",
                    "action": {"kind": "draw", "target": {"visual_ref": "values"}}}]),
])
def test_program_enforces_shared_timing_bounds(field, value):
    invalid = _program()
    invalid[field] = value
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)


@pytest.mark.parametrize("at_seconds,duration_seconds,total_duration_seconds", [
    (23.9, 4.0, 24.0),
    (5.5, 0.6, 6.0),
])
def test_program_rejects_timeline_actions_beyond_scene_end(
    at_seconds, duration_seconds, total_duration_seconds,
):
    invalid = _program()
    invalid["timeline"][0]["at_seconds"] = at_seconds
    invalid["timeline"][0]["duration_seconds"] = duration_seconds
    invalid["total_duration_seconds"] = total_duration_seconds

    with pytest.raises(ValidationError, match="timeline action exceeds total scene duration"):
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


@pytest.mark.parametrize("bad_text", [
    "first line\nsecond line",
    "top\rbottom",
    "one\r\ntwo",
    "vert\vtab",
    "form\ffeed",
    "line sep",
    "para sep",
    "next\x85line",
])
def test_program_rejects_multiline_callout_text(bad_text):
    """A callout's rendered envelope is sized for a single line at
    `FONT_SIZES["label"]` (see layout's `CALLOUT_ENVELOPE`). A newline
    would render extra lines below the anchor that the layout has not
    reserved room for, so the callout would overrun into the row below."""
    invalid = _program()
    invalid["relations"][0]["text"] = bad_text
    with pytest.raises(ValidationError, match="single line"):
        SceneProgramDocument.model_validate(invalid)


def test_all_program_models_forbid_extra_fields():
    invalid = _program()
    invalid["visuals"][0]["extra"] = True
    with pytest.raises(ValidationError):
        SceneProgramDocument.model_validate(invalid)


def test_a_show_answer_stage_action_parses_from_the_program_action_union():
    from pydantic import TypeAdapter

    from app.meta.dsl.scene_program import ProgramAction, ShowAnswerStageAction

    action = TypeAdapter(ProgramAction).validate_python({
        "kind": "show_answer_stage",
        "target": {"visual_ref": "evaluated_answer"},
        "stage": "work",
    })

    assert isinstance(action, ShowAnswerStageAction)
    assert action.stage == "work"


def test_the_unknown_stage_is_not_an_addressable_stage():
    """The unknown text is what the visual is DRAWN as, so the ordinary reveal
    puts it on screen. Only the two transitions away from it are actions."""
    from pydantic import ValidationError

    from app.meta.dsl.scene_program import ShowAnswerStageAction

    with pytest.raises(ValidationError):
        ShowAnswerStageAction(
            target=TargetRef(visual_ref="evaluated_answer"), stage="unknown",
        )


def test_rotate_action_is_a_valid_program_action():
    """M22: RotateAction joins ProgramAction. Compiler-emitted only."""
    from app.meta.dsl.scene_program import RotateAction

    action = RotateAction(target={"visual_ref": "plane"}, iteration=2)
    assert action.kind == "rotate"
    assert action.iteration == 2


def test_rotate_action_rejects_iteration_out_of_range():
    from pydantic import ValidationError

    from app.meta.dsl.scene_program import RotateAction

    with pytest.raises(ValidationError):
        RotateAction(target={"visual_ref": "plane"}, iteration=5)
    with pytest.raises(ValidationError):
        RotateAction(target={"visual_ref": "plane"}, iteration=0)


def test_coordinate_plane_program_visual_defaults_rotation_frames_empty():
    from app.meta.dsl.scene_program import CoordinatePlaneProgramVisual
    from app.meta.dsl.teaching_plan import LiteralNode

    def lit(v):
        return LiteralNode(value=v)

    program_visual = CoordinatePlaneProgramVisual(
        ref="plane",
        x_min=lit(-5), x_max=lit(5), y_min=lit(-5), y_max=lit(5),
    )
    assert program_visual.rotation_frames == []
