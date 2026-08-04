from dataclasses import dataclass, replace
from fractions import Fraction
from types import SimpleNamespace

import pytest
from manim import FadeIn, Line, Text

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.scene_program import StyleRecipeDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import _PART_CARDINALITY, compile_teaching_plan
from app.meta.v3.geometry import Bounds, PlacedVisual, Point
from app.meta.v3.manim_measurer import FONT_SIZES, ManimTextMeasurer
from app.meta.v3.renderer import _build_visual, render_resolved_scene
from app.meta.v3.resolver import ResolvedAction, ResolvedScene, ResolvedTarget, resolve_scene
from app.meta.v3.visual_registry import default_visual_registry


def _reveal(mobject):
    """Stand-in `motion` callback for tests that never actually play a reveal."""
    return FadeIn(mobject)


def _resolved_scene_with(visuals: list[PlacedVisual], timeline=()) -> ResolvedScene:
    return ResolvedScene(
        visuals=visuals,
        relations=[],
        # A scene holding an answer visual has to pass its staging actions: the
        # renderer reads the timeline to decide which stage to draw, and a
        # program that stages nothing draws the resolved value instead.
        timeline=list(timeline),
        total_duration_seconds=1.0,
        style_recipe=StyleRecipeDocument(
            palette="ocean", composition="vertical_lesson", motion_variant="smooth",
        ),
    )


def _resolved_action_for(action) -> ResolvedAction:
    return ResolvedAction(
        at_seconds=0.0,
        duration_seconds=1.0,
        beat_id="beat",
        action=action,
        targets=[ResolvedTarget(ref=action.target, bounds=Bounds(0, 0, 0, 0))],
        path=None,
    )


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


@dataclass
class PlayCall:
    index: int
    kind: str
    target_refs: tuple[str, ...] = ()
    target: tuple[str, str | None, int | None] | None = None
    targets: tuple[tuple[str, str | None, int | None], ...] = ()
    role: str | None = None
    run_time: float | None = None


class RecordingScene:
    def __init__(self):
        self.play_calls = []
        self.wait_calls = []

    def play(self, animation, **_kwargs):
        self.play_calls.append(PlayCall(
            index=len(self.play_calls),
            kind=animation._semantic_kind,
            target_refs=animation._semantic_target_refs,
            target=animation._semantic_target,
            targets=getattr(animation, "_semantic_targets", ()),
            role=animation._semantic_role,
            run_time=_kwargs.get("run_time"),
        ))

    def wait(self, seconds):
        self.wait_calls.append(seconds)


