from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.scene_program import CalloutRelation, LabelProgramVisual
from app.meta.dsl.teaching_plan import (
    OrderedValuesVisual,
    TeachingBeat,
    TeachingPlanDocument,
)
from app.meta.dsl.v3_common import AnchorRef, CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.quality import validate_static_quality


@dataclass(frozen=True)
class Candidate:
    plan: TeachingPlanDocument
    program: object


def _field(name):
    return {"node": "field_ref", "field": name}


def _median_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [_field(f"v{index}") for index in range(1, 8)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "quality-median",
    })


def _perimeter_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": _field("length"), "width": _field("width"), "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace every edge of the boundary"},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "quality-perimeter",
    })


def _compile(plan, answer, fields):
    return compile_teaching_plan(
        plan, answer, frozenset(fields),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )


@pytest.fixture
def valid_program():
    plan = _median_plan()
    return Candidate(plan, _compile(plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)}))


def apply_literal_test_mutation(candidate, mutation):
    program = candidate.program
    if mutation == "split_group_reveal":
        timeline = [
            entry.model_copy(update={"action": entry.action.model_copy(update={"mode": "stagger"})})
            if entry.action.kind == "reveal" and entry.action.targets[0].visual_ref == "values" else entry
            for entry in program.timeline
        ]
        return Candidate(candidate.plan, program.model_copy(update={"timeline": timeline}))
    if mutation == "initial_answer_focus":
        visuals = [
            visual.model_copy(update={"initial_role": "focus"}) if visual.ref == "evaluated_answer" else visual
            for visual in program.visuals
        ]
        return Candidate(candidate.plan, program.model_copy(update={"visuals": visuals}))
    if mutation == "row_anchor_for_item":
        relation = program.relations[0]
        row_target = relation.target.model_copy(update={"part": None, "index": None, "anchor": "center"})
        relations = [relation.model_copy(update={"target": row_target}), *program.relations[1:]]
        return Candidate(candidate.plan, program.model_copy(update={"relations": relations}))
    if mutation == "remove_perimeter_trace":
        plan = _perimeter_plan()
        perimeter = _compile(
            plan,
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
            {"length", "width"},
        )
        return Candidate(plan, perimeter.model_copy(update={
            "timeline": [entry for entry in perimeter.timeline if entry.action.kind != "trace"],
        }))
    if mutation == "short_final_hold":
        timeline = [
            entry.model_copy(update={"duration_seconds": 0.5}) if entry.beat_id == "show_answer" else entry
            for entry in program.timeline
        ]
        return Candidate(candidate.plan, program.model_copy(update={"timeline": timeline}))
    if mutation == "insert_unexplained_wait":
        timeline = [
            entry.model_copy(update={"at_seconds": entry.at_seconds + 1.0}) if entry.at_seconds >= 2.9 else entry
            for entry in program.timeline
        ]
        return Candidate(candidate.plan, program.model_copy(update={
            "timeline": timeline, "total_duration_seconds": program.total_duration_seconds + 1.0,
        }))
    if mutation == "detach_dimension_label":
        # A dimension relation is identified by its typed target part
        # (`length_edge`/`width_edge` -- the same parts
        # `check_dimension_anchor_specificity` and the rendered-quality probe
        # both select on; see `app/meta/v3/quality.py`'s `DIMENSION_TARGET_PARTS`),
        # not by a ref-name convention no compiled program follows. Detaching
        # its index (while keeping the dimension-typed part) is the only way
        # to construct a "genuinely non-specific" dimension anchor, since the
        # compiler itself refuses to emit one -- this exercises the static
        # check's actual fail path, not a ref string it never sees in
        # production.
        plan = _perimeter_plan()
        perimeter = _compile(
            plan,
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
            {"length", "width"},
        )
        relation = CalloutRelation(
            ref="callout_1_0",
            target=AnchorRef(visual_ref="rectangle", part="length_edge", index=0, anchor="bottom"),
            text="length",
        )
        detached = relation.model_copy(update={
            "target": relation.target.model_copy(update={"index": None}),
        })
        return Candidate(plan, perimeter.model_copy(update={"relations": [detached]}))
    if mutation == "overlap_callout":
        duplicate = program.relations[0].model_copy(update={"ref": "second_callout"})
        return Candidate(candidate.plan, program.model_copy(update={"relations": [*program.relations, duplicate]}))
    if mutation == "extend_to_13_seconds":
        return Candidate(candidate.plan, program.model_copy(update={"total_duration_seconds": 13.0}))
    if mutation == "repeat_reveal":
        # Two beats naming the same visual compiled to two `reveal` actions on
        # it, so the rendered scene faded the same mobject in twice. Duplicate
        # the entry in place (same instant, same duration) so only the repeat
        # itself is under test, not a timing side effect.
        first_reveal = next(entry for entry in program.timeline if entry.action.kind == "reveal")
        return Candidate(candidate.plan, program.model_copy(update={
            "timeline": [*program.timeline, first_reveal.model_copy()],
        }))
    if mutation == "declare_unused_visual":
        # A visual no timeline action ever names is never added to the manim
        # scene, yet still claims layout width -- so it silently shrinks every
        # other visual to make room for nothing.
        unused = LabelProgramVisual(ref="unused_label", text="never animated")
        return Candidate(candidate.plan, program.model_copy(update={
            "visuals": [*program.visuals, unused],
        }))
    raise AssertionError(f"unknown mutation {mutation}")


