"""End-to-end tests for the fraction equivalence and arithmetic strategies (M2).

`equivalence_align` teaches "these two partitions describe the same amount",
so the plan must declare a second partition and reveal it. Fraction arithmetic
across unlike denominators (`common_denominator_bridge`) additionally needs the
LCD partition on-screen. The compiler enforces the shape; the quality gate
enforces that each supporting partition actually reveals.
"""

import pytest

from app.meta.dsl.expression import (
    AddNode, FractionNode, LiteralNode, SubtractNode,
)
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.quality import validate_static_quality


def _partition(ref, parts):
    return {
        "kind": "partition", "ref": ref,
        "whole": {"node": "literal", "value": 1},
        "parts": {"node": "literal", "value": parts},
    }


def _equivalence_plan(**overrides):
    """A four-beat plan for 2/3 = 4/6.

    Two partitions of one whole -- thirds and sixths -- reveal in turn, then
    align. The answer's fraction is the equivalent one; `FractionNode` is an
    operation so `_work_beat_id` lifts the calculation onto the derive beat.
    """
    payload = {
        "plan_version": 3,
        "learning_objective": "Show that two-thirds equals four-sixths.",
        "primary_visual": _partition("thirds", 3),
        "supporting_visuals": [_partition("sixths", 6)],
        "strategy": "equivalence_align",
        "variation_seed": "two-thirds-equivalence",
        "beats": [
            {"id": "reveal_thirds", "kind": "orient",
             "targets": [{"visual_ref": "thirds"}],
             "intent": "Show the thirds partition."},
            {"id": "reveal_sixths", "kind": "reveal",
             "targets": [{"visual_ref": "sixths"}],
             "intent": "Show the sixths partition beside it."},
            {"id": "align_parts", "kind": "derive",
             "targets": [{"visual_ref": "thirds"}, {"visual_ref": "sixths"}],
             "intent": "Match two-thirds against four-sixths."},
            {"id": "state_equivalence", "kind": "conclude",
             "targets": [{"visual_ref": "thirds"}],
             "intent": "The two partitions describe the same amount."},
        ],
    }
    payload.update(overrides)
    return TeachingPlanDocument.model_validate(payload)