@pytest.fixture
def resolved_median_scene():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values",
            "ref": "values",
            "values": [{"node": "field_ref", "field": f"v{index}"} for index in range(1, 8)],
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
        "variation_seed": "median-renderer",
    })
    program = compile_teaching_plan(
        plan,
        FieldRefNode(field="v4"),
        frozenset({f"v{index}" for index in range(1, 8)}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    return resolve_scene(
        program,
        {f"v{index}": index for index in range(1, 8)},
        LiteralTextMeasurer(),
    )


def test_values_reveal_in_one_play_and_focus_changes_later(resolved_median_scene):
    scene = RecordingScene()
    render_resolved_scene(scene, resolved_median_scene)
    assert scene.play_calls[0].kind == "group_reveal"
    assert scene.play_calls[0].target_refs == ("values",)
    focus_call = next(call for call in scene.play_calls if call.kind == "set_role")
    assert focus_call.target == ("values", "item", 3)
    assert focus_call.role == "focus"
    assert focus_call.index > scene.play_calls[0].index


def test_set_role_transitions_every_resolved_target(resolved_median_scene):
    focus = next(action for action in resolved_median_scene.timeline if action.action.kind == "set_role" and action.action.role == "focus")
    another_item = next(action for action in resolved_median_scene.timeline if action.action.kind == "set_role" and action.targets[0].ref.index == 0)
    resolved = replace(
        resolved_median_scene,
        timeline=[replace(focus, targets=[focus.targets[0], another_item.targets[0]])],
        total_duration_seconds=focus.duration_seconds,
    )

    scene = RecordingScene()
    rendered = render_resolved_scene(scene, resolved)

    expected_targets = (("values", "item", 3), ("values", "item", 0))
    assert scene.play_calls[0].targets == expected_targets
    assert {rendered.roles[target] for target in expected_targets} == {"focus"}


def test_coincident_non_reveal_actions_share_timeline_duration(resolved_median_scene):
    focus = next(action for action in resolved_median_scene.timeline if action.action.kind == "set_role" and action.action.role == "focus")
    constraint = next(action for action in resolved_median_scene.timeline if action.action.kind == "set_role" and action.targets[0].ref.index == 0)
    concurrent_focus = replace(focus, at_seconds=1.0, duration_seconds=1.0)
    concurrent_constraint = replace(constraint, at_seconds=1.0, duration_seconds=0.5)
    follow_up = replace(focus, at_seconds=2.5, duration_seconds=0.25)
    resolved = replace(
        resolved_median_scene,
        timeline=[concurrent_focus, concurrent_constraint, follow_up],
        total_duration_seconds=4.0,
    )

    scene = RecordingScene()
    render_resolved_scene(scene, resolved)

    assert [call.run_time for call in scene.play_calls] == [1.0, 0.25]
    assert scene.play_calls[0].kind == "parallel"
    assert scene.wait_calls == pytest.approx([1.0, 0.5, 1.25])


def test_declared_initial_role_overrides_the_payload_shape_derivation():
    from app.meta.v3.renderer import _initial_role

    assert _initial_role("values", {"values": (1, 2, 3)}) == "neutral"
    assert _initial_role("values", {"values": (1, 2, 3), "initial_role": "structure"}) == "structure"


def test_manim_text_measurer_uses_the_renderer_font_table():
    measured = ManimTextMeasurer().measure("42", "math_value")
    text = Text("42", font_size=FONT_SIZES["math_value"])
    assert measured == pytest.approx((text.width, text.height))


def test_rectangle_renderer_maps_edges_and_plays_its_resolved_trace():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Trace a rectangle perimeter.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace its boundary"},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the result"},
        ],
        "variation_seed": "rectangle-renderer",
    })
    program = compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    resolved = resolve_scene(
        program, {"length": 8, "width": 3}, LiteralTextMeasurer(),
    )

    scene = RecordingScene()
    rendered = render_resolved_scene(scene, resolved)

    assert all(("rectangle", "edge", index) in rendered.targets for index in range(4))
    assert any(call.kind == "trace" for call in scene.play_calls)


_MEASURABLE_VALUES = {
    "ordered_values": {"values": ["3", "5", "8"]},
    "rectangle_measurement": {"length": Fraction(8), "width": Fraction(3), "unit": "cm"},
    "number_line": {"minimum": Fraction(0), "maximum": Fraction(10), "markers": [Fraction(4)]},
    "grid": {"rows": 2, "columns": 3},
    "partition": {"whole": Fraction(8), "parts": 4},
    "bar": {"value": Fraction(3), "maximum": Fraction(5)},
    "object_set": {"count": 6},
    "label": {"text": "Answer"},
}


@pytest.mark.parametrize("kind", sorted(_PART_CARDINALITY))
def test_every_compiler_targetable_part_resolves_to_a_rendered_mobject(kind):
    """A part the compiler accepts as a target must be renderable.

    `compiler._PART_CARDINALITY` decides which semantic parts a plan may name,
    `measure_rectangle` and friends give them geometry, and the resolver resolves
    them -- but the renderer builds child mobjects independently, so a part
    declared in all three and built by none crashes `_target_mobject` with a
    KeyError. Inside the probe subprocess that surfaces only as
    `render_probe_failed`, "probe renderer exited unsuccessfully", after three
    burnt generation attempts.

    `tests/meta/v3/test_capability_consistency.py` deliberately compares
    declarations only ("never compile a plan"), so this is the check that the
    declarations are actually backed by geometry the renderer can find.
    """
    measured = default_visual_registry().measure(
        SimpleNamespace(kind=kind, ref=kind, initial_role="neutral"), _MEASURABLE_VALUES[kind], ManimTextMeasurer(),
    )
    _root, children = _build_visual(PlacedVisual(measured, Point(0.0, 0.0)), "ocean")

    targetable = {
        key for key in measured.parts if key[0] in _PART_CARDINALITY[kind]
    }
    missing = sorted(targetable - set(children))
    assert not missing, f"{kind} declares targetable parts the renderer never builds: {missing}"