@pytest.mark.parametrize("mutation,expected_code", [
    ("split_group_reveal", "serial_simple_reveal"),
    ("initial_answer_focus", "premature_answer_emphasis"),
    ("row_anchor_for_item", "collection_anchor_for_item"),
    ("remove_perimeter_trace", "static_process_visual"),
    ("short_final_hold", "conclusion_hold_too_short"),
    ("insert_unexplained_wait", "unexplained_idle_time"),
    ("detach_dimension_label", "dimension_anchor_mismatch"),
    ("overlap_callout", "callout_collision"),
    ("extend_to_13_seconds", "timeline_over_budget"),
    ("repeat_reveal", "repeated_reveal"),
    ("declare_unused_visual", "unused_visual"),
])
def test_quality_mutations_fail(valid_program, mutation, expected_code):
    broken = apply_literal_test_mutation(valid_program, mutation)

    report = validate_static_quality(broken.plan, broken.program)

    assert report.passed is False
    assert expected_code in [check.code for check in report.checks if not check.passed]


def _mid_scene_conclude_plan_data():
    """The median plan with a SECOND `conclude` beat inserted before the beat
    that derives the answer -- so the evaluated answer is revealed and given
    its `conclusion` role at 1.3s of a 6.5s scene, 20% in, before the `focus`
    beat that is supposed to derive it."""
    return {
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [_field(f"v{index}") for index in range(1, 8)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "blurt_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median before it has been derived"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "premature-answer",
    }


def test_a_non_final_conclude_beat_is_rejected_by_the_plan_schema():
    """Layer 1 of the premature-answer fix. `TeachingPlanDocument` used to
    require only that the LAST beat be `conclude`, so a mid-scene `conclude`
    was schema-legal -- and `beat_expander._standard_actions` reveals the
    evaluated answer in EVERY `conclude` beat. The Global Constraint is that
    the evaluated-answer visual is introduced only during `conclude` (singular,
    at the end), so a second `conclude` beat is not a pacing preference but a
    schema error."""
    with pytest.raises(ValidationError, match="only the final beat may be conclude"):
        TeachingPlanDocument.model_validate(_mid_scene_conclude_plan_data())


def _plan_with_only_the_beat_order_rule_bypassed(plan_data):
    """Construct a `TeachingPlanDocument` with the document-level
    beat-order validator (`require_focus_and_conclusion_order`) -- and ONLY
    that validator -- skipped.

    Every nested model is still fully validated through `model_validate`, and
    the program under test is still produced by the REAL
    `compile_teaching_plan`. The bypass exists because the two halves of the
    premature-answer fix are deliberately layered: the schema rejects a
    non-final `conclude` beat outright (proved directly above), and
    `check_answer_timing` independently refuses to call such a reveal legal.
    Testing the second layer requires an input the first layer no longer
    admits; `model_construct` is the narrowest possible way to get one, and it
    is used here to prove a *gate*, not to hand-build a program shape (which
    is the pattern this suite is otherwise moving away from -- see the
    compiler-built tests below).
    """
    return TeachingPlanDocument.model_construct(
        plan_version=3,
        learning_objective=plan_data["learning_objective"],
        primary_visual=OrderedValuesVisual.model_validate(plan_data["primary_visual"]),
        supporting_visuals=[],
        strategy=plan_data["strategy"],
        beats=[TeachingBeat.model_validate(beat) for beat in plan_data["beats"]],
        variation_seed=plan_data["variation_seed"],
    )


def test_answer_revealed_in_a_non_final_conclude_beat_fails_premature_answer_emphasis():
    """Layer 2 of the premature-answer fix, and the finding itself:
    `check_answer_timing` built its set of legal conclusion beats from EVERY
    `conclude` beat in the plan, so the premature reveal's own `beat_id` was a
    member of that set and the check named `premature_answer_emphasis` passed
    on premature answer emphasis. Before the fix this exact program returned
    `passed=True` with zero failing checks.

    The failing input is a real compiled `SceneProgramDocument` from
    `compile_teaching_plan`, not a `model_copy`-mutated one, so the assertion
    below is about what the gate does to compiler output.
    """
    plan = _plan_with_only_the_beat_order_rule_bypassed(_mid_scene_conclude_plan_data())
    program = _compile(
        plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)},
    )

    # Confirm the compiler really did emit the premature reveal -- the whole
    # point is that this is reachable output, not a hypothetical shape.
    answer_reveals = [
        (entry.beat_id, entry.at_seconds) for entry in program.timeline
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    ]
    assert answer_reveals[0][0] == "blurt_answer" != plan.beats[-1].id
    first_focus = min(
        entry.at_seconds for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    )
    assert answer_reveals[0][1] < first_focus

    report = validate_static_quality(plan, program)

    assert report.passed is False
    assert "premature_answer_emphasis" in [
        check.code for check in report.checks if not check.passed
    ]


