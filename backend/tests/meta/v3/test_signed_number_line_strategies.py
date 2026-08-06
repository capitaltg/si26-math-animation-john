"""End-to-end tests for the signed number_line strategies (M6).

`signed_hop` teaches directed motion (+ hops right, - hops left) on a signed
number_line, and `distance_from_zero` annotates a value's distance to the
origin. The compiler enforces the compile-time shape (a signed context for
signed_hop; a 0 marker and a nonzero marker for distance_from_zero) and
tightens `magnitude_comparison` so it can no longer misfire on a signed range.

Acceptance fixtures (ticket #100): -3 + 5, -4 - (-2), |-7|, 2 x -3.
"""

from copy import deepcopy

import pytest

from app.meta.dsl.expression import (
    AddNode, LiteralNode, MultiplyNode, SubtractNode,
)
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.quality import validate_static_quality


@pytest.fixture
def compile_context():
    return CompileContext(concept_family="number_and_operations", grade_band="6-8")


def _literal(value):
    return {"node": "literal", "value": value}


def _signed_hop_plan(
    *, minimum, maximum, markers, seed, objective="Model signed addition on a signed number line.",
):
    """A four-beat signed_hop plan whose markers describe the hop sequence.

    Every marker is drawn as a labelled dot: the start, each intermediate
    running sum, and the end. `signed_hop` falls through to
    `_generic_role_change`, so the beat expander focuses the beat's targets
    at focus/derive time; the arrow-and-direction reading comes from the
    number_line itself showing the running values in signed context.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": objective,
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": _literal(minimum), "maximum": _literal(maximum),
            "markers": [_literal(value) for value in markers],
        },
        "strategy": "signed_hop",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "line"}],
             "intent": "show the signed number line with the start marked"},
            {"id": "hop", "kind": "derive", "targets": [{"visual_ref": "line"}],
             "intent": "hop from start to end in the operation's direction"},
            {"id": "focus_end", "kind": "focus",
             "targets": [{"visual_ref": "line", "part": "marker", "index": len(markers) - 1}],
             "intent": "name the value that lands under the arrowhead"},
            {"id": "state_answer", "kind": "conclude", "targets": [{"visual_ref": "line"}],
             "intent": "state the result of the signed operation"},
        ],
        "variation_seed": seed,
    })


def _distance_plan(*, minimum, maximum, markers, seed, objective):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": objective,
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": _literal(minimum), "maximum": _literal(maximum),
            "markers": [_literal(value) for value in markers],
        },
        "strategy": "distance_from_zero",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "line"}],
             "intent": "show the signed line with 0 and the operand marked"},
            {"id": "measure", "kind": "derive", "targets": [{"visual_ref": "line"}],
             "intent": "read the distance from the marker to the origin"},
            {"id": "state_answer", "kind": "conclude", "targets": [{"visual_ref": "line"}],
             "intent": "state the absolute value"},
        ],
        "variation_seed": seed,
    })


def _assert_compiles_and_passes_quality(plan, answer, compile_context):
    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)
    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]
    return program


# -- Acceptance fixtures ----------------------------------------------------


def test_signed_hop_models_negative_three_plus_five(compile_context):
    """-3 + 5 = 2: start at -3, hop +5 right to 2."""
    plan = _signed_hop_plan(
        minimum=-6, maximum=6, markers=[-3, 2], seed="signed-hop-neg-three-plus-five",
    )
    _assert_compiles_and_passes_quality(
        plan,
        AddNode(operands=[LiteralNode(value=-3), LiteralNode(value=5)]),
        compile_context,
    )


def test_signed_hop_models_negative_four_minus_negative_two(compile_context):
    """-4 - (-2) = -2: start at -4, subtract -2 (hop right +2) to -2."""
    plan = _signed_hop_plan(
        minimum=-6, maximum=2, markers=[-4, -2],
        seed="signed-hop-neg-four-minus-neg-two",
        objective="Model subtracting a negative on a signed number line.",
    )
    _assert_compiles_and_passes_quality(
        plan,
        SubtractNode(operands=[LiteralNode(value=-4), LiteralNode(value=-2)]),
        compile_context,
    )


def test_signed_hop_models_two_times_negative_three(compile_context):
    """2 x -3 = -6: two hops of -3 to the left from 0, landing on -6."""
    plan = _signed_hop_plan(
        minimum=-8, maximum=2, markers=[0, -3, -6],
        seed="signed-hop-two-times-neg-three",
        objective="Model multiplication as repeated signed hops.",
    )
    _assert_compiles_and_passes_quality(
        plan,
        MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=-3)]),
        compile_context,
    )


def test_distance_from_zero_absolute_value_of_negative_seven(compile_context):
    """|-7| = 7: draw 0 and -7 on the line, annotate the distance."""
    plan = _distance_plan(
        minimum=-9, maximum=2, markers=[-7, 0], seed="distance-abs-neg-seven",
        objective="Show that the absolute value of -7 is its distance from 0.",
    )
    _assert_compiles_and_passes_quality(
        plan, LiteralNode(value=7), compile_context,
    )


# -- Compile-time shape enforcement ----------------------------------------


def test_signed_hop_rejects_a_line_with_no_signed_context(compile_context):
    """A [0, 10] line with only positive markers cannot teach signed direction;
    `magnitude_comparison` already covers that shape.
    """
    plan = _signed_hop_plan(
        minimum=0, maximum=10, markers=[2, 7], seed="signed-hop-unsigned-line",
    )
    with pytest.raises(V3ValidationError, match="signed_hop_requires_signed_context"):
        compile_teaching_plan(plan, LiteralNode(value=7), frozenset(), compile_context)


def test_signed_hop_rejects_a_single_marker(compile_context):
    """A signed hop needs a start AND an end; one marker cannot draw the hop."""
    plan = _signed_hop_plan(
        minimum=-5, maximum=5, markers=[-3], seed="signed-hop-single-marker",
    )
    with pytest.raises(V3ValidationError, match="signed_hop_requires_at_least_two_markers"):
        compile_teaching_plan(plan, LiteralNode(value=-3), frozenset(), compile_context)


def test_distance_from_zero_rejects_a_plan_missing_the_origin(compile_context):
    """The annotation lands on 0; a plan whose markers do not include 0 cannot
    stage the origin, and the strategy is decorative without it.
    """
    plan = _distance_plan(
        minimum=-9, maximum=2, markers=[-7, -3], seed="distance-no-origin",
        objective="Distance without an origin.",
    )
    with pytest.raises(V3ValidationError, match="distance_from_zero_requires_zero_marker"):
        compile_teaching_plan(plan, LiteralNode(value=7), frozenset(), compile_context)


def test_distance_from_zero_rejects_a_plan_with_only_the_origin(compile_context):
    """0 alone leaves no distance to measure."""
    plan = _distance_plan(
        minimum=-3, maximum=3, markers=[0], seed="distance-only-origin",
        objective="Distance with no operand.",
    )
    with pytest.raises(V3ValidationError, match="distance_from_zero_requires_nonzero_marker"):
        compile_teaching_plan(plan, LiteralNode(value=0), frozenset(), compile_context)


# -- magnitude_comparison guard on signed ranges ----------------------------


def _magnitude_plan(*, minimum, maximum, markers, seed):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Compare numeric magnitudes on a line.",
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": _literal(minimum), "maximum": _literal(maximum),
            "markers": [_literal(value) for value in markers],
        },
        "strategy": "magnitude_comparison",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "line"}],
             "intent": "show the number line"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "line"}],
             "intent": "compare each marker's magnitude"},
            {"id": "state", "kind": "conclude", "targets": [{"visual_ref": "line"}],
             "intent": "state the largest"},
        ],
        "variation_seed": seed,
    })


def test_magnitude_comparison_rejects_a_negative_line_minimum(compile_context):
    """A left-to-right sweep on a signed line reads left as smaller magnitude,
    which is wrong: -5 sits left of 2 but is greater in absolute value.
    """
    plan = _magnitude_plan(
        minimum=-5, maximum=5, markers=[1, 3], seed="magnitude-signed-minimum",
    )
    with pytest.raises(
        V3ValidationError, match="magnitude_comparison_requires_nonnegative_range",
    ):
        compile_teaching_plan(plan, LiteralNode(value=3), frozenset(), compile_context)


def test_magnitude_comparison_rejects_a_negative_marker(compile_context):
    """Even on a [0, 10] line, a marker at -1 is off-line and cannot sweep in
    the "greater to the right" order magnitude_comparison relies on. The
    measurer rejects the off-range marker too, but the compiler's own guard
    fails earlier with a hint pointing the retry at the M6 strategies.
    """
    plan = _magnitude_plan(
        minimum=0, maximum=10, markers=[2, 5, 8], seed="magnitude-negative-marker",
    )
    raw = plan.model_dump()
    raw["primary_visual"]["markers"][0] = _literal(-2)
    plan = TeachingPlanDocument.model_validate(raw)
    with pytest.raises(
        V3ValidationError, match="magnitude_comparison_requires_nonnegative_markers",
    ):
        compile_teaching_plan(plan, LiteralNode(value=8), frozenset(), compile_context)


# -- Emitted arrow / annotation actions ------------------------------------


def _hop_actions(program):
    return [entry for entry in program.timeline if entry.action.kind == "signed_hop_arrow"]


def _distance_actions(program):
    return [entry for entry in program.timeline if entry.action.kind == "distance_annotation"]


def _target_key(target):
    return (target.visual_ref, target.part, target.index)


def test_signed_hop_emits_one_arrow_between_each_consecutive_marker_pair(compile_context):
    """`2 x -3 = -6` has three markers (0, -3, -6) and therefore two hops."""
    plan = _signed_hop_plan(
        minimum=-8, maximum=2, markers=[0, -3, -6],
        seed="signed-hop-arrows-two-times-neg-three",
        objective="Model multiplication as repeated signed hops.",
    )
    program = _assert_compiles_and_passes_quality(
        plan,
        MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=-3)]),
        compile_context,
    )
    arrows = _hop_actions(program)
    assert len(arrows) == 2, "one arrow per marker pair"
    # Every arrow lands on the hop derive beat (single-owner rule, mirrors
    # magnitude_comparison's sweep beat), so a later derive/focus beat cannot
    # double-stage the arrows.
    assert {entry.beat_id for entry in arrows} == {"hop"}
    ordered = sorted(arrows, key=lambda entry: entry.at_seconds)
    endpoints = [
        (_target_key(entry.action.source), _target_key(entry.action.target))
        for entry in ordered
    ]
    assert endpoints == [
        (("line", "marker", 0), ("line", "marker", 1)),
        (("line", "marker", 1), ("line", "marker", 2)),
    ], "arrows follow the plan's marker order in time"


def test_signed_hop_encodes_direction_through_source_target_order(compile_context):
    """A positive hop (-3 -> 2) draws source left of target; a negative hop
    (-4 -> -2 is still rightward, but on `2 x -3` the hops read left).

    The renderer draws the arrow from `source` to `target`, so the arrowhead
    lands under `target`. That is how the sign is animated: for `2 x -3` both
    hops go leftward and their `source` markers sit to the right of their
    `target` markers on the line.
    """
    plan = _signed_hop_plan(
        minimum=-8, maximum=2, markers=[0, -3, -6],
        seed="signed-hop-direction-two-times-neg-three",
        objective="Model multiplication as repeated signed hops.",
    )
    program = _assert_compiles_and_passes_quality(
        plan,
        MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=-3)]),
        compile_context,
    )
    hop_targets = {entry.action.target.index for entry in _hop_actions(program)}
    hop_sources = {entry.action.source.index for entry in _hop_actions(program)}
    # Sources point to the earlier marker, targets to the later; for a left
    # sequence of markers, `target.index > source.index` places the arrowhead
    # under the marker whose numeric value is smaller (more negative), which
    # is the leftward direction on the rendered line.
    assert hop_sources == {0, 1}
    assert hop_targets == {1, 2}


def test_distance_from_zero_emits_a_bracket_labelled_with_the_magnitude(compile_context):
    """|-7| = 7: one annotation, anchored at the origin marker, labelled `7`."""
    plan = _distance_plan(
        minimum=-9, maximum=2, markers=[-7, 0], seed="distance-abs-neg-seven-actions",
        objective="Show that the absolute value of -7 is its distance from 0.",
    )
    program = _assert_compiles_and_passes_quality(
        plan, LiteralNode(value=7), compile_context,
    )
    annotations = _distance_actions(program)
    assert len(annotations) == 1
    annotation = annotations[0].action
    # Origin is the 0 marker (index 1 in [-7, 0]); target is the -7 marker.
    assert _target_key(annotation.origin) == ("line", "marker", 1)
    assert _target_key(annotation.target) == ("line", "marker", 0)
    assert annotation.label == "7"
    assert annotations[0].beat_id == "measure"


def test_distance_from_zero_renders_end_to_end(compile_context):
    """`|-7|` compiles, resolves, and renders without raising -- the
    annotation reaches the recorded play calls as a `distance_annotation`
    animation. Guards the two rendering paths added for M6 (bracket and
    label) against future regressions that a compile-only test would miss.
    """
    from app.meta.v3.renderer import render_resolved_scene
    from app.meta.v3.resolver import resolve_scene

    plan = _distance_plan(
        minimum=-9, maximum=2, markers=[-7, 0], seed="distance-abs-neg-seven-render",
        objective="Show that the absolute value of -7 is its distance from 0.",
    )
    program = _assert_compiles_and_passes_quality(
        plan, LiteralNode(value=7), compile_context,
    )

    class _LiteralTextMeasurer:
        def measure(self, text, font_role):
            return len(text) * 0.3, 0.6

    class _RecordingScene:
        def __init__(self):
            self.kinds = []

        def play(self, animation, **_kwargs):
            self.kinds.append(animation._semantic_kind)

        def wait(self, _seconds):
            return None

    resolved = resolve_scene(program, {}, _LiteralTextMeasurer())
    scene = _RecordingScene()
    render_resolved_scene(scene, resolved)
    assert "distance_annotation" in scene.kinds


def test_signed_hop_renders_end_to_end(compile_context):
    """`-3 + 5` compiles, resolves, and renders; the hop arrow is played."""
    from app.meta.v3.renderer import render_resolved_scene
    from app.meta.v3.resolver import resolve_scene

    plan = _signed_hop_plan(
        minimum=-6, maximum=6, markers=[-3, 2], seed="signed-hop-neg-three-plus-five-render",
    )
    program = _assert_compiles_and_passes_quality(
        plan,
        AddNode(operands=[LiteralNode(value=-3), LiteralNode(value=5)]),
        compile_context,
    )

    class _LiteralTextMeasurer:
        def measure(self, text, font_role):
            return len(text) * 0.3, 0.6

    class _RecordingScene:
        def __init__(self):
            self.kinds = []

        def play(self, animation, **_kwargs):
            self.kinds.append(animation._semantic_kind)

        def wait(self, _seconds):
            return None

    resolved = resolve_scene(program, {}, _LiteralTextMeasurer())
    scene = _RecordingScene()
    render_resolved_scene(scene, resolved)
    assert "signed_hop_arrow" in scene.kinds


def test_magnitude_comparison_still_accepts_a_nonnegative_signed_plan(compile_context):
    """Regression: the new guard must not tighten past the M6 boundary. A
    [0, 10] line with all-positive markers stays a legal magnitude_comparison.
    """
    plan = _magnitude_plan(
        minimum=0, maximum=10, markers=[2, 5, 8], seed="magnitude-nonnegative",
    )
    program = compile_teaching_plan(plan, LiteralNode(value=8), frozenset(), compile_context)
    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert [action.target.index for action in focus_actions] == [0, 1, 2]
