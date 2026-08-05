import pytest
from pydantic import ValidationError

from app.meta.dsl.teaching_plan import TeachingPlanDocument


def _median_plan():
    field = lambda name: {"node": "field_ref", "field": name}
    return {
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values",
            "ref": "values",
            "values": [field(f"v{i}") for i in range(1, 8)],
        },
        "supporting_visuals": [],
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together", "custom_actions": []},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward", "custom_actions": []},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value", "custom_actions": []},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median", "custom_actions": []},
        ],
        "variation_seed": "median-demo",
    }


def test_median_teaching_plan_parses():
    plan = TeachingPlanDocument.model_validate(_median_plan())
    assert plan.plan_version == 3
    assert plan.beats[-1].kind == "conclude"


@pytest.mark.parametrize("bad_key,bad_value", [
    ("x", 1.5),
    ("color", "#ff8800"),
    ("python", "scene.play(FadeIn(answer))"),
    ("url", "https://example.test"),
])
def test_generated_plan_forbids_renderer_controls(bad_key, bad_value):
    raw = _median_plan()
    raw["primary_visual"][bad_key] = bad_value
    with pytest.raises(ValidationError):
        TeachingPlanDocument.model_validate(raw)


def _plan_with_generated_text(field_name, value):
    raw = _median_plan()
    if field_name == "learning_objective":
        raw[field_name] = value
    elif field_name == "intent":
        raw["beats"][0][field_name] = value
    elif field_name == "variation_seed":
        raw[field_name] = value
    elif field_name == "label_text":
        raw["primary_visual"] = {"kind": "label", "ref": "caption", "text": value}
    elif field_name == "unit":
        raw["primary_visual"] = {
            "kind": "rectangle_measurement",
            "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"},
            "unit": value,
        }
    elif field_name == "callout_text":
        raw["beats"][0]["custom_actions"] = [{
            "kind": "callout",
            "target": {"visual_ref": "values", "anchor": "top"},
            "text": value,
        }]
    return raw


@pytest.mark.parametrize("field_name", [
    "learning_objective", "intent", "variation_seed", "label_text", "unit", "callout_text",
])
@pytest.mark.parametrize("bad_text", [
    "scene.play(FadeIn(answer))",
    "from manim import FadeIn",
    "../../etc/passwd",
    "https://example.test/scene",
    "position=(1, 2, 0)",
    "color=#ff8800",
    "easing=custom_curve",
    "BLUE",
    "point=(x, y)",
])
def test_every_generated_text_field_rejects_renderer_controls(field_name, bad_text):
    with pytest.raises(ValidationError):
        TeachingPlanDocument.model_validate(_plan_with_generated_text(field_name, bad_text))


@pytest.mark.parametrize("bad_text", [
    "first line\nsecond line",
    "top\rbottom",
    "one\r\ntwo",
    "vert\vtab",
    "form\ffeed",
    "line sep",
    "para sep",
])
def test_plan_rejects_multiline_callout_request_text(bad_text):
    """A plan-authored callout label rides the same single-line rendered
    envelope that the compiled `CalloutRelation` does; reject line breaks
    at the plan schema too so authors get a clear failure rather than a
    rendered overflow."""
    with pytest.raises(ValidationError, match="single line"):
        TeachingPlanDocument.model_validate(
            _plan_with_generated_text("callout_text", bad_text),
        )


@pytest.mark.parametrize("bad_text", ["Circle()", "x = 1"])
def test_identifier_fields_reject_bare_calls_and_assignments(bad_text):
    # Prose fields deliberately allow these -- "Area (square units)" and
    # "P = 2 x (length + width)" are math wording, not renderer controls.
    with pytest.raises(ValidationError):
        TeachingPlanDocument.model_validate(_plan_with_generated_text("variation_seed", bad_text))


def test_generated_text_accepts_legitimate_natural_language():
    raw = _median_plan()
    raw["learning_objective"] = "Explain why the middle value is the median."
    raw["beats"][0]["intent"] = "Show the ordered values together before pairing them."
    plan = TeachingPlanDocument.model_validate(raw)
    assert plan.learning_objective.startswith("Explain")


