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
