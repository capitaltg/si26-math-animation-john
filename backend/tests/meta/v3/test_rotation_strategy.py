"""M22 rotation strategy — compiler validator + frozen `rotation_frames`."""

import math

import pytest

from app.meta.dsl.expression import FieldRefNode, LiteralNode
from app.meta.dsl.teaching_plan import (
    CoordinatePlaneVisual, CoordinatePointNode, EmphasizeRequest, PolygonSpec,
    TeachingBeat, TeachingPlanDocument,
)
from app.meta.dsl.v3_common import CompileContext, TargetRef
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError


def _lit(v):
    return LiteralNode(value=v)


def _point(x, y):
    return {"x": _lit(x), "y": _lit(y)}


@pytest.fixture
def compile_context():
    return CompileContext(concept_family="geometry", grade_band="6-8")


def _compile(plan, *, compile_context):
    """`compile_teaching_plan` needs an answer expression and known-field set
    on top of the plan; rotation has no derived numeric answer, so a literal
    placeholder (unused by any assertion here) satisfies the signature.
    """
    return compile_teaching_plan(plan, LiteralNode(value=0), frozenset(), compile_context)


def _plane_with_triangle(*, angle=90, iterations=3, extent=5):
    return CoordinatePlaneVisual(
        ref="plane",
        x_min=_lit(-extent), x_max=_lit(extent),
        y_min=_lit(-extent), y_max=_lit(extent),
        polygons=[PolygonSpec(
            ref="tri",
            vertices=[_point(1, 0), _point(3, 0), _point(2, 2)],
        )],
        pivot=_point(0, 0),
        rotation_angle_deg=angle,
        rotation_iterations=iterations,
    )


def _rotation_plan(**overrides):
    plane = overrides.pop("primary_visual", _plane_with_triangle())
    return TeachingPlanDocument(
        plan_version=3,
        learning_objective="Rotate a triangle 90 degrees about the origin three times.",
        primary_visual=plane,
        strategy="rotation",
        beats=[
            TeachingBeat(id="reveal", kind="reveal",
                         targets=[{"visual_ref": "plane"}],
                         intent="Show the triangle."),
            TeachingBeat(id="derive", kind="derive",
                         targets=[{"visual_ref": "plane"}],
                         intent="Rotate three times."),
            TeachingBeat(id="conclude", kind="conclude",
                         targets=[{"visual_ref": "plane"}],
                         intent="Land the image."),
        ],
        variation_seed="v1",
        **overrides,
    )


def test_rotation_compiles_and_computes_three_frames(compile_context):
    program = _compile(_rotation_plan(), compile_context=compile_context)
    plane_program = next(v for v in program.visuals if v.kind == "coordinate_plane")

    assert len(plane_program.rotation_frames) == 3

    # 90 degrees CCW about (0, 0): (x, y) -> (-y, x). Applied 3 times to the
    # triangle (1, 0), (3, 0), (2, 2).
    expected = [
        [(0.0, 1.0), (0.0, 3.0), (-2.0, 2.0)],       # iter 1
        [(-1.0, 0.0), (-3.0, 0.0), (-2.0, -2.0)],    # iter 2
        [(0.0, -1.0), (0.0, -3.0), (2.0, -2.0)],     # iter 3
    ]
    for frame_index, expected_verts in enumerate(expected):
        for i, (ex, ey) in enumerate(expected_verts):
            ax, ay = plane_program.rotation_frames[frame_index][i]
            assert math.isclose(ax, ex, abs_tol=1e-9)
            assert math.isclose(ay, ey, abs_tol=1e-9)


def test_rotation_rejects_missing_pivot(compile_context):
    plane = _plane_with_triangle()
    plane_no_pivot = plane.model_copy(update={"pivot": None})
    with pytest.raises(V3ValidationError, match="rotation_requires_pivot_and_angle_and_iterations"):
        _compile(_rotation_plan(primary_visual=plane_no_pivot), compile_context=compile_context)


def test_rotation_rejects_image_off_plane(compile_context):
    # A corner-adjacent vertex has a radius (from the origin pivot) larger
    # than the plane's half-width. A pure 45-degree-aligned rotation keeps
    # every intermediate image inside a symmetric square (the rotation only
    # ever swaps/negates coordinates whose magnitudes already fit); to force
    # a genuine, unambiguous excursion off the plane, this vertex's rotated
    # position has to land *on an axis* at its full radius, well past the
    # plane's edge rather than merely touching it.
    plane = CoordinatePlaneVisual(
        ref="plane",
        x_min=_lit(-3), x_max=_lit(3),
        y_min=_lit(-3), y_max=_lit(3),
        polygons=[PolygonSpec(
            ref="tri",
            vertices=[_point(2.9, 2.9), _point(-2.9, -1), _point(0, -2.9)],
        )],
        pivot=_point(0, 0),
        rotation_angle_deg=45,
        rotation_iterations=2,
    )
    with pytest.raises(V3ValidationError, match="rotation_image_off_plane"):
        _compile(_rotation_plan(primary_visual=plane), compile_context=compile_context)