def _bridge_plan(*, primary_parts, second_parts, lcd_parts, operation):
    """A four-beat plan for a like-whole fraction sum or difference.

    Three partitions: the two operands and the LCD bridge that refines both.
    `operation` is `"add"` or `"subtract"` so the answer_expression matches the
    lesson's own move.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": f"Combine two fractions using an LCD of {lcd_parts}.",
        "primary_visual": _partition("first_operand", primary_parts),
        "supporting_visuals": [
            _partition("second_operand", second_parts),
            _partition("bridge_lcd", lcd_parts),
        ],
        "strategy": "common_denominator_bridge",
        "variation_seed": f"bridge-{primary_parts}-{second_parts}-{operation}",
        "beats": [
            {"id": "reveal_first", "kind": "orient",
             "targets": [{"visual_ref": "first_operand"}],
             "intent": "Show the first operand's partition."},
            {"id": "reveal_others", "kind": "reveal",
             "targets": [
                 {"visual_ref": "second_operand"},
                 {"visual_ref": "bridge_lcd"},
             ],
             "intent": "Show the second operand and the LCD bridge."},
            {"id": "combine_on_bridge", "kind": "derive",
             "targets": [
                 {"visual_ref": "first_operand"},
                 {"visual_ref": "second_operand"},
                 {"visual_ref": "bridge_lcd"},
             ],
             "intent": "Combine the two operands on the LCD."},
            {"id": "state_result", "kind": "conclude",
             "targets": [{"visual_ref": "bridge_lcd"}],
             "intent": "The bridge partition carries the answer."},
        ],
    })


def _compile_and_gate(plan, answer_expression, known_fields=frozenset()):
    program = compile_teaching_plan(
        plan, answer_expression, known_fields,
        CompileContext(concept_family="proportion_and_scale", grade_band="3-5"),
    )
    validate_static_quality(plan, program).require_passed()
    return program


def _equivalence_answer():
    """4/6 written as a fraction node so `format_number` displays it that way."""
    return FractionNode(operands=[LiteralNode(value=4), LiteralNode(value=6)])


def _add_answer():
    """1/2 + 1/3 = 5/6. The work stage shows the sum, the value stage 5/6."""
    return AddNode(operands=[
        FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=2)]),
        FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=3)]),
    ])


def _subtract_answer():
    """3/4 - 1/2 = 1/4."""
    return SubtractNode(operands=[
        FractionNode(operands=[LiteralNode(value=3), LiteralNode(value=4)]),
        FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=2)]),
    ])


def test_equivalence_align_compiles_two_thirds_equals_four_sixths():
    program = _compile_and_gate(_equivalence_plan(), _equivalence_answer())

    kinds = [visual.kind for visual in program.visuals]
    assert kinds == ["partition", "partition", "answer_expression"]

    revealed_refs = {
        target.visual_ref
        for entry in program.timeline
        if entry.action.kind == "reveal"
        for target in entry.action.targets
    }
    assert {"thirds", "sixths"}.issubset(revealed_refs), (
        "the equivalent partition must land on-screen for the strategy's own move to read"
    )


def test_equivalence_align_needs_exactly_one_supporting_partition():
    payload = _equivalence_plan().model_dump()
    payload["supporting_visuals"] = []
    payload["beats"] = [
        beat for beat in payload["beats"] if beat["id"] != "reveal_sixths"
    ]
    for beat in payload["beats"]:
        beat["targets"] = [
            target for target in beat["targets"] if target["visual_ref"] != "sixths"
        ]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    assert exc_info.value.failure.code == "equivalence_align_requires_one_supporting_partition"


def test_equivalence_align_rejects_a_non_partition_primary():
    payload = _equivalence_plan().model_dump()
    payload["primary_visual"] = {
        "kind": "bar", "ref": "thirds",
        "value": {"node": "literal", "value": 2},
        "maximum": {"node": "literal", "value": 3},
    }

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    assert exc_info.value.failure.code == "incompatible_strategy"


def test_equivalence_align_rejects_a_plan_that_never_reveals_the_equivalent_partition():
    """A `group_reveal` primary + a supporting visual never named by any beat is decorative.

    The strategy affordance check must catch the missing reveal so the lesson
    fails at compile time rather than as an animation with a dangling extra
    circle.
    """
    payload = _equivalence_plan().model_dump()
    # Drop the second beat that revealed `sixths` -- and everything downstream
    # that named it -- so no beat targets the supporting partition.
    payload["beats"] = [
        beat for beat in payload["beats"] if beat["id"] != "reveal_sixths"
    ]
    for beat in payload["beats"]:
        beat["targets"] = [
            target for target in beat["targets"] if target["visual_ref"] != "sixths"
        ]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    # The quality gate raises with the check's code as the failure code.
    assert exc_info.value.failure.code == "static_process_visual"


def test_common_denominator_bridge_compiles_one_half_plus_one_third():
    plan = _bridge_plan(primary_parts=2, second_parts=3, lcd_parts=6, operation="add")

    program = _compile_and_gate(plan, _add_answer())

    kinds = [visual.kind for visual in program.visuals]
    assert kinds == ["partition", "partition", "partition", "answer_expression"]

    revealed_refs = {
        target.visual_ref
        for entry in program.timeline
        if entry.action.kind == "reveal"
        for target in entry.action.targets
    }
    assert {"first_operand", "second_operand", "bridge_lcd"}.issubset(revealed_refs), (
        "the LCD bridge must land on-screen so the animation shows the common denominator"
    )
    assert any(
        entry.action.kind == "show_answer_stage" and entry.action.stage == "work"
        for entry in program.timeline
    ), "the sum's arithmetic must show before the answer resolves"


def test_common_denominator_bridge_compiles_three_quarters_minus_one_half():
    plan = _bridge_plan(primary_parts=4, second_parts=2, lcd_parts=4, operation="subtract")

    program = _compile_and_gate(plan, _subtract_answer())

    kinds = [visual.kind for visual in program.visuals]
    assert kinds == ["partition", "partition", "partition", "answer_expression"]

    revealed_refs = {
        target.visual_ref
        for entry in program.timeline
        if entry.action.kind == "reveal"
        for target in entry.action.targets
    }
    assert {"first_operand", "second_operand", "bridge_lcd"}.issubset(revealed_refs)


def test_common_denominator_bridge_needs_two_supporting_partitions():
    payload = _bridge_plan(
        primary_parts=2, second_parts=3, lcd_parts=6, operation="add",
    ).model_dump()
    payload["supporting_visuals"] = payload["supporting_visuals"][:1]
    for beat in payload["beats"]:
        pruned = [
            target for target in beat["targets"] if target["visual_ref"] != "bridge_lcd"
        ]
        # Every beat needs at least one target; the conclude beat originally
        # named the bridge, so fall back to the primary operand when the bridge
        # is the only target the beat had.
        beat["targets"] = pruned or [{"visual_ref": "first_operand"}]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _add_answer())

    assert exc_info.value.failure.code == "common_denominator_bridge_requires_two_supporting_partitions"


def test_common_denominator_bridge_rejects_a_plan_that_never_reveals_the_bridge():
    payload = _bridge_plan(
        primary_parts=2, second_parts=3, lcd_parts=6, operation="add",
    ).model_dump()
    # Drop `bridge_lcd` from every beat's targets so the compiler still sees the
    # visual declared but nothing reveals it. Every beat still needs at least
    # one target, so a beat that only named the bridge falls back to the
    # primary operand.
    for beat in payload["beats"]:
        pruned = [
            target for target in beat["targets"] if target["visual_ref"] != "bridge_lcd"
        ]
        beat["targets"] = pruned or [{"visual_ref": "first_operand"}]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _add_answer())

    assert exc_info.value.failure.code == "static_process_visual"
