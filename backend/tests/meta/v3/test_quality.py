from dataclasses import dataclass

import pytest

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.scene_program import CalloutRelation
from app.meta.dsl.teaching_plan import TeachingPlanDocument
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
        plan = _perimeter_plan()
        perimeter = _compile(
            plan,
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
            {"length", "width"},
        )
        relation = CalloutRelation(
            ref="length_dimension",
            target=AnchorRef(visual_ref="rectangle", part="edge", index=0, anchor="center"),
            text="length",
        )
        detached = relation.model_copy(update={
            "target": relation.target.model_copy(update={"part": None, "index": None}),
        })
        return Candidate(plan, perimeter.model_copy(update={"relations": [detached]}))
    if mutation == "overlap_callout":
        duplicate = program.relations[0].model_copy(update={"ref": "second_callout"})
        return Candidate(candidate.plan, program.model_copy(update={"relations": [*program.relations, duplicate]}))
    if mutation == "extend_to_13_seconds":
        return Candidate(candidate.plan, program.model_copy(update={"total_duration_seconds": 13.0}))
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
])
def test_quality_mutations_fail(valid_program, mutation, expected_code):
    broken = apply_literal_test_mutation(valid_program, mutation)

    report = validate_static_quality(broken.plan, broken.program)

    assert report.passed is False
    assert expected_code in [check.code for check in report.checks if not check.passed]


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
