from fractions import Fraction

import pytest

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.scene_program import SceneProgramDocument, ShowRelationAction, TimedAction
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import AnchorRef, CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.geometry import Bounds, MeasuredVisual, Point, SemanticPart
from app.meta.v3.layout import SAFE_FRAME, place_vertical_lesson
from app.meta.v3.resolver import resolve_scene


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


def _field(name):
    return {"node": "field_ref", "field": name}


def _measured_visual(ref, height, width=2):
    bounds = Bounds(-width / 2, width / 2, -height / 2, height / 2)
    return MeasuredVisual(
        ref=ref,
        bounds=bounds,
        parts={("item", 0): SemanticPart("item", 0, bounds)},
        paths={},
        payload={},
    )


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


def test_resolve_scene_carries_a_declared_non_default_initial_role_through_ordered_values(measurer):
    """Pins the production seam `resolve_scene` -> `_evaluated_spec` ->
    `_measure_ordered_values` -> `measure_ordered_values`.

    Every other `initial_role` test either hand-builds a `SimpleNamespace`
    spec directly or exercises `ordered_values` through `compile_teaching_plan`,
    which only ever assigns the kind's default (`"neutral"`) -- so a hardcoded
    `initial_role="neutral"` in `_evaluated_spec`, or a future rebuild of the
    evaluated spec that drops the field, would pass the whole suite while
    making a `structure` declaration a silent no-op on screen. This builds a
    `SceneProgramDocument` directly, the only way to declare a non-default
    role, and checks it survives resolution.
    """
    program = SceneProgramDocument.model_validate({
        "scene_version": 3,
        "visuals": [{
            "kind": "ordered_values", "ref": "values", "initial_role": "structure",
            "values": [
                {"node": "literal", "value": 3}, {"node": "literal", "value": 5},
                {"node": "literal", "value": 8},
            ],
        }],
        "timeline": [{
            "at_seconds": 0.0, "duration_seconds": 1.0, "beat_id": "reveal_values",
            "action": {"kind": "reveal", "targets": [{"visual_ref": "values"}]},
        }],
        "total_duration_seconds": 6.0,
        "variation_seed": "resolver-initial-role",
        "style_recipe": {"palette": "ocean", "composition": "vertical_lesson", "motion_variant": "smooth"},
    })

    resolved = resolve_scene(program, {}, measurer)

    assert resolved.visual("values").measured.payload["initial_role"] == "structure"


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


def test_vertical_layout_centers_the_column_including_the_answer():
    primary, conclusion = place_vertical_lesson([
        _measured_visual("primary", 2),
        _measured_visual("evaluated_answer", 0.6),
    ])

    assert primary.bounds.top <= SAFE_FRAME.top
    assert conclusion.bounds.bottom >= SAFE_FRAME.bottom
    assert conclusion.bounds.top < primary.bounds.bottom
    assert (primary.bounds.top + conclusion.bounds.bottom) / 2 == pytest.approx(0.0)


def test_vertical_layout_scales_visuals_and_gaps_inside_safe_frame():
    original_gap = 0.45
    primary, supporting, conclusion = place_vertical_lesson([
        _measured_visual("primary", 3),
        _measured_visual("supporting", 3, width=7),
        _measured_visual("evaluated_answer", 1),
    ])
    scale = (primary.bounds.top - primary.bounds.bottom) / 3

    assert scale < 1
    # Width 7 exceeds the side budget beside a width-2 primary (6.6 - 1 - 0.45 =
    # 5.15), so this support takes a full-width row of its own. The gap under
    # test is therefore the vertical one; it must still scale with the visuals.
    assert supporting.bounds.bottom - primary.bounds.top == pytest.approx(original_gap * scale)
    for visual in (primary, supporting, conclusion):
        assert visual.bounds.left >= SAFE_FRAME.left - 1e-9
        assert visual.bounds.right <= SAFE_FRAME.right + 1e-9
        assert visual.bounds.bottom >= SAFE_FRAME.bottom - 1e-9
        assert visual.bounds.top <= SAFE_FRAME.top + 1e-9