def test_rotation_rejects_identity_mid_sequence(compile_context):
    plane = _plane_with_triangle(angle=180, iterations=2)
    with pytest.raises(V3ValidationError, match="rotation_returns_to_start"):
        _compile(_rotation_plan(primary_visual=plane), compile_context=compile_context)


def test_rotation_rejects_zero_polygons(compile_context):
    plane = _plane_with_triangle().model_copy(update={"polygons": []})
    with pytest.raises(V3ValidationError, match="rotation_requires_one_polygon"):
        _compile(_rotation_plan(primary_visual=plane), compile_context=compile_context)


def test_rotation_rejects_field_ref_pivot(compile_context):
    """`CoordinatePointNode.x`/`.y` are typed `ExpressionNode`, so a plan is
    schema-legal with a field-ref pivot; `_compute_rotation_frames` must
    refuse it with a named failure code rather than crash on arithmetic with
    a non-numeric operand."""
    plane = _plane_with_triangle()
    field_ref_pivot = CoordinatePointNode(x=FieldRefNode(field="pivot_x"), y=_lit(0))
    plane_field_ref_pivot = plane.model_copy(update={"pivot": field_ref_pivot})
    with pytest.raises(V3ValidationError, match="rotation_requires_literal_geometry"):
        _compile(_rotation_plan(primary_visual=plane_field_ref_pivot), compile_context=compile_context)


def test_group_reveal_still_accepts_polygon_free_plane(compile_context):
    """Backward-compat: coordinate_plane + group_reveal (no polygon) still
    compiles once `rotation` gains its own polygon/pivot requirements."""
    plane = CoordinatePlaneVisual(
        ref="plane",
        x_min=_lit(-5), x_max=_lit(5), y_min=_lit(-5), y_max=_lit(5),
        points=[_point(2, 3)],
    )
    plan = TeachingPlanDocument(
        plan_version=3,
        learning_objective="Show a single plotted point on a coordinate plane.",
        primary_visual=plane,
        strategy="group_reveal",
        beats=[
            TeachingBeat(id="reveal", kind="reveal",
                         targets=[{"visual_ref": "plane"}], intent="Show."),
            TeachingBeat(id="focus", kind="focus",
                         targets=[{"visual_ref": "plane"}], intent="Focus."),
            TeachingBeat(id="conclude", kind="conclude",
                         targets=[{"visual_ref": "plane"}], intent="Done."),
        ],
        variation_seed="v1",
    )
    program = _compile(plan, compile_context=compile_context)
    assert program is not None


def test_rotation_stages_one_rotate_action_per_iteration_on_derive(compile_context):
    program = _compile(_rotation_plan(), compile_context=compile_context)
    rotate_actions = [
        entry for entry in program.timeline
        if entry.action.kind == "rotate"
    ]
    assert len(rotate_actions) == 3
    assert [entry.action.iteration for entry in rotate_actions] == [1, 2, 3]
    # All rotate actions belong to a single focus-or-derive beat.
    beat_ids = {entry.beat_id for entry in rotate_actions}
    assert beat_ids == {"derive"}


def test_rotation_program_names_the_polygon_as_its_answer_anchor(compile_context):
    program = _compile(_rotation_plan(), compile_context=compile_context)
    assert program.answer_anchor.model_dump() == {
        "visual_ref": "plane", "part": "polygon", "index": 0,
    }


def test_rotation_rejects_zero_focus_or_derive_beats(compile_context):
    plan = _rotation_plan()
    # Replace the derive beat with an organize beat: leaves zero focus/derive.
    plan = plan.model_copy(update={"beats": [
        plan.beats[0],
        plan.beats[1].model_copy(update={"kind": "organize"}),
        plan.beats[2],
    ]})
    with pytest.raises(V3ValidationError, match="rotation_requires_one_focus_or_derive_beat"):
        _compile(plan, compile_context=compile_context)


def test_rotation_rejects_two_focus_or_derive_beats(compile_context):
    plan = _rotation_plan()
    plan = plan.model_copy(update={"beats": [
        plan.beats[0],
        plan.beats[1],  # derive
        plan.beats[1].model_copy(update={"id": "focus_two", "kind": "focus"}),
        plan.beats[2],
    ]})
    with pytest.raises(V3ValidationError, match="rotation_requires_one_focus_or_derive_beat"):
        _compile(plan, compile_context=compile_context)


def test_rotation_rejects_custom_actions_on_the_derive_beat(compile_context):
    plan = _rotation_plan()
    beats = list(plan.beats)
    beats[1] = beats[1].model_copy(update={
        "custom_actions": [
            EmphasizeRequest(target=TargetRef(visual_ref="plane"), role="focus"),
        ],
    })
    plan = plan.model_copy(update={"beats": beats})
    with pytest.raises(V3ValidationError, match="rotation_custom_actions_forbidden"):
        _compile(plan, compile_context=compile_context)
