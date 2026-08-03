import pytest
from pydantic import ValidationError

from app.meta.dsl.teaching_plan import TeachingPlanDocument


def _perimeter_plan(**overrides):
    field = lambda name: {"node": "field_ref", "field": name}
    plan = {
        "plan_version": 3,
        "learning_objective": "Find the perimeter of a rectangle using P = 2 × (length + width).",
        "primary_visual": {
            "kind": "rectangle_measurement",
            "ref": "rectangle",
            "length": field("length"),
            "width": field("width"),
            "unit": "cm",
        },
        "supporting_visuals": [
            {"kind": "label", "ref": "formula", "text": "P = 2 × (length + width)"},
            {"kind": "label", "ref": "question", "text": "Perimeter = ?"},
        ],
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the rectangle", "custom_actions": []},
            {"id": "trace", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace every edge", "custom_actions": []},
            {"id": "formula", "kind": "derive", "targets": [{"visual_ref": "formula"}],
             "intent": "Reveal the formula P = 2 × (length + width) and explain why it counts all four sides.",
             "custom_actions": []},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter", "custom_actions": []},
        ],
        "variation_seed": "perimeter-formula",
    }
    plan.update(overrides)
    return plan


def test_named_formula_prose_is_accepted_across_every_prose_field():
    plan = TeachingPlanDocument.model_validate(_perimeter_plan())

    assert plan.learning_objective.endswith("P = 2 × (length + width).")
    assert plan.supporting_visuals[0].text == "P = 2 × (length + width)"
    assert plan.supporting_visuals[1].text == "Perimeter = ?"
    assert plan.beats[2].intent.startswith("Reveal the formula P = 2 × (length + width)")


@pytest.mark.parametrize(
    "prose",
    [
        "Area (square units) grows with both sides.",
        "Count the tiles (rows times columns).",
    ],
)
def test_capitalised_word_before_parenthesis_is_not_a_python_call(prose):
    plan = TeachingPlanDocument.model_validate(_perimeter_plan(learning_objective=prose))

    assert plan.learning_objective == prose


@pytest.mark.parametrize(
    "prose",
    [
        "self.play(FadeIn(rect))",
        "from manim import Scene",
        "See https://example.com for the answer.",
        "Load ../assets/rect.svg first.",
        "eval('2 + 2') gives the perimeter.",
        "Use color: #ff0000 for the border.",
    ],
)
def test_prose_still_rejects_code_urls_paths_and_render_controls(prose):
    with pytest.raises(ValidationError):
        TeachingPlanDocument.model_validate(_perimeter_plan(learning_objective=prose))


def test_identifier_fields_still_reject_assignments_and_calls():
    with pytest.raises(ValidationError):
        TeachingPlanDocument.model_validate(_perimeter_plan(variation_seed="seed = 1"))