def _scaled_down_lesson_plan():
    """A rectangle plus a label wide enough that layout must scale the lesson down.

    `place_vertical_lesson` fits the lesson inside `SAFE_FRAME` by scaling every
    measured bound uniformly. The renderer then rebuilt label text from the
    payload at a fixed font size, so only the text escaped that scale.

    The label is long enough (13.85 units) to exceed even the full 13.2-unit
    width of a stacked row, which is what forces a scale below 1 now that a wide
    supporting label no longer has to squeeze in beside the primary.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find the perimeter of a rectangle from its two dimensions.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rect",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "supporting_visuals": [
            {"kind": "label", "ref": "formula_label", "text": "Perimeter equals two times the length plus the width of the rectangle"},
        ],
        "strategy": "boundary_trace",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "rect"}],
             "intent": "show the measured rectangle"},
            {"id": "organize", "kind": "organize", "targets": [{"visual_ref": "formula_label"}],
             "intent": "introduce the perimeter formula"},
            {"id": "derive", "kind": "derive", "targets": [{"visual_ref": "rect"}],
             "intent": "substitute the two dimensions into the formula"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "formula_label"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "scaled-down-lesson",
    })


def test_label_text_is_rendered_at_the_scale_layout_assigned_it():
    """A label's rendered glyphs must fill exactly the box layout reserved for it.

    Measured with the real `ManimTextMeasurer`, a label's measured size IS its
    manim `Text` size, so after a uniform layout scale the rendered mobject must
    match its placed bounds. It did not: the bounds were scaled and the `Text`
    was rebuilt at `FONT_SIZES["label"]`, so the glyphs overran their reserved
    box by 1/scale -- off the safe frame on one side and into the primary visual
    on the other.
    """
    plan = _scaled_down_lesson_plan()
    program = compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    resolved = resolve_scene(program, {"length": 8, "width": 3}, ManimTextMeasurer())
    placed = resolved.visual("formula_label").bounds
    unscaled_width, _height = ManimTextMeasurer().measure(
        "Perimeter equals two times the length plus the width of the rectangle", "label",
    )
    reserved_width = placed.right - placed.left
    assert reserved_width < unscaled_width, "this lesson must be scaled down to be a test"

    rendered = render_resolved_scene(RecordingScene(), resolved)

    assert float(rendered.visuals["formula_label"].width) == pytest.approx(
        reserved_width, abs=0.01,
    )


def test_rectangle_renders_its_measured_dimensions_as_visible_text():
    """The length and width must reach the screen as glyphs, not just as geometry.

    The renderer read `length`/`width` from the payload only to size the box, so
    a perimeter lesson showed a rectangle with no numbers on it -- nothing to add
    up. The rendered text also has to carry the layout scale, like every other
    label.
    """
    plan = _scaled_down_lesson_plan()
    program = compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    resolved = resolve_scene(program, {"length": 8, "width": 3}, ManimTextMeasurer())

    rendered = render_resolved_scene(RecordingScene(), resolved)

    length_label = rendered.targets[("rect", "length_label", 0)]
    width_label = rendered.targets[("rect", "width_label", 0)]
    # `Text.text` is manim-normalised ("8cm"); `original_text` is what we passed.
    assert length_label.original_text == "8 cm"
    assert width_label.original_text == "3 cm"
    # The length labels the bottom edge and the width the left edge, so a
    # swapped pair would put "3 cm" under the shape. Compare against the edges,
    # not the group -- the labels are submobjects, so the group's own extent
    # already includes them.
    bottom_edge = rendered.targets[("rect", "length_edge", 0)]
    left_edge = rendered.targets[("rect", "width_edge", 0)]
    assert float(length_label.get_top()[1]) <= float(bottom_edge.get_bottom()[1])
    assert float(width_label.get_right()[0]) <= float(left_edge.get_left()[0])
    reserved = resolved.visual("rect").measured.parts[("length_label", 0)].bounds
    assert float(length_label.width) == pytest.approx(
        reserved.right - reserved.left, abs=0.01,
    )


def _perimeter_plan_emphasizing_alias_edges():
    """A boundary_trace plan whose derive beat emphasizes the declared
    `length_edge`/`width_edge` semantic parts.

    `compiler._PART_CARDINALITY` declares both as valid rectangle targets
    (cardinality 2 each) and `resolver` resolves them, so this plan compiles,
    resolves and passes static quality -- but the renderer only ever built
    child mobjects for the plain numbered `edge` parts, so every such plan
    died with a `KeyError` inside `_target_mobject`. The subprocess exit is
    caught and converted to a validation failure, so the operator only ever
    saw three burnt generation attempts and a generic retry hint.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the rectangle"},
            {"id": "pair_the_edges", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "each length edge and each width edge occurs twice",
             "custom_actions": [
                 {"kind": "emphasize", "target": {
                     "visual_ref": "rectangle", "part": "length_edge", "index": 0}},
                 {"kind": "emphasize", "target": {
                     "visual_ref": "rectangle", "part": "length_edge", "index": 1}},
                 {"kind": "emphasize", "target": {
                     "visual_ref": "rectangle", "part": "width_edge", "index": 0}},
                 {"kind": "emphasize", "target": {
                     "visual_ref": "rectangle", "part": "width_edge", "index": 1}},
             ]},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the result"},
        ],
        "variation_seed": "rectangle-alias-edges",
    })