def test_callout_on_whole_rectangle_with_no_part_fails_dimension_anchor_specificity():
    """Controller ruling: a callout relation targeting a rectangle_measurement
    visual must name a specific part. This compiles a callout with NO `part`
    at all through the REAL compiler (not a hand-mutated relation) --
    `compiler.py`'s `_validate_target` returns immediately when
    `target.part is None`, and `_validate_callout_anchor` only restricts
    `ordered_values` items, never `rectangle_measurement` -- so this is the
    actual shape the compiler accepts today. Before this fix, such a callout
    was never even considered a dimension relation (selection required
    `target.part in DIMENSION_TARGET_PARTS`, which `None` never satisfies),
    so a label mislabeled onto the whole rectangle passed every gate."""
    plan_data = _perimeter_plan().model_dump()
    plan_data["beats"][1]["custom_actions"] = [
        {"kind": "callout", "text": "the rectangle", "target": {
            "visual_ref": "rectangle", "anchor": "center",
        }},
    ]
    plan = TeachingPlanDocument.model_validate(plan_data)
    program = _compile(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        {"length", "width"},
    )
    # Confirm the compiler really did accept the whole-rectangle callout with
    # no part -- this is not a hypothetical, it is what compile_teaching_plan
    # produces for this plan today.
    relation = next(r for r in program.relations if r.target.visual_ref == "rectangle")
    assert relation.target.part is None

    report = validate_static_quality(plan, program)

    assert report.passed is False
    assert "dimension_anchor_mismatch" in [check.code for check in report.checks if not check.passed]


def _median_plan_naming_two_different_items():
    """A `pair_elimination` plan whose derive beat names `values.item[0]` and
    whose focus/conclude beats name `values.item[3]` -- naming two items is the
    natural way to teach pairing, and the compiler accepts it."""
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [_field(f"v{index}") for index in range(1, 8)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "eliminate_smallest", "kind": "derive",
             "targets": [{"visual_ref": "values", "part": "item", "index": 0}],
             "intent": "pair the smallest value off against the largest"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "two-item-targets",
    })


def test_a_plan_naming_two_different_items_passes_semantic_anchor_specificity():
    """`check_semantic_anchor_specificity` required each relation to match
    EVERY item target in the plan rather than to be item-level at all. As soon
    as two beats named different items on one visual, any relation on that
    visual mismatched at least one of them and the check failed -- on a plan
    whose only relation (`median_callout` on `values.item[3]`) is item-specific,
    making the reported detail untrue as well. That blocked legitimate
    pair_elimination candidates and misdirected the repair loop.
    """
    plan = _median_plan_naming_two_different_items()
    program = _compile(
        plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)},
    )
    # Two distinct item targets on one visual, and a relation that really is
    # item-specific -- the exact combination that used to fail.
    item_targets = {
        (target.visual_ref, target.part, target.index)
        for beat in plan.beats for target in beat.targets
        if target.part is not None
    }
    assert len({index for _, _, index in item_targets}) == 2
    assert all(
        relation.target.part is not None and relation.target.index is not None
        for relation in program.relations
    )

    report = validate_static_quality(plan, program)

    assert report.passed is True
    assert [check.code for check in report.checks if not check.passed] == []