def test_pair_elimination_rejects_dim_on_a_primary_item():
    plan = _median_plan()
    # On the conclude beat, not the organize beat: the organize beat now rejects
    # every custom action outright (see
    # test_pair_elimination_rejects_a_custom_action_on_the_organize_beat), and
    # this test is pinning the separate whole-visual/item role-change ban.
    plan["beats"][3]["custom_actions"] = [
        {"kind": "dim", "target": {"visual_ref": "values", "part": "item", "index": 0}},
    ]
    with pytest.raises(ValidationError, match="changes the role of the primary visual"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_emphasize_on_a_primary_item():
    plan = _median_plan()
    plan["beats"][3]["custom_actions"] = [
        {"kind": "emphasize",
         "target": {"visual_ref": "values", "part": "item", "index": 3},
         "role": "conclusion"},
    ]
    with pytest.raises(ValidationError, match="changes the role of the primary visual"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_restore_on_a_primary_item():
    plan = _median_plan()
    plan["beats"][3]["custom_actions"] = [
        {"kind": "restore", "target": {"visual_ref": "values", "part": "item", "index": 0}},
    ]
    with pytest.raises(ValidationError, match="changes the role of the primary visual"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_emphasize_on_the_whole_primary_visual():
    plan = _median_plan()
    plan["beats"][3]["custom_actions"] = [
        {"kind": "emphasize", "target": {"visual_ref": "values"}, "role": "focus"},
    ]
    with pytest.raises(ValidationError, match="changes the role of the primary visual"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_a_second_organize_beat():
    plan = _median_plan()
    plan["beats"][0]["kind"] = "organize"
    with pytest.raises(ValidationError, match="exactly one organize beat"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_a_plan_with_no_organize_beat():
    plan = _median_plan()
    plan["beats"][1]["kind"] = "derive"
    with pytest.raises(ValidationError, match="exactly one organize beat"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_a_custom_action_on_the_organize_beat():
    plan = _median_plan()
    plan["beats"][1]["custom_actions"] = [{
        "kind": "callout",
        "target": {"visual_ref": "values", "part": "item", "index": 0, "anchor": "bottom"},
        "text": "eliminated first",
    }]
    with pytest.raises(ValidationError, match="organize beat"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_a_focus_beat_off_the_middle_item():
    plan = _median_plan()
    plan["beats"][2]["targets"] = [{"visual_ref": "values", "part": "item", "index": 2}]
    with pytest.raises(ValidationError, match="unpaired middle item"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_rejects_a_focus_beat_before_the_organize_beat():
    plan = _median_plan()
    plan["beats"][1], plan["beats"][2] = plan["beats"][2], plan["beats"][1]
    with pytest.raises(ValidationError, match="unpaired middle item"):
        TeachingPlanDocument.model_validate(plan)


def test_pair_elimination_allows_a_callout_on_the_middle_item():
    plan = _median_plan()
    plan["beats"][3]["custom_actions"] = [{
        "kind": "callout",
        "target": {"visual_ref": "values", "part": "item", "index": 3, "anchor": "bottom"},
        "text": "This is the median - the middle value!",
    }]
    assert len(TeachingPlanDocument.model_validate(plan).beats[3].custom_actions) == 1


def test_other_strategies_may_still_dim_collection_items():
    plan = _median_plan()
    plan["strategy"] = "short_stagger"
    plan["beats"][1]["custom_actions"] = [
        {"kind": "dim", "target": {"visual_ref": "values", "part": "item", "index": 0}},
    ]
    assert TeachingPlanDocument.model_validate(plan).strategy == "short_stagger"


def test_other_strategies_may_still_restore_collection_items():
    plan = _median_plan()
    plan["strategy"] = "short_stagger"
    plan["beats"][1]["custom_actions"] = [
        {"kind": "restore", "target": {"visual_ref": "values", "part": "item", "index": 0}},
    ]
    assert TeachingPlanDocument.model_validate(plan).strategy == "short_stagger"


def test_other_strategies_may_still_dim_the_whole_primary_visual():
    plan = _median_plan()
    plan["strategy"] = "short_stagger"
    plan["beats"][1]["custom_actions"] = [
        {"kind": "dim", "target": {"visual_ref": "values"}},
    ]
    assert TeachingPlanDocument.model_validate(plan).strategy == "short_stagger"


def test_other_strategies_may_still_restore_the_whole_primary_visual():
    plan = _median_plan()
    plan["strategy"] = "short_stagger"
    plan["beats"][1]["custom_actions"] = [
        {"kind": "restore", "target": {"visual_ref": "values"}},
    ]
    assert TeachingPlanDocument.model_validate(plan).strategy == "short_stagger"


def test_answer_unit_defaults_to_empty_so_stored_plans_still_parse():
    plan = TeachingPlanDocument.model_validate(_median_plan())

    assert plan.answer_unit == ""


def test_answer_unit_carries_the_unit_of_the_result():
    raw = _median_plan()
    raw["answer_unit"] = "meters"
    plan = TeachingPlanDocument.model_validate(raw)

    assert plan.answer_unit == "meters"