def test_rectangle_alias_edge_parts_render_the_same_lines_as_their_numbered_edges():
    """The alias entries must point at the SAME `Line` mobjects the numbered
    edges use, in the pairing `rectangle_measurement.measure_rectangle`
    declares: length is bottom/top (edge 0 and 2), width is left/right
    (edge 3 and 1). Asserting object identity -- not merely presence -- is what
    makes this fail if the aliases are ever registered as fresh, separately
    styled duplicates that emphasis would visibly miss.
    """
    plan = _perimeter_plan_emphasizing_alias_edges()
    program = compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    resolved = resolve_scene(program, {"length": 8, "width": 3}, LiteralTextMeasurer())

    scene = RecordingScene()
    rendered = render_resolved_scene(scene, resolved)

    targets = rendered.targets
    assert targets[("rectangle", "length_edge", 0)] is targets[("rectangle", "edge", 0)]
    assert targets[("rectangle", "length_edge", 1)] is targets[("rectangle", "edge", 2)]
    assert targets[("rectangle", "width_edge", 0)] is targets[("rectangle", "edge", 3)]
    assert targets[("rectangle", "width_edge", 1)] is targets[("rectangle", "edge", 1)]
    # The four emphasis actions really did play, so `_target_mobject` resolved
    # every alias key rather than raising.
    assert [call.role for call in scene.play_calls if call.role] == ["focus"] * 4
    # The rectangle group still holds exactly four Lines: the aliases are
    # additional *names* for those lines, not extra geometry. (The two dimension
    # labels are separate Text mobjects, not duplicated edges.)
    lines = [
        submobject for submobject in rendered.visuals["rectangle"].submobjects
        if isinstance(submobject, Line)
    ]
    assert len(lines) == 4


def test_the_answer_renders_every_stage_and_transforms_between_them():
    """The unknown stage is the mobject on screen; the transitions mutate it in
    place, so `dynamic_render_worker._answer_visible` keeps finding the same
    mobject in the final frame."""
    from manim import Transform

    from app.meta.dsl.scene_program import ShowAnswerStageAction
    from app.meta.dsl.v3_common import TargetRef
    from app.meta.v3.geometry import Bounds, MeasuredVisual, PlacedVisual, Point
    from app.meta.v3.renderer import _action_animation, _build_vertical_lesson

    stages = {"unknown": "? m", "work": "2 × 3 = ? m", "value": "2 × 3 = 6 m"}
    measured = MeasuredVisual(
        ref="evaluated_answer",
        bounds=Bounds(-1, 1, -0.2, 0.2),
        parts={},
        paths={},
        payload={"stages": stages},
    )
    action = _resolved_action_for(
        ShowAnswerStageAction(target=TargetRef(visual_ref="evaluated_answer"), stage="work"),
    )
    scene = _resolved_scene_with([PlacedVisual(measured, Point(0, 0), 1.0)], timeline=[action])

    rendered = _build_vertical_lesson(scene, "ocean")

    assert set(rendered.answer_stages["evaluated_answer"]) == {"unknown", "work", "value"}
    assert rendered.visuals["evaluated_answer"] is (
        rendered.answer_stages["evaluated_answer"]["unknown"]
    )

    assert isinstance(_action_animation(action, rendered, _reveal, "ocean"), Transform)


