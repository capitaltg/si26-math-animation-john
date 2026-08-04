from fractions import Fraction

import pytest

from app.meta.dsl.expression import LiteralNode
from app.meta.dsl.scene_program import UnitTapeProgramVisual
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.resolver import evaluate_program_visual
from app.meta.v3.visual_registry import default_visual_registry


class LabelMeasurer:
    """Roughly `ManimTextMeasurer` at the label font size."""

    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


def test_a_program_tape_evaluates_its_two_expressions():
    visual = UnitTapeProgramVisual(
        ref="trail_tape",
        value=LiteralNode(node="literal", value=2.75),
        per_unit=LiteralNode(node="literal", value=1000),
        source_unit="km",
        target_unit="m",
    )

    spec, values = evaluate_program_visual(visual, {})

    assert spec.kind == "unit_tape"
    assert spec.initial_role == "structure"
    assert values == {
        "value": Fraction(11, 4), "per_unit": Fraction(1000),
        "source_unit": "km", "target_unit": "m",
    }


def _measure(value, per_unit=Fraction(1000)):
    from types import SimpleNamespace

    return default_visual_registry().measure(
        SimpleNamespace(kind="unit_tape", ref="trail_tape", initial_role="structure"),
        {"value": value, "per_unit": per_unit, "source_unit": "km", "target_unit": "m"},
        LabelMeasurer(),
    )


def test_a_tape_draws_one_box_per_whole_unit_plus_the_remainder():
    measured = _measure(Fraction(11, 4))

    boxes = measured.payload["boxes"]
    assert [box["source_label"] for box in boxes] == ["1 km", "1 km", "0.75 km"]
    assert [box["target_label"] for box in boxes] == ["1000 m", "1000 m", "750 m"]
    assert [box["fill_fraction"] for box in boxes] == [1.0, 1.0, 0.75]


def test_a_whole_valued_tape_has_no_partial_box():
    measured = _measure(Fraction(3))

    assert [box["fill_fraction"] for box in measured.payload["boxes"]] == [1.0, 1.0, 1.0]
    assert [box["source_label"] for box in measured.payload["boxes"]] == ["1 km"] * 3


def test_a_tape_exposes_a_group_part_per_label_class():
    """The compiler cannot enumerate box indices: the count comes from fixture
    params, which are unknown when the plan compiles. So one action has to be
    able to name every target label at once.
    """
    measured = _measure(Fraction(11, 4))

    group = measured.parts[("target_label", None)]
    per_box = [measured.parts[("target_label", index)] for index in range(3)]
    assert group.bounds.left == min(part.bounds.left for part in per_box)
    assert group.bounds.right == max(part.bounds.right for part in per_box)


def test_a_tape_puts_the_two_labels_in_different_halves_of_its_box():
    """Both labels are measured up front, so revealing the second cannot reflow."""
    measured = _measure(Fraction(2))

    box = measured.parts[("box", 0)].bounds
    source = measured.parts[("source_label", 0)].bounds
    target = measured.parts[("target_label", 0)].bounds
    assert source.bottom > target.top
    assert box.bottom <= target.bottom and source.top <= box.top


def test_a_tape_label_is_a_decimal_not_a_ratio():
    measured = _measure(Fraction(5, 2))

    assert measured.payload["boxes"][-1]["source_label"] == "0.5 km"
    assert measured.payload["boxes"][-1]["target_label"] == "500 m"


