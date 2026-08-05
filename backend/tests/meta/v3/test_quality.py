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
from app.meta.v3.quality import QualityCheck, QualityReport, validate_static_quality


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


def _perimeter_candidate():
    plan = _perimeter_plan()
    return Candidate(
        plan,
        _compile(
            plan,
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
            {"length", "width"},
        ),
    )


def apply_literal_test_mutation(candidate, mutation):
    program = candidate.program
    if mutation == "split_group_reveal":
        timeline = [
            entry.model_copy(update={"action": entry.action.model_copy(update={"mode": "stagger"})})
            if entry.action.kind == "reveal" and entry.action.targets[0].visual_ref == "values" else entry
            for entry in program.timeline
        ]
        return Candidate(candidate.plan, program.model_copy(update={"timeline": timeline}))
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


# Removed mutations that bypassed pydantic to fabricate unconstructible inputs:
# `initial_answer_focus` (AnswerProgramVisual.initial_role is Literal["neutral"];
# quality.py's initial_role != "neutral" branch is a defensive assertion for a
# pure invariant, not a live gate) and `extend_to_13_seconds`
# (SceneProgramDocument.total_duration_seconds has le=MAX_SCENE_SECONDS=12; the
# `timeline_over_budget` branch is likewise a pure invariant).
@pytest.mark.parametrize("mutation,expected_code", [
    ("split_group_reveal", "serial_simple_reveal"),
    ("row_anchor_for_item", "collection_anchor_for_item"),
    ("remove_perimeter_trace", "static_process_visual"),
    ("short_final_hold", "conclusion_hold_too_short"),
    ("insert_unexplained_wait", "unexplained_idle_time"),
    ("detach_dimension_label", "dimension_anchor_mismatch"),
    ("overlap_callout", "callout_collision"),
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
    beat that is supposed to derive it.

    `group_reveal` rather than `pair_elimination`: what is under test is when
    the `evaluated_answer` card may be revealed, and a `pair_elimination` plan
    declares no such card -- its answer is one of the collection's own values.
    The strategy is otherwise immaterial here; this plan has no `organize` beat,
    so it compiles to the same 6.5s timeline either way."""
    return {
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [_field(f"v{index}") for index in range(1, 8)],
        },
        "strategy": "group_reveal",
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

    The unresolved answer is now always revealed in the first beat, so a
    premature `conclude` no longer manifests as an early reveal -- every
    `conclude` beat resolves the value instead, so it is the `value` stage
    that lands early here.

    The failing input is a real compiled `SceneProgramDocument` from
    `compile_teaching_plan`, not a `model_copy`-mutated one, so the assertion
    below is about what the gate does to compiler output.
    """
    plan = _plan_with_only_the_beat_order_rule_bypassed(_mid_scene_conclude_plan_data())
    program = _compile(
        plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)},
    )

    # Confirm the compiler really did emit the premature value resolution --
    # the whole point is that this is reachable output, not a hypothetical shape.
    value_stages = [
        (entry.beat_id, entry.at_seconds) for entry in program.timeline
        if entry.action.kind == "show_answer_stage" and entry.action.stage == "value"
    ]
    assert value_stages[0][0] == "blurt_answer" != plan.beats[-1].id
    first_focus = min(
        entry.at_seconds for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    )
    assert value_stages[0][1] < first_focus

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
            {"id": "eliminate_smallest", "kind": "organize",
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


def test_a_callout_on_a_dimension_edge_is_rejected_as_a_duplicate_label():
    """`measure_rectangle` now labels the length and width itself, so a callout
    on `length_edge`/`width_edge` writes a second label over the first.

    Those callouts used to be the only route to a visible dimension, and this
    test asserted they PASSED. They cannot express a per-render value, though:
    `CalloutRelation.text` is a plain string frozen at generation time, so a
    template reused on another problem would keep labelling the first problem's
    numbers. The dimensions are now measured and drawn from the `length`/`width`
    expressions, and a callout on those same edges is a duplicate.

    Callouts remain available for every other anchor -- a plain numbered `edge`,
    a `vertex` -- which is what `check_dimension_anchor_specificity` still guards.
    """
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

    assert report.passed is False
    assert "duplicate_dimension_label" in [
        check.code for check in report.checks if not check.passed
    ]


def test_a_callout_on_a_plain_vertex_is_still_accepted():
    """The duplicate-label gate must not turn into a blanket ban on callouts."""
    raw = _perimeter_plan_with_dimension_callouts().model_dump()
    raw["beats"][1]["custom_actions"] = [{
        "kind": "callout", "text": "start here",
        "target": {"visual_ref": "rectangle", "part": "vertex", "index": 0, "anchor": "top"},
    }]
    plan = TeachingPlanDocument.model_validate(raw)
    program = _compile(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        {"length", "width"},
    )

    report = validate_static_quality(plan, program)

    assert report.passed is True


def test_a_multi_action_conclusion_without_an_answer_card_still_clears_the_hold_floor():
    """`check_conclusion_hold`'s fallback must be satisfiable by real output.

    The fallback holds EVERY action of the final beat to
    `MIN_CONCLUSION_HOLD_SECONDS`, and a `pair_elimination` lesson declares no
    `evaluated_answer` -- which used to be the only thing making
    `timeline.schedule_beats` co-start a conclusion. Without that, this plan's
    conclude beat (revealing a supporting label, then showing the median callout)
    was split into two sequential 0.9868s slots and the gate rejected reachable
    compiler output. The two halves of the fix have to agree on which beat the
    conclusion is, so this asserts the gate against the compiler, not a mutation.
    """
    raw = _median_plan().model_dump()
    raw["supporting_visuals"] = [
        {"kind": "label", "ref": "answer_label", "text": "the middle value is the median"},
    ]
    raw["beats"][3]["targets"] = [
        {"visual_ref": "values", "part": "item", "index": 3},
        {"visual_ref": "answer_label"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    program = _compile(plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)})
    conclusion = [entry for entry in program.timeline if entry.beat_id == "show_answer"]
    assert len(conclusion) == 2, "this plan must compile to a multi-action conclusion"
    assert not [visual for visual in program.visuals if visual.ref == "evaluated_answer"]

    report = validate_static_quality(plan, program)

    assert report.passed is True
    assert [check.code for check in report.checks if not check.passed] == []


def test_a_plan_hijacking_the_evaluated_answer_ref_is_rejected():
    """The `evaluated_answer` ref is reserved for the compiler-supplied
    `answer_expression` visual. A plan can still name a supporting visual
    `evaluated_answer` -- nothing in the plan schema stops that -- and
    `BeatExpander.expand` appends its own answer AFTER the plan's supporting
    visuals (`beat_expander.py:73-82`), so the plan-declared shape reaches the
    `next()` in `check_answer_timing` first. That ordering is what makes the
    kind gate load-bearing; without it, `check_answer_work_shown` would then
    reach `answer.expression` and raise `AttributeError`.

    Compiled through a non-`pair_elimination` plan (which suppresses the
    system answer on strategy alone, hiding the ordering dependency) so both
    visuals actually coexist in the program and the plan-declared one is
    selected.
    """
    raw = _perimeter_plan().model_dump()
    raw["supporting_visuals"] = [
        {
            "kind": "ordered_values", "ref": "evaluated_answer",
            "values": [_field("length"), _field("width"), _field("length")],
        },
    ]
    raw["beats"][0]["targets"] = [
        {"visual_ref": "rectangle"},
        {"visual_ref": "evaluated_answer"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    program = _compile(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        {"length", "width"},
    )
    matches = [visual for visual in program.visuals if visual.ref == "evaluated_answer"]
    assert len(matches) == 2, "plan-declared and system-supplied answer visuals should coexist"
    assert matches[0].kind == "ordered_values", "plan-declared visual must be selected first by next()"
    assert matches[1].kind == "answer_expression"

    report = validate_static_quality(plan, program)

    assert not report.passed
    assert any(
        check.code == "premature_answer_emphasis"
        and not check.passed
        and check.path == "visuals.evaluated_answer.kind"
        for check in report.checks
    )


def test_valid_compiled_candidate_passes_and_exposes_reviewer_safe_payload(valid_program):
    report = validate_static_quality(valid_program.plan, valid_program.program)

    assert report.passed is True
    payload = report.model_payload()
    # Payload is a reviewer-safe surface: only the four documented keys, and
    # nothing from the candidate itself (plans/programs/values).
    assert set(payload.keys()) == {"passed", "checks"}
    assert payload["passed"] is True
    for entry in payload["checks"]:
        assert set(entry.keys()) == {"code", "passed", "path", "detail"}
        assert isinstance(entry["code"], str) and entry["code"]
        assert entry["passed"] is True
        assert isinstance(entry["path"], str)
        assert isinstance(entry["detail"], str)
    serialized = str(payload)
    # No fixture values (`v1`..`v7`) or plan/program object addresses should
    # reach the reviewer surface.
    for field in (f"v{i}" for i in range(1, 8)):
        assert field not in serialized


def test_report_raises_first_structured_failure_without_candidate_contents(valid_program):
    report = validate_static_quality(
        valid_program.plan,
        apply_literal_test_mutation(valid_program, "split_group_reveal").program,
    )

    with pytest.raises(V3ValidationError, match="serial_simple_reveal") as exc_info:
        report.require_passed()

    failed = next(check for check in report.checks if not check.passed)
    assert failed.detail in exc_info.value.failure.hint
    # `V3ValidationError.__str__` composes only compile-time strings
    # (`code`, `path`, `observed=detail`), so pin the exact shape rather than
    # asserting a candidate value like `"v4"` cannot leak into it.
    assert str(exc_info.value) == f"{failed.code} at {failed.path}: {failed.detail}"


@pytest.mark.parametrize(
    ("code", "path", "detail"),
    [
        # Representative static-layer failure (app/meta/v3/quality.py).
        ("serial_simple_reveal", "timeline[0].action.mode", "ordered values must reveal together"),
        # Representative rendered-layer failure (app/meta/v3/render_probe.py) --
        # reused because `QualityReport.require_passed` serves both layers.
        ("callout_collision", "relations.rel_a.bounds", "callout overlaps an unrelated visual"),
    ],
)
def test_the_quality_hint_carries_the_check_and_its_diagnosis(code, path, detail):
    """Every `_failed(...)` site knows what is wrong; the retry loop only sees
    `code`, `path`, and `hint` (see `_STABLE_REPAIR_FEEDBACK_FIELDS` in
    `app/meta/draft_generation.py`). Before this test, `require_passed` stamped
    the same generic hint on every failure and the per-check diagnosis (held in
    `detail`, forwarded through `observed`) never reached the model -- so the
    retry proposed the same repair unchanged. The forwarded `hint` must name
    the check and carry something the model can act on for each failure.
    """
    report = QualityReport(
        passed=False,
        checks=[QualityCheck(code=code, passed=False, path=path, detail=detail)],
    )

    with pytest.raises(V3ValidationError) as exc_info:
        report.require_passed()

    failure = exc_info.value.failure
    assert failure.code == code
    assert failure.path == path
    assert detail in failure.hint
    assert failure.hint != "revise the teaching plan and regenerate the candidate"


def _plan_with_a_redundant_reveal_beat():
    """A `reveal` beat whose target is already revealed AND already in focus.

    The expander reveals only what is not yet on screen, and falls back to moving
    attention when a beat's kind has nothing left to do -- so a beat is only
    genuinely empty once even that fallback is a no-op, which needs the target to
    already hold `focus`. That is the case this gate exists for.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": _field("length"), "width": _field("width"), "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "focus_boundary", "kind": "focus", "targets": [{"visual_ref": "rectangle"}],
             "intent": "attend to the whole boundary"},
            {"id": "second_look", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "look again at the same rectangle"},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "quality-redundant-reveal",
    })


def test_a_beat_that_produces_no_action_is_named_rather_than_reported_as_idle_time():
    """The failure must name the beat at fault, not the gap it leaves behind.

    An empty beat contributes no timeline entry, so the only symptom was
    `unexplained_idle_time` at the index of the NEXT action -- naming neither the
    beat nor the reason, which left the repair loop nothing to act on and burned
    all three generation attempts.
    """
    plan = _plan_with_a_redundant_reveal_beat()
    program = _compile(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        {"length", "width"},
    )
    assert "second_look" not in {entry.beat_id for entry in program.timeline}, (
        "this plan must contain a beat that compiles to no actions"
    )

    report = validate_static_quality(plan, program)

    assert report.passed is False
    failed = [check for check in report.checks if not check.passed]
    assert failed[0].code == "beat_without_action", (
        "the named cause must be reported before the idle-interval symptom"
    )
    assert "second_look" in failed[0].detail


def test_the_first_beat_placeholder_reveal_does_not_trip_the_conclusion_hold():
    """`check_conclusion_hold` used to take the minimum duration across EVERY
    entry naming `evaluated_answer`. The first-beat reveal is far shorter than
    the 1.5s floor, so the check failed on a correct lesson."""
    candidate = _perimeter_candidate()

    report = validate_static_quality(candidate.plan, candidate.program)

    hold = next(check for check in report.checks if check.code == "conclusion_hold_too_short")
    assert hold.passed, hold.detail


def test_an_answer_revealed_late_is_rejected():
    candidate = _perimeter_candidate()
    reveal_index = next(
        index for index, entry in enumerate(candidate.program.timeline)
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    )
    moved = candidate.program.timeline[reveal_index].model_copy(
        update={"beat_id": candidate.plan.beats[-1].id},
    )
    timeline = list(candidate.program.timeline)
    timeline[reveal_index] = moved
    program = candidate.program.model_copy(update={"timeline": timeline})

    report = validate_static_quality(candidate.plan, program)

    assert not report.passed
    assert any(check.code == "answer_placeholder_missing" for check in report.checks)


def test_the_resolved_value_may_not_appear_before_conclude():
    candidate = _perimeter_candidate()
    value_index = next(
        index for index, entry in enumerate(candidate.program.timeline)
        if entry.action.kind == "show_answer_stage" and entry.action.stage == "value"
    )
    moved = candidate.program.timeline[value_index].model_copy(
        update={"beat_id": candidate.plan.beats[0].id},
    )
    timeline = list(candidate.program.timeline)
    timeline[value_index] = moved
    program = candidate.program.model_copy(update={"timeline": timeline})

    report = validate_static_quality(candidate.plan, program)

    assert not report.passed
    assert any(
        check.code == "premature_answer_emphasis" and not check.passed
        for check in report.checks
    )


def test_a_staged_perimeter_candidate_passes_every_gate():
    candidate = _perimeter_candidate()

    report = validate_static_quality(candidate.plan, candidate.program)

    assert report.passed, [check for check in report.checks if not check.passed]


def test_a_label_using_a_question_mark_as_the_answer_is_rejected():
    """The kilometers draft authored `? meters` while the compiler appended its
    own answer, so the lesson showed two answers, one of them dead."""
    from app.meta.v3.quality import check_answer_stand_in

    program = _perimeter_candidate().program
    program = program.model_copy(update={
        "visuals": [*program.visuals, LabelProgramVisual(ref="answer_label", text="? meters")],
    })

    check = check_answer_stand_in(program)

    assert not check.passed
    assert check.code == "answer_stand_in_label"


def test_a_question_prompt_label_is_left_alone():
    """A stand-in uses "?" as a value, so the mark sits mid-string; a question
    ends with it."""
    from app.meta.v3.quality import check_answer_stand_in

    program = _perimeter_candidate().program
    program = program.model_copy(update={
        "visuals": [
            *program.visuals,
            LabelProgramVisual(ref="prompt", text="What is the perimeter?"),
        ],
    })

    assert check_answer_stand_in(program).passed


def test_an_answer_with_arithmetic_must_show_its_work():
    from app.meta.v3.quality import check_answer_work_shown

    program = _perimeter_candidate().program
    timeline = [
        entry for entry in program.timeline
        if not (entry.action.kind == "show_answer_stage" and entry.action.stage == "work")
    ]
    stripped = program.model_copy(update={"timeline": timeline})

    check = check_answer_work_shown(stripped)

    assert not check.passed
    assert check.code == "answer_work_not_shown"


def test_a_staged_candidate_shows_its_work():
    from app.meta.v3.quality import check_answer_work_shown

    assert check_answer_work_shown(_perimeter_candidate().program).passed


def test_a_bare_question_mark_label_is_rejected():
    """The purest stand-in: "?" alone, with no unit to push the mark mid-string."""
    from app.meta.v3.quality import check_answer_stand_in

    program = _perimeter_candidate().program
    program = program.model_copy(update={
        "visuals": [*program.visuals, LabelProgramVisual(ref="gap", text="?")],
    })

    assert not check_answer_stand_in(program).passed


def _perimeter_program_with_callout(text):
    program = _perimeter_candidate().program
    return program.model_copy(update={
        "relations": [
            *program.relations,
            CalloutRelation(
                ref="hint",
                target=AnchorRef(visual_ref="rectangle", part="edge", index=0, anchor="bottom"),
                text=text,
            ),
        ],
    })


def test_a_callout_using_a_question_mark_as_the_answer_is_rejected():
    """Relation text is the other model-authored text surface in the DSL, so a
    model told never to put "?" in a label can author the same dead placeholder
    as a callout instead."""
    from app.meta.v3.quality import check_answer_stand_in

    check = check_answer_stand_in(_perimeter_program_with_callout("? meters"))

    assert not check.passed
    assert check.code == "answer_stand_in_label"
    assert check.path == "relations[0].text"


def test_a_question_prompt_callout_is_left_alone():
    from app.meta.v3.quality import check_answer_stand_in

    assert check_answer_stand_in(
        _perimeter_program_with_callout("What is the perimeter?"),
    ).passed


def test_an_unresolved_answer_without_any_stages_fails():
    """Defence in depth: a program with evaluated_answer but no show_answer_stage
    entries at all must be rejected, even though the evaluated_answer is revealed
    in the first beat and nothing wrong appears until timeline is examined."""
    from app.meta.v3.quality import check_answer_timing

    candidate = _perimeter_candidate()
    timeline = [
        entry for entry in candidate.program.timeline
        if entry.action.kind != "show_answer_stage"
    ]
    program = candidate.program.model_copy(update={"timeline": timeline})

    check = check_answer_timing(candidate.plan, program)

    assert not check.passed
    assert check.code == "premature_answer_emphasis"


def test_a_show_answer_stage_targeting_the_wrong_visual_is_rejected():
    """`ShowAnswerStageAction.target` is a plain `TargetRef` that the action's
    own schema does not constrain to the answer visual; `_action_animation`
    (`app/meta/v3/renderer.py`) would otherwise `KeyError` on
    `rendered.answer_stages[target.visual_ref]` instead of failing a
    structured check."""
    from app.meta.v3.quality import check_answer_stage_target

    candidate = _perimeter_candidate()
    index = next(
        i for i, entry in enumerate(candidate.program.timeline)
        if entry.action.kind == "show_answer_stage" and entry.action.stage == "value"
    )
    entry = candidate.program.timeline[index]
    misdirected = entry.model_copy(update={
        "action": entry.action.model_copy(update={
            "target": entry.action.target.model_copy(update={"visual_ref": "rectangle"}),
        }),
    })
    timeline = list(candidate.program.timeline)
    timeline[index] = misdirected
    program = candidate.program.model_copy(update={"timeline": timeline})

    check = check_answer_stage_target(program)

    assert not check.passed
    assert check.code == "answer_stage_undefined"


def test_a_work_stage_on_an_answer_with_no_operation_is_rejected():
    """`work` only exists in the resolver's `stages` dict when `has_operation`
    is true (`resolver.evaluate_program_visual`'s `answer_expression` branch),
    so a stored program whose answer expression was edited down to a bare
    field reference but still requests `work` would otherwise `KeyError` at
    render time."""
    from app.meta.v3.quality import check_answer_stage_target

    candidate = _perimeter_candidate()
    visuals = [
        visual.model_copy(update={"expression": FieldRefNode(field="length")})
        if visual.ref == "evaluated_answer" else visual
        for visual in candidate.program.visuals
    ]
    program = candidate.program.model_copy(update={"visuals": visuals})

    check = check_answer_stage_target(program)

    assert not check.passed
    assert check.code == "answer_stage_undefined"


def test_pair_elimination_declares_no_answer_stage_so_the_check_passes():
    """`pair_elimination`'s median plan declares no `evaluated_answer` visual,
    and `beat_expander` emits no `show_answer_stage` action for it -- so the
    loop over `program.timeline` never finds one to check, and the check
    trivially passes."""
    from app.meta.v3.quality import check_answer_stage_target

    plan = _median_plan()
    program = _compile(plan, FieldRefNode(field="v4"), {f"v{index}" for index in range(1, 8)})

    assert not any(entry.action.kind == "show_answer_stage" for entry in program.timeline)
    assert check_answer_stage_target(program).passed