def _answer_and_label_scene():
    """An answer visual plus an unrelated label, both placed."""
    from app.meta.dsl.scene_program import ShowAnswerStageAction
    from app.meta.dsl.v3_common import TargetRef
    from app.meta.v3.geometry import Bounds, MeasuredVisual, PlacedVisual, Point

    answer = MeasuredVisual(
        ref="evaluated_answer",
        bounds=Bounds(-1, 1, -0.2, 0.2),
        parts={},
        paths={},
        payload={"stages": {"unknown": "? m", "work": "2 × 3 = ? m", "value": "2 × 3 = 6 m"}},
    )
    label = MeasuredVisual(
        ref="hint", bounds=Bounds(-1, 1, 1, 1.4), parts={}, paths={}, payload={"text": "1 km"},
    )
    return _resolved_scene_with(
        [PlacedVisual(answer, Point(0, 0), 1.0), PlacedVisual(label, Point(0, 0), 1.0)],
        timeline=[
            _resolved_action_for(ShowAnswerStageAction(
                target=TargetRef(visual_ref="evaluated_answer"), stage=stage,
            ))
            for stage in ("work", "value")
        ],
    )


def _play_slot(actions):
    """Run one timeline slot through the renderer and return (animations, rendered)."""
    from app.meta.v3.renderer import _build_vertical_lesson, _play_parallel_actions

    scene = _answer_and_label_scene()
    rendered = _build_vertical_lesson(scene, "ocean")
    played = []
    recorder = SimpleNamespace(play=lambda animation, **_kwargs: played.append(animation))
    _play_parallel_actions(recorder, actions, rendered, _reveal, "ocean")
    assert len(played) == 1, "a slot is one play call"
    return played[0].animations, rendered


def test_concluding_the_answer_recolours_and_resolves_it_in_one_animation():
    """One mobject, one slot, one `Transform` -- or the value stage never shows.

    The conclude beat emits `show_answer_stage(value)` and `set_role(conclusion)`
    together on the answer. Rendered as two `Transform`s in one `AnimationGroup`
    they both rewrite the same points every frame, and the recolour -- whose
    target is a copy of the mobject as it stands at `begin()`, i.e. the WORK stage
    -- wins because it is second. Every lesson ended on "2 × 3 = ? m" in the
    conclusion colour: the resolved answer was rendered nowhere. Merging them is
    the fix, so pin the merge, not just the count.
    """
    from app.meta.dsl.scene_program import SetRoleAction, ShowAnswerStageAction
    from app.meta.dsl.v3_common import TargetRef
    from app.meta.manim_primitives.style import resolve_semantic_style

    target = TargetRef(visual_ref="evaluated_answer")
    animations, rendered = _play_slot([
        # Compiler order: the stage action comes first, which is what made a
        # decide-as-you-go merge emit its animation before the `set_role`.
        _resolved_action_for(ShowAnswerStageAction(target=target, stage="value")),
        _resolved_action_for(SetRoleAction(target=target, role="conclusion")),
    ])

    assert len(animations) == 1
    stages = rendered.answer_stages["evaluated_answer"]
    destination = animations[0].target_mobject
    # The one animation morphs the on-screen mobject into the VALUE stage...
    assert animations[0].mobject is rendered.visuals["evaluated_answer"]
    assert destination is stages["value"]
    # `original_text`, not `text`: manim strips whitespace out of the latter.
    assert destination.original_text == "2 × 3 = 6 m"
    # ...wearing the conclusion role's colour, so the recolour is not simply lost.
    expected = resolve_semantic_style("ocean", "conclusion")["color"].to_hex()
    assert all(member.get_color().to_hex() == expected for member in destination.get_family())
    # And the role bookkeeping later `set_role`s diff against still moved.
    assert rendered.roles[("evaluated_answer", None, None)] == "conclusion"


def test_a_role_change_beside_an_unrelated_answer_stage_keeps_both_animations():
    """Merging is per mobject: a `set_role` on another visual must not absorb the
    answer's stage change, and the un-co-slotted `work` stage (the derive beat)
    must animate exactly as it always did."""
    from app.meta.dsl.scene_program import SetRoleAction, ShowAnswerStageAction
    from app.meta.dsl.v3_common import TargetRef

    animations, rendered = _play_slot([
        _resolved_action_for(ShowAnswerStageAction(
            target=TargetRef(visual_ref="evaluated_answer"), stage="work",
        )),
        _resolved_action_for(SetRoleAction(target=TargetRef(visual_ref="hint"), role="focus")),
    ])

    assert len(animations) == 2
    stages = rendered.answer_stages["evaluated_answer"]
    destinations = [animation.target_mobject for animation in animations]
    assert stages["work"] in destinations
    assert rendered.roles[("hint", None, None)] == "focus"
    # The answer's role is untouched: nothing in this slot addressed it.
    assert rendered.roles[("evaluated_answer", None, None)] != "focus"