def test_vertical_layout_keeps_primary_centered_with_supporting_and_conclusion_visuals():
    primary, supporting, conclusion = place_vertical_lesson([
        _measured_visual("primary", 2),
        _measured_visual("supporting", 0.8),
        _measured_visual("evaluated_answer", 0.6),
    ])

    assert primary.bounds.left - supporting.bounds.right == pytest.approx(0.45)
    for visual in (primary, supporting, conclusion):
        assert visual.bounds.bottom >= SAFE_FRAME.bottom
        assert visual.bounds.top <= SAFE_FRAME.top


def test_vertical_layout_places_a_conclusion_only_scene_without_scaling_error():
    conclusion, = place_vertical_lesson([_measured_visual("evaluated_answer", 0.6)])

    assert conclusion.bounds.center.y == pytest.approx(0.0)
    assert conclusion.bounds.bottom >= SAFE_FRAME.bottom


def test_vertical_layout_reuses_support_partition_for_fit_and_placement():
    # Width 8 exceeds the side budget beside a width-2 primary (5.15) and takes a
    # row of its own; the width-5 and width-2 supports sit beside. The scale must
    # come from the same split that placement uses -- if the fit assumed one
    # arrangement and placement produced another, the bounds below escape the
    # safe frame.
    placed = place_vertical_lesson([
        _measured_visual("primary", 3, width=2),
        _measured_visual("support_beside_0", 3, width=5),
        _measured_visual("support_beside_1", 3, width=2),
        _measured_visual("support_stacked", 3, width=8),
        _measured_visual("evaluated_answer", 0.6),
    ])
    by_ref = {visual.measured.ref: visual for visual in placed}

    # Vertical binds: the primary's band (3) plus the stacked row (3) and the gap
    # between them (0.45) is 6.45 against the 6.0-high instructional frame.
    scale = (placed[0].bounds.top - placed[0].bounds.bottom) / 3
    assert scale == pytest.approx(6.0 / 6.45, abs=1e-5)
    # The split itself, which is this test's subject.
    primary_band = by_ref["primary"].bounds
    for ref in ("support_beside_0", "support_beside_1"):
        beside = by_ref[ref].bounds
        assert beside.bottom == pytest.approx(primary_band.bottom)
        assert beside.right <= primary_band.left or beside.left >= primary_band.right
    assert by_ref["support_stacked"].bounds.bottom >= primary_band.top
    for visual in placed:
        assert visual.bounds.left >= SAFE_FRAME.left - 1e-9
        assert visual.bounds.right <= SAFE_FRAME.right + 1e-9
        assert visual.bounds.bottom >= SAFE_FRAME.bottom - 1e-9
        assert visual.bounds.top <= SAFE_FRAME.top + 1e-9


def test_an_answer_expression_resolves_to_three_stages():
    from app.meta.dsl.scene_program import AnswerProgramVisual
    from app.meta.dsl.expression import FieldRefNode, LiteralNode, MultiplyNode
    from app.meta.v3.resolver import evaluate_program_visual

    visual = AnswerProgramVisual(
        ref="evaluated_answer",
        expression=MultiplyNode(operands=[
            FieldRefNode(field="distance_km"), LiteralNode(value=1000),
        ]),
        suffix=" meters",
    )

    spec, payload = evaluate_program_visual(visual, {"distance_km": Fraction(11, 4)})

    assert spec.kind == "answer_expression"
    assert payload["stages"] == {
        "unknown": "? meters",
        "work": "2.75 × 1000 = ? meters",
        "value": "2.75 × 1000 = 2750 meters",
    }


def test_an_answer_with_no_arithmetic_has_no_work_stage():
    """A bare field reference has nothing to show, so a work stage would just
    print the value it is about to resolve to."""
    from app.meta.dsl.scene_program import AnswerProgramVisual
    from app.meta.dsl.expression import FieldRefNode
    from app.meta.v3.resolver import evaluate_program_visual

    visual = AnswerProgramVisual(
        ref="evaluated_answer", expression=FieldRefNode(field="total"), suffix=" apples",
    )

    _spec, payload = evaluate_program_visual(visual, {"total": Fraction(7)})

    assert payload["stages"] == {"unknown": "? apples", "value": "7 apples"}
