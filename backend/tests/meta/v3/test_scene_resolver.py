from fractions import Fraction

import pytest

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.scene_program import ShowRelationAction, TimedAction
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import AnchorRef, CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.geometry import Point
from app.meta.v3.resolver import resolve_scene


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


def _field(name):
    return {"node": "field_ref", "field": name}


@pytest.fixture
def measurer():
    return LiteralTextMeasurer()


@pytest.fixture
def program():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values",
            "ref": "values",
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
        "variation_seed": "median-demo",
    })
    return compile_teaching_plan(
        plan,
        FieldRefNode(field="v4"),
        frozenset({f"v{index}" for index in range(1, 8)}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )


@pytest.fixture
def perimeter_program():
    plan = TeachingPlanDocument.model_validate({
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
            {"id": "show_perimeter", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "perimeter-demo",
    })
    return compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )


def test_runtime_resolution_remeasures_new_values_and_keeps_callout_under_item(program, measurer):
    first = resolve_scene(program, {"v1": 3, "v2": 5, "v3": 6, "v4": 8,
                                    "v5": 9, "v6": 12, "v7": 15}, measurer)
    second = resolve_scene(program, {"v1": 10, "v2": 20, "v3": 30, "v4": 40,
                                     "v5": 50, "v6": 60, "v7": 70}, measurer)
    first_target = first.anchor("values", "item", 3, "bottom")
    second_target = second.anchor("values", "item", 3, "bottom")
    assert first.relation("median_callout").target == first_target
    assert second.relation("median_callout").target == second_target
    assert first_target.x != second_target.x or first.visual("values").bounds != second.visual("values").bounds


def test_trace_path_and_timeline_target_use_final_placed_geometry(perimeter_program, measurer):
    scene = resolve_scene(perimeter_program, {"length": 8, "width": 3}, measurer)
    rectangle = scene.visual("rectangle")
    reveal = next(action for action in scene.timeline if action.action.kind == "reveal")
    trace = next(action for action in scene.timeline if action.action.kind == "trace")

    assert reveal.targets[0].bounds == rectangle.bounds
    assert trace.path[0] == Point(
        rectangle.measured.paths["perimeter"][0].x + rectangle.offset.x,
        rectangle.measured.paths["perimeter"][0].y + rectangle.offset.y,
    )
    assert trace.path[0] == trace.path[-1]


def test_relation_with_missing_semantic_part_has_structured_anchor_failure(program, measurer):
    relation = program.relations[0].model_copy(update={
        "target": AnchorRef(visual_ref="values", part="missing", index=3, anchor="bottom"),
    })
    malformed = program.model_copy(update={"relations": [relation]})

    with pytest.raises(V3ValidationError) as exc:
        resolve_scene(malformed, {f"v{index}": index for index in range(1, 8)}, measurer)

    assert exc.value.failure.code == "unknown_semantic_anchor"
    assert exc.value.failure.path == "relations[0].target"


def test_relation_rejects_collection_anchor_for_item(program, measurer):
    relation = program.relations[0].model_copy(update={
        "target": AnchorRef(visual_ref="values", part="item", anchor="bottom"),
    })
    malformed = program.model_copy(update={"relations": [relation]})

    with pytest.raises(V3ValidationError) as exc:
        resolve_scene(malformed, {f"v{index}": index for index in range(1, 8)}, measurer)

    assert exc.value.failure.code == "collection_anchor_for_item"


def test_timeline_unknown_relation_has_structured_action_path(program, measurer):
    replacement = TimedAction(
        at_seconds=program.timeline[0].at_seconds,
        duration_seconds=program.timeline[0].duration_seconds,
        beat_id=program.timeline[0].beat_id,
        action=ShowRelationAction(relation_ref="missing_relation"),
    )
    malformed = program.model_copy(update={"timeline": [replacement, *program.timeline[1:]]})

    with pytest.raises(V3ValidationError) as exc:
        resolve_scene(malformed, {f"v{index}": Fraction(index) for index in range(1, 8)}, measurer)

    assert exc.value.failure.code == "unknown_relation"
    assert exc.value.failure.path == "timeline[0].action.relation_ref"
