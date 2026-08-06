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


def _partition(ref, parts, shaded=0, whole=1):
    return {
        "kind": "partition", "ref": ref,
        "whole": {"node": "literal", "value": whole},
        "parts": {"node": "literal", "value": parts},
        "shaded": {"node": "literal", "value": shaded},
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
        "primary_visual": _partition("thirds", parts=3, shaded=2),
        "supporting_visuals": [_partition("sixths", parts=6, shaded=4)],
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


def _bridge_plan(
    *, primary_parts, primary_shaded, second_parts, second_shaded,
    lcd_parts, lcd_shaded, operation,
):
    """A four-beat plan for a like-whole fraction sum or difference.

    Three partitions: the two operands and the LCD bridge that refines both.
    `operation` is `"add"` or `"subtract"` so the answer_expression matches the
    lesson's own move.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": f"Combine two fractions using an LCD of {lcd_parts}.",
        "primary_visual": _partition("first_operand", parts=primary_parts, shaded=primary_shaded),
        "supporting_visuals": [
            _partition("second_operand", parts=second_parts, shaded=second_shaded),
            _partition("bridge_lcd", parts=lcd_parts, shaded=lcd_shaded),
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
        if target.part is None and target.index is None
    }
    assert {"thirds", "sixths"}.issubset(revealed_refs), (
        "each partition must reveal as a whole so its circle and every wedge land before the alignment"
    )

    # The align beat focuses every shaded wedge of BOTH partitions -- 2 in
    # `thirds` and 4 in `sixths` -- so the equivalence lands as matching
    # highlighted wedges rather than as a decorative whole-visual recolour.
    focused_parts = {
        (entry.action.target.visual_ref, entry.action.target.part, entry.action.target.index)
        for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    }
    for index in range(2):
        assert ("thirds", "partition", index) in focused_parts, (
            f"the align beat must focus thirds.partition[{index}] (numerator wedge)"
        )
    for index in range(4):
        assert ("sixths", "partition", index) in focused_parts, (
            f"the align beat must focus sixths.partition[{index}] (equivalent-numerator wedge)"
        )


def test_equivalence_align_rejects_mismatched_fractions():
    payload = _equivalence_plan().model_dump()
    # 2/3 alongside 3/6 -- both reduce to 1/2 vs 2/3, so the equivalence
    # never holds and the strategy is decorative.
    payload["supporting_visuals"][0]["shaded"] = {"node": "literal", "value": 3}

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    assert exc_info.value.failure.code == "equivalence_align_requires_equal_fractions"


def test_equivalence_align_rejects_different_wholes():
    payload = _equivalence_plan().model_dump()
    payload["supporting_visuals"][0]["whole"] = {"node": "literal", "value": 2}

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    assert exc_info.value.failure.code == "equivalence_align_requires_same_whole"


def test_equivalence_align_rejects_partial_supporting_reveal():
    """Revealing only `sixths.partition[0]` never brings the circle on screen.

    `check_strategy_affordance` used to accept any reveal naming the supporting
    ref; the alignment then landed on a single wedge with no partition around
    it. The gate now requires a whole-visual reveal (`part is None and
    index is None`), matching `beat_expander._is_revealed`.
    """
    payload = _equivalence_plan().model_dump()
    # Every whole `sixths` target becomes a single-wedge target so the
    # supporting partition's circle never enters the scene. The align beat
    # keeps naming `thirds` (whole) so beat_expander does not synthesise a
    # whole `sixths` reveal via `_reveal_unrevealed`.
    for beat in payload["beats"]:
        beat["targets"] = [
            {"visual_ref": "sixths", "part": "partition", "index": 0}
            if target["visual_ref"] == "sixths"
            and target.get("part") is None
            else target
            for target in beat["targets"]
        ]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    assert exc_info.value.failure.code == "static_process_visual"


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
    """A plan whose beats never target both partitions cannot animate the alignment.

    `_require_owned_equivalence_align_beat` refuses the shape at compile time
    so a plan that could not emit the shaded-wedge walk fails before the
    quality gate ever runs.
    """
    payload = _equivalence_plan().model_dump()
    payload["beats"] = [
        beat for beat in payload["beats"] if beat["id"] != "reveal_sixths"
    ]
    for beat in payload["beats"]:
        beat["targets"] = [
            target for target in beat["targets"] if target["visual_ref"] != "sixths"
        ]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _equivalence_answer())

    assert exc_info.value.failure.code == "equivalence_align_requires_alignment_beat"


def test_common_denominator_bridge_compiles_one_half_plus_one_third():
    plan = _bridge_plan(
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
    )

    program = _compile_and_gate(plan, _add_answer())

    kinds = [visual.kind for visual in program.visuals]
    assert kinds == ["partition", "partition", "partition", "answer_expression"]

    whole_revealed_refs = {
        target.visual_ref
        for entry in program.timeline
        if entry.action.kind == "reveal"
        for target in entry.action.targets
        if target.part is None and target.index is None
    }
    assert {"first_operand", "second_operand", "bridge_lcd"}.issubset(whole_revealed_refs), (
        "every partition must reveal as a whole so the animation shows the common denominator"
    )
    assert any(
        entry.action.kind == "show_answer_stage" and entry.action.stage == "work"
        for entry in program.timeline
    ), "the sum's arithmetic must show before the answer resolves"

    # The bridge beat focuses the LCD partition's 5 shaded wedges (the
    # refined result of 1/2 + 1/3 = 5/6) so the frame reads as "these five
    # sixths hold the sum" rather than as a whole-visual recolour.
    focused_parts = {
        (entry.action.target.visual_ref, entry.action.target.part, entry.action.target.index)
        for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    }
    for index in range(5):
        assert ("bridge_lcd", "partition", index) in focused_parts, (
            f"the bridge beat must focus bridge_lcd.partition[{index}]"
        )


def test_common_denominator_bridge_compiles_three_quarters_minus_one_half():
    plan = _bridge_plan(
        primary_parts=4, primary_shaded=3,
        second_parts=2, second_shaded=1,
        lcd_parts=4, lcd_shaded=1,
        operation="subtract",
    )

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
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
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


def test_common_denominator_bridge_rejects_a_non_lcd_bridge():
    """1/2 + 1/3 refined onto 5 sixths cannot use a 4-part bridge.

    The strategy teaches "refine both operands onto their common
    denominator"; a bridge whose parts count is not the LCD carries a
    denominator that cannot express both operands as whole numerator counts.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(
            _bridge_plan(
                primary_parts=2, primary_shaded=1,
                second_parts=3, second_shaded=1,
                lcd_parts=4, lcd_shaded=2,
                operation="add",
            ),
            _add_answer(),
        )

    assert exc_info.value.failure.code == "common_denominator_bridge_requires_lcd"


def test_common_denominator_bridge_rejects_result_that_is_neither_sum_nor_difference():
    """A bridge whose shaded/parts is neither operand_a + operand_b nor |a - b|.

    1/2 + 1/3 combined on 6 gives 5/6; a bridge that shades only 2/6 would
    animate an arbitrary intermediate rather than the arithmetic the strategy
    teaches.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(
            _bridge_plan(
                primary_parts=2, primary_shaded=1,
                second_parts=3, second_shaded=1,
                lcd_parts=6, lcd_shaded=2,
                operation="add",
            ),
            _add_answer(),
        )

    assert exc_info.value.failure.code == "common_denominator_bridge_result_mismatch"


def test_common_denominator_bridge_rejects_a_plan_that_never_reveals_the_bridge():
    """A plan whose beats never target the bridge partition cannot stage the walk.

    `_require_owned_common_denominator_bridge_beat` refuses the shape at
    compile time so a plan that could not emit the refined-onto-LCD walk fails
    before the quality gate ever runs.
    """
    payload = _bridge_plan(
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
    ).model_dump()
    for beat in payload["beats"]:
        pruned = [
            target for target in beat["targets"] if target["visual_ref"] != "bridge_lcd"
        ]
        beat["targets"] = pruned or [{"visual_ref": "first_operand"}]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _add_answer())

    assert exc_info.value.failure.code == "common_denominator_bridge_requires_bridge_beat"


def test_common_denominator_bridge_rejects_addition_answer_with_difference_bridge():
    """An add answer paired with a difference bridge contradicts the arithmetic.

    Refused at compile time so the animation cannot show `1/2 + 1/3` while the
    bridge shades the difference (which visually reads as subtraction).
    """
    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(
            _bridge_plan(
                primary_parts=2, primary_shaded=1,
                second_parts=3, second_shaded=1,
                lcd_parts=6, lcd_shaded=1,
                operation="add",
            ),
            _add_answer(),
        )

    assert exc_info.value.failure.code == "common_denominator_bridge_result_mismatch"


def test_common_denominator_bridge_rejects_subtract_answer_operand_swap():
    """Subtracting `1/2 - 3/4` cannot compile onto a 3/4 primary + 1/2 second.

    The compiler pins operand order to the primary/second partitions, so the
    answer's operands must be primary first, second second.
    """
    payload = _bridge_plan(
        primary_parts=4, primary_shaded=3,
        second_parts=2, second_shaded=1,
        lcd_parts=4, lcd_shaded=1,
        operation="subtract",
    )
    swapped = SubtractNode(operands=[
        FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=2)]),
        FractionNode(operands=[LiteralNode(value=3), LiteralNode(value=4)]),
    ])

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(payload, swapped)

    assert exc_info.value.failure.code == "common_denominator_bridge_operands_must_match_partitions"


def test_common_denominator_bridge_bridge_beat_walks_operands_then_bridge():
    """The bridge beat first focuses each operand's shaded wedges (their
    refined-onto-LCD state), then the bridge's shaded wedges, so the frame
    reads as "each operand refined onto the common denominator, combined".
    """
    plan = _bridge_plan(
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
    )

    program = _compile_and_gate(plan, _add_answer())

    focus_sequence = [
        (entry.action.target.visual_ref, entry.action.target.part, entry.action.target.index)
        for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
        and entry.action.target.part == "partition"
    ]
    first_operand_focus = focus_sequence.index(("first_operand", "partition", 0))
    second_operand_focus = focus_sequence.index(("second_operand", "partition", 0))
    bridge_focus = focus_sequence.index(("bridge_lcd", "partition", 0))
    assert first_operand_focus < bridge_focus, (
        "operand_a's refined state must land before the bridge's combined result"
    )
    assert second_operand_focus < bridge_focus, (
        "operand_b's refined state must land before the bridge's combined result"
    )
