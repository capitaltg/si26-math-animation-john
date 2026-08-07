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

    Five partitions: the two operands in their own denominators, each
    operand's refinement onto the LCD (`refined_a` and `refined_b`), and the
    LCD bridge that carries the result. The refined partitions are what let
    the animation teach the LCD reasoning -- without them the frame jumps
    from unlike-denominator operands to the bridge and skips the intermediate
    3/6 and 2/6 states a 1/2 + 1/3 lesson needs. `operation` is `"add"` or
    `"subtract"` so the answer_expression matches the lesson's own move.
    """
    refined_a_shaded = primary_shaded * lcd_parts // primary_parts
    refined_b_shaded = second_shaded * lcd_parts // second_parts
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": f"Combine two fractions using an LCD of {lcd_parts}.",
        "primary_visual": _partition("first_operand", parts=primary_parts, shaded=primary_shaded),
        "supporting_visuals": [
            _partition("second_operand", parts=second_parts, shaded=second_shaded),
            _partition("refined_a", parts=lcd_parts, shaded=refined_a_shaded),
            _partition("refined_b", parts=lcd_parts, shaded=refined_b_shaded),
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
                 {"visual_ref": "refined_a"},
                 {"visual_ref": "refined_b"},
                 {"visual_ref": "bridge_lcd"},
             ],
             "intent": "Show the second operand, both LCD refinements, and the bridge."},
            {"id": "combine_on_bridge", "kind": "derive",
             "targets": [
                 {"visual_ref": "first_operand"},
                 {"visual_ref": "second_operand"},
                 {"visual_ref": "refined_a"},
                 {"visual_ref": "refined_b"},
                 {"visual_ref": "bridge_lcd"},
             ],
             "intent": "Refine each operand onto the LCD, then combine on the bridge."},
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
    assert kinds == [
        "partition", "partition", "partition", "partition", "partition", "answer_expression",
    ]

    # The refined partitions carry each operand at the LCD (1/2 -> 3/6,
    # 1/3 -> 2/6). Assert them by shape so a plan that renames them still
    # has to declare the right intermediate denominators and shading.
    refined_specs = {
        visual.ref: visual for visual in program.visuals if visual.kind == "partition"
    }
    assert refined_specs["refined_a"].parts.value == 6
    assert refined_specs["refined_a"].shaded.value == 3
    assert refined_specs["refined_b"].parts.value == 6
    assert refined_specs["refined_b"].shaded.value == 2

    whole_revealed_refs = {
        target.visual_ref
        for entry in program.timeline
        if entry.action.kind == "reveal"
        for target in entry.action.targets
        if target.part is None and target.index is None
    }
    assert {
        "first_operand", "second_operand", "refined_a", "refined_b", "bridge_lcd",
    }.issubset(whole_revealed_refs), (
        "every partition must reveal as a whole so the animation shows the common denominator"
    )
    assert any(
        entry.action.kind == "show_answer_stage" and entry.action.stage == "work"
        for entry in program.timeline
    ), "the sum's arithmetic must show before the answer resolves"

    # The bridge beat focuses each operand's shaded wedges, the refined
    # intermediates (3/6 and 2/6), and the LCD partition's 5 shaded wedges,
    # so the frame reads as "each operand refined onto sixths, combined into
    # 5/6" rather than jumping straight to the sum.
    focused_parts = {
        (entry.action.target.visual_ref, entry.action.target.part, entry.action.target.index)
        for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    }
    for index in range(3):
        assert ("refined_a", "partition", index) in focused_parts, (
            f"the bridge beat must focus refined_a.partition[{index}] (1/2 refined to 3/6)"
        )
    for index in range(2):
        assert ("refined_b", "partition", index) in focused_parts, (
            f"the bridge beat must focus refined_b.partition[{index}] (1/3 refined to 2/6)"
        )
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
    assert kinds == [
        "partition", "partition", "partition", "partition", "partition", "answer_expression",
    ]

    revealed_refs = {
        target.visual_ref
        for entry in program.timeline
        if entry.action.kind == "reveal"
        for target in entry.action.targets
    }
    assert {
        "first_operand", "second_operand", "refined_a", "refined_b", "bridge_lcd",
    }.issubset(revealed_refs)

    # 3/4 refines to 3/4 and 1/2 refines to 2/4 on an LCD of 4, so the
    # bridge beat still shows the refinement even when one operand already
    # sits on the LCD.
    refined_specs = {
        visual.ref: visual for visual in program.visuals if visual.kind == "partition"
    }
    assert (refined_specs["refined_a"].parts.value, refined_specs["refined_a"].shaded.value) == (4, 3)
    assert (refined_specs["refined_b"].parts.value, refined_specs["refined_b"].shaded.value) == (4, 2)


def test_common_denominator_bridge_needs_four_supporting_partitions():
    payload = _bridge_plan(
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
    ).model_dump()
    # Drop the two refined partitions and the bridge; only the second operand
    # remains, so the strategy's five-partition shape cannot land.
    payload["supporting_visuals"] = payload["supporting_visuals"][:1]
    dropped_refs = {"refined_a", "refined_b", "bridge_lcd"}
    for beat in payload["beats"]:
        pruned = [
            target for target in beat["targets"]
            if target["visual_ref"] not in dropped_refs
        ]
        # Every beat needs at least one target; the conclude beat originally
        # named the bridge, so fall back to the primary operand when the bridge
        # is the only target the beat had.
        beat["targets"] = pruned or [{"visual_ref": "first_operand"}]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _add_answer())

    assert exc_info.value.failure.code == "common_denominator_bridge_requires_four_supporting_partitions"


def test_common_denominator_bridge_rejects_a_refined_partition_at_wrong_denominator():
    """A refined operand whose parts count is not the LCD cannot express the operand.

    The strategy teaches "refine each operand onto the common denominator";
    a refined partition whose denominator is anything else does not carry the
    operand on the LCD, so the intermediate state the animation is supposed
    to teach is missing.
    """
    payload = _bridge_plan(
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
    ).model_dump()
    payload["supporting_visuals"][1]["parts"] = {"node": "literal", "value": 4}
    payload["supporting_visuals"][1]["shaded"] = {"node": "literal", "value": 2}

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _add_answer())

    assert exc_info.value.failure.code == "common_denominator_bridge_requires_refined_lcd_parts"


def test_common_denominator_bridge_rejects_a_refined_partition_that_shades_a_different_amount():
    """A refined operand's shaded count must equal its operand at the LCD.

    1/2 at denominator 6 is 3 shaded wedges; a refined partition that shades
    4/6 instead animates a different amount than the operand it is claimed to
    refine, so the LCD reasoning contradicts the operand on-screen.
    """
    payload = _bridge_plan(
        primary_parts=2, primary_shaded=1,
        second_parts=3, second_shaded=1,
        lcd_parts=6, lcd_shaded=5,
        operation="add",
    ).model_dump()
    payload["supporting_visuals"][1]["shaded"] = {"node": "literal", "value": 4}

    with pytest.raises(V3ValidationError) as exc_info:
        _compile_and_gate(TeachingPlanDocument.model_validate(payload), _add_answer())

    assert exc_info.value.failure.code == "common_denominator_bridge_refined_must_equal_operand"


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


def test_common_denominator_bridge_bridge_beat_walks_operands_through_refinements_then_bridge():
    """The bridge beat walks each operand into its LCD refinement before the bridge.

    For each operand, the beat focuses the operand's own shaded wedges, then
    the LCD-refined partition's shaded wedges, then finally the bridge. That
    ordering is what makes the frame teach the refinement: the animation
    passes through the intermediate 3/6 and 2/6 states, rather than jumping
    from unlike-denominator operands straight to the sum.
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
    refined_a_focus = focus_sequence.index(("refined_a", "partition", 0))
    refined_b_focus = focus_sequence.index(("refined_b", "partition", 0))
    bridge_focus = focus_sequence.index(("bridge_lcd", "partition", 0))
    assert first_operand_focus < refined_a_focus < bridge_focus, (
        "operand_a must focus, then refine onto the LCD, before the bridge lands"
    )
    assert second_operand_focus < refined_b_focus < bridge_focus, (
        "operand_b must focus, then refine onto the LCD, before the bridge lands"
    )