def test_a_whole_collection_callout_still_fails_semantic_anchor_specificity():
    """The counterweight to the test above: fixing the false positive must not
    turn the check into a dead filter. A callout targeting `values` with no
    `part` compiles cleanly (`compiler._validate_target` returns immediately
    when `part is None`, and `_validate_callout_anchor` only constrains the
    anchor of item-level targets), so this genuinely non-specific anchor is
    reachable compiler output -- and the plan instructs on `values.item[3]`,
    so a whole-collection arrow cannot point at what is being taught.
    """
    plan_data = _median_plan_naming_two_different_items().model_dump()
    plan_data["beats"][0]["custom_actions"] = [
        {"kind": "callout", "text": "seven values in order", "target": {
            "visual_ref": "values", "anchor": "top",
        }},
    ]
    plan = TeachingPlanDocument.model_validate(plan_data)
    program = _compile(
        plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)},
    )
    non_specific = [
        index for index, relation in enumerate(program.relations)
        if relation.target.part is None
    ]
    assert non_specific, "the compiler must really emit a whole-collection callout"

    report = validate_static_quality(plan, program)

    assert report.passed is False
    failed = [check for check in report.checks if not check.passed]
    assert [check.code for check in failed] == ["collection_anchor_for_item"]
    assert failed[0].path == f"relations[{non_specific[0]}].target"


def _perimeter_plan_with_dimension_callouts():
    # A real teaching plan whose derive beat requests "callout" custom
    # actions on the declared "length_edge"/"width_edge" semantic parts (see
    # rectangle_measurement.py) -- the actual typed target a compiled
    # program emits for a length/width label, and the same construction
    # `test_dynamic_render_worker.py` uses to exercise this end to end at
    # the render layer.
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": _field("length"), "width": _field("width"), "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace every edge of the boundary",
             "custom_actions": [
                 {"kind": "callout", "text": "length", "target": {
                     "visual_ref": "rectangle", "part": "length_edge", "index": 0, "anchor": "bottom",
                 }},
                 {"kind": "callout", "text": "width", "target": {
                     "visual_ref": "rectangle", "part": "width_edge", "index": 0, "anchor": "left",
                 }},
             ]},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "quality-perimeter-dimensions",
    })


def test_real_perimeter_program_with_dimension_callouts_passes_static_quality():
    """Proves `check_dimension_anchor_specificity` actually runs and ACCEPTS
    the `length_edge`/`width_edge` alias parts as valid dimension anchors --
    the exact typed target the real compiler emits for a length/width
    callout. Before this fix, the check filtered on `"dimension" in
    relation.ref` (never true) and, had it ever run, would have REJECTED
    these same relations for not being anchored to a plain "edge" part --
    i.e. the static gate and the compiler disagreed about what a valid
    dimension anchor looks like."""
    plan = _perimeter_plan_with_dimension_callouts()
    program = _compile(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        {"length", "width"},
    )
    dimension_refs = {
        relation.ref for relation in program.relations
        if relation.target.part in {"length_edge", "width_edge"}
    }
    assert dimension_refs, "the plan's callouts must compile to real dimension relations"

    report = validate_static_quality(plan, program)

    assert report.passed is True
    assert all(check.passed for check in report.checks if check.code == "dimension_anchor_mismatch")


def test_valid_compiled_candidate_passes_and_exposes_reviewer_safe_payload(valid_program):
    report = validate_static_quality(valid_program.plan, valid_program.program)

    assert report.passed is True
    assert report.model_payload() == {
        "passed": True,
        "checks": [
            {"code": check.code, "passed": True, "path": check.path, "detail": check.detail}
            for check in report.checks
        ],
    }


def test_report_raises_first_structured_failure_without_candidate_contents(valid_program):
    report = validate_static_quality(
        valid_program.plan,
        apply_literal_test_mutation(valid_program, "split_group_reveal").program,
    )

    with pytest.raises(V3ValidationError, match="serial_simple_reveal") as exc_info:
        report.require_passed()

    assert exc_info.value.failure.hint == "revise the teaching plan and regenerate the candidate"
    assert "v4" not in str(exc_info.value)
