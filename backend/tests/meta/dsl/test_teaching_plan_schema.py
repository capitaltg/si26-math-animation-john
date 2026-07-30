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
])
def test_every_generated_text_field_rejects_renderer_controls(field_name, bad_text):
    with pytest.raises(ValidationError):
        TeachingPlanDocument.model_validate(_plan_with_generated_text(field_name, bad_text))


def test_generated_text_accepts_legitimate_natural_language():
    raw = _median_plan()
    raw["learning_objective"] = "Explain why the middle value is the median."
    raw["beats"][0]["intent"] = "Show the ordered values together before pairing them."
    plan = TeachingPlanDocument.model_validate(raw)
    assert plan.learning_objective.startswith("Explain")