def test_a_tape_too_long_to_read_is_rejected_by_the_field_a_reviewer_can_change():
    """The count is derived, so the failure has to name `value`, not `9`.

    `_CARDINALITY_FIELDS` keys on field names present in the evaluated values,
    but a tape's box count is ceil(value) -- no field holds it. A failure naming
    the derived number would tell a reviewer to change something that is not in
    the plan.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        _measure(Fraction(9))

    failure = exc_info.value.failure
    assert failure.code == "visual_extent_unrenderable"
    assert failure.path == "visuals.trail_tape"
    assert "value" in failure.hint
    assert "8" in failure.hint
    assert "number_line" in failure.hint


def test_a_tape_at_the_cap_still_measures():
    measured = _measure(Fraction(8))

    assert len(measured.payload["boxes"]) == 8


def _tape_plan(strategy="unit_substitution", extra_beat_actions=None):
    """A four-beat conversion lesson: orient, name the rate, derive, conclude."""
    from app.meta.dsl.teaching_plan import TeachingPlanDocument

    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Convert a distance in kilometres to metres.",
        "primary_visual": {
            "kind": "unit_tape", "ref": "trail_tape",
            "value": {"node": "field_ref", "field": "distance_km"},
            "per_unit": {"node": "literal", "value": 1000},
            "source_unit": "km", "target_unit": "m",
        },
        "strategy": strategy,
        "answer_unit": "meters",
        "variation_seed": "trail_conversion",
        "beats": [
            {"id": "show_tape", "kind": "orient",
             "targets": [{"visual_ref": "trail_tape"}],
             "intent": "Show the trail as whole kilometres and part of one."},
            {"id": "name_rate", "kind": "focus",
             "targets": [{"visual_ref": "trail_tape", "part": "box", "index": 0}],
             "intent": "One kilometre is one thousand metres.",
             "custom_actions": extra_beat_actions or [
                 {"kind": "callout",
                  "target": {"visual_ref": "trail_tape", "part": "box", "index": 0, "anchor": "bottom"},
                  "text": "1 km = 1000 m"},
             ]},
            {"id": "rename_boxes", "kind": "derive",
             "targets": [{"visual_ref": "trail_tape"}],
             "intent": "Name every box in metres."},
            {"id": "state_total", "kind": "conclude",
             "targets": [{"visual_ref": "trail_tape"}],
             "intent": "Add the metres to get the total."},
        ],
    })


def _answer_expression():
    """distance_km x 1000, the metres the lesson concludes with."""
    from app.meta.dsl.expression import FieldRefNode, LiteralNode, MultiplyNode

    return MultiplyNode(operands=[
        FieldRefNode(field="distance_km"), LiteralNode(value=1000),
    ])


def _compile(plan):
    from app.meta.dsl.v3_common import CompileContext
    from app.meta.v3.compiler import compile_teaching_plan

    return compile_teaching_plan(
        plan,
        _answer_expression(),
        frozenset({"distance_km"}),
        CompileContext(concept_family="transform_other", grade_band="3-5"),
    )


def test_a_tape_plan_compiles_to_a_scene_program():
    program = _compile(_tape_plan())

    assert [visual.kind for visual in program.visuals] == ["unit_tape", "answer_expression"]


def test_unit_substitution_is_rejected_on_another_visual_kind():
    from app.meta.dsl.teaching_plan import TeachingPlanDocument

    payload = _tape_plan().model_dump()
    payload["primary_visual"] = {
        "kind": "bar", "ref": "trail_tape",
        "value": {"node": "literal", "value": 3},
        "maximum": {"node": "literal", "value": 5},
    }
    payload["beats"][1]["custom_actions"] = []
    payload["beats"][1]["targets"] = [
        {"visual_ref": "trail_tape", "part": "segment", "index": 0},
    ]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile(TeachingPlanDocument.model_validate(payload))

    assert exc_info.value.failure.code == "incompatible_strategy"


def test_a_plan_may_not_stage_the_substitution_itself():
    """`unit_substitution` is a choreography the compiler owns.

    `compiler._validate_target` requires an index for any part target, so a plan
    could only ever reveal `target_label[0]` -- leaving the other boxes' labels
    invisible while an affordance check still saw a reveal. Only the compiler can
    name the group part, whose box count is unknown until fixture params arrive.
    Same division of labour as `require_pair_elimination_shape`.
    """
    from app.meta.dsl.teaching_plan import TeachingPlanDocument
    from pydantic import ValidationError

    payload = _tape_plan().model_dump()
    payload["beats"][1]["custom_actions"] = [
        {"kind": "reveal",
         "targets": [{"visual_ref": "trail_tape", "part": "target_label", "index": 0}]},
    ]

    with pytest.raises(ValidationError, match="target_label"):
        TeachingPlanDocument.model_validate(payload)


def test_the_tape_factory_never_runs_for_an_oversized_value():
    """The guard runs before the factory, as it does for `bar`."""
    from types import SimpleNamespace

    from app.meta.v3.visual_registry import VisualRegistry

    registry = VisualRegistry()

    def must_not_run(*, spec, values, measurer):
        raise AssertionError("the factory ran before the count was checked")

    registry.register("unit_tape", must_not_run)

    with pytest.raises(V3ValidationError):
        registry.measure(
            SimpleNamespace(kind="unit_tape", ref="huge"),
            {"value": Fraction(10**6), "per_unit": Fraction(1000),
             "source_unit": "km", "target_unit": "m"},
            LabelMeasurer(),
        )
