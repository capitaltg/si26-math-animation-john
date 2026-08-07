import pytest

from app.meta.dsl.expression import LiteralNode
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.layout import CALLOUT_ENVELOPE, MIN_TEXT_SCALE, SAFE_FRAME
from app.meta.v3.resolver import resolve_scene


class _LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.2, 0.4


@pytest.fixture
def compile_context():
    return CompileContext(concept_family="ratio", grade_band="6-8")


def _percent_of_whole_plan(*, value, maximum=100, beats=None):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Read a percent as part of a hundred-unit whole.",
        "primary_visual": {
            "kind": "bar", "ref": "percent_bar",
            "value": {"node": "literal", "value": value},
            "maximum": {"node": "literal", "value": maximum},
        },
        "strategy": "percent_of_whole",
        "beats": beats or [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "percent_bar"}],
             "intent": "show the whole bar"},
            {"id": "sweep_part", "kind": "derive", "targets": [{"visual_ref": "percent_bar"}],
             "intent": "sweep the part of the whole the percent names"},
            {"id": "state_value", "kind": "conclude", "targets": [{"visual_ref": "percent_bar"}],
             "intent": "state the percent"},
        ],
        "variation_seed": "percent-of-whole",
    })


def _percent_change_plan(*, before, after, maximum=100, beats=None):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Compare a before value to an after value.",
        "primary_visual": {
            "kind": "bar", "ref": "before_bar",
            "value": {"node": "literal", "value": before},
            "maximum": {"node": "literal", "value": maximum},
        },
        "supporting_visuals": [{
            "kind": "bar", "ref": "after_bar",
            "value": {"node": "literal", "value": after},
            "maximum": {"node": "literal", "value": maximum},
        }],
        "strategy": "percent_change",
        "beats": beats or [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "before_bar"}],
             "intent": "show the before value"},
            {"id": "reveal_after", "kind": "reveal", "targets": [{"visual_ref": "after_bar"}],
             "intent": "bring in the after value"},
            {"id": "sweep_delta", "kind": "derive", "targets": [{"visual_ref": "after_bar"}],
             "intent": "sweep the delta between before and after"},
            {"id": "state_change", "kind": "conclude", "targets": [{"visual_ref": "after_bar"}],
             "intent": "state the percent change"},
        ],
        "variation_seed": "percent-change",
    })


def test_percent_of_whole_sweeps_only_the_part_of_the_whole(compile_context):
    """A 30% bar should focus segments [0..29], leaving [30..99] structural.

    That contrast is what teaches "30 of 100": the part in the accent role,
    the remainder still in the initial structural role.
    """
    plan = _percent_of_whole_plan(value=30)

    program = compile_teaching_plan(
        plan, LiteralNode(value=30), frozenset(), compile_context,
    )

    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep_part" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert [action.target.part for action in focus_actions] == ["segment"] * 30
    assert [action.target.index for action in focus_actions] == list(range(30))


def test_percent_of_whole_sweep_is_one_focus_per_instant(compile_context):
    """`check_salience` rejects two focus role changes at the same at_seconds.
    The slot-per-segment sizing is what keeps the sweep passing that gate --
    the same discipline `magnitude_comparison` already applies.
    """
    plan = _percent_of_whole_plan(value=15)

    program = compile_teaching_plan(
        plan, LiteralNode(value=15), frozenset(), compile_context,
    )

    starts = [
        entry.at_seconds for entry in program.timeline
        if entry.beat_id == "sweep_part" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert len(set(starts)) == len(starts) == 15


def test_percent_of_whole_refuses_a_non_hundred_maximum(compile_context):
    """A percent bar's maximum must be 100. A bar with maximum=60 would let
    the plan claim "30% of 60" is a sweep to segment 30, which is a magnitude
    walk, not a percent reading.
    """
    plan = _percent_of_whole_plan(value=18, maximum=60)

    with pytest.raises(
        V3ValidationError, match="percent_of_whole_requires_hundred_maximum",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=18), frozenset(), compile_context,
        )


def test_percent_of_whole_refuses_value_at_the_boundary(compile_context):
    """`value` must sit strictly between 0 and 100, so both the "part" and
    the "whole minus part" stay on screen. A value of 100 puts every
    segment in focus and loses the contrast that carries the reading; 0
    would sweep nothing and fall through to a whole-visual focus.
    """
    for degenerate in (0, 100):
        plan = _percent_of_whole_plan(value=degenerate)
        with pytest.raises(
            V3ValidationError, match="percent_of_whole_requires_value_in_range",
        ):
            compile_teaching_plan(
                plan, LiteralNode(value=degenerate), frozenset(), compile_context,
            )


def test_percent_of_whole_rejects_custom_actions_on_its_sweep_beat():
    """The sweep beat is compiler-owned; a hand-written role change on it
    either duplicates a compiler-emitted focus or slips a second focus into
    a slot the salience gate expects to hold one. Same discipline as
    `magnitude_comparison`.
    """
    plan_dict = _percent_of_whole_plan(value=30).model_dump()
    plan_dict["beats"][1]["custom_actions"] = [
        {"kind": "emphasize", "target": {"visual_ref": "percent_bar"}},
    ]

    with pytest.raises(ValueError, match="percent_of_whole's sweep beat"):
        TeachingPlanDocument.model_validate(plan_dict)


def test_magnitude_comparison_refused_on_a_percent_bar(compile_context):
    """A bar with maximum=100 is a percent bar by construction; using
    `magnitude_comparison` on it would teach "sweep 30 segments of 100"
    where the plan actually means "30 percent of the whole". The guard
    steers the plan to `percent_of_whole` at compile time.
    """
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Sweep a bar's magnitude.",
        "primary_visual": {
            "kind": "bar", "ref": "usage",
            "value": {"node": "literal", "value": 30},
            "maximum": {"node": "literal", "value": 100},
        },
        "strategy": "magnitude_comparison",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "usage"}],
             "intent": "show the bar"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "usage"}],
             "intent": "sweep to 30"},
            {"id": "state", "kind": "conclude", "targets": [{"visual_ref": "usage"}],
             "intent": "state 30"},
        ],
        "variation_seed": "percent-bar-magnitude",
    })

    with pytest.raises(
        V3ValidationError, match="magnitude_comparison_on_percent_bar",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=30), frozenset(), compile_context,
        )


def test_percent_change_sweeps_the_delta_on_the_after_bar(compile_context):
    """A $40 -> $50 (25% mark-up) plan sweeps segments [40..49] on the
    after-bar, not on the before-bar. The primary bar stays as the "before"
    reference frame while the after-bar shows the change accumulating.
    """
    plan = _percent_change_plan(before=40, after=50)

    program = compile_teaching_plan(
        plan, LiteralNode(value=50), frozenset(), compile_context,
    )

    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep_delta" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert [action.target.visual_ref for action in focus_actions] == ["after_bar"] * 10
    assert [action.target.part for action in focus_actions] == ["segment"] * 10
    assert [action.target.index for action in focus_actions] == list(range(40, 50))


def test_percent_change_direction_agnostic_walk(compile_context):
    """A discount ($50 -> $40) sweeps the same segments a mark-up ($40 -> $50)
    does: the delta's MAGNITUDE is what the strategy teaches, and both
    plans should animate segments [40..49] left-to-right on screen so the
    walk is legible in the same direction regardless of sign.
    """
    plan = _percent_change_plan(before=50, after=40)

    program = compile_teaching_plan(
        plan, LiteralNode(value=40), frozenset(), compile_context,
    )

    focus_indices = [
        entry.action.target.index for entry in program.timeline
        if entry.beat_id == "sweep_delta" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert focus_indices == list(range(40, 50))


def test_percent_change_requires_one_supporting_bar(compile_context):
    """A `percent_change` plan without an after-bar has nothing to compare
    against. Rejecting at compile time keeps the strategy from silently
    degrading to a single-bar magnitude walk.
    """
    plan_dict = _percent_change_plan(
        before=40, after=50,
        beats=[
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "before_bar"}],
             "intent": "show the before value"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "before_bar"}],
             "intent": "sweep"},
            {"id": "state", "kind": "conclude", "targets": [{"visual_ref": "before_bar"}],
             "intent": "state"},
        ],
    ).model_dump()
    plan_dict["supporting_visuals"] = []
    plan = TeachingPlanDocument.model_validate(plan_dict)

    with pytest.raises(
        V3ValidationError, match="percent_change_requires_one_supporting_bar",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=50), frozenset(), compile_context,
        )


def test_percent_change_requires_matching_maxima(compile_context):
    """The delta reads correctly only when the two bars share an axis:
    one segment on the before-bar has to be the same width and the same
    "one unit" as one segment on the after-bar, or the sweep is comparing
    two different scales.
    """
    plan_dict = _percent_change_plan(before=40, after=50, maximum=100).model_dump()
    plan_dict["supporting_visuals"][0]["maximum"] = {"node": "literal", "value": 80}
    plan = TeachingPlanDocument.model_validate(plan_dict)

    with pytest.raises(
        V3ValidationError, match="percent_change_requires_matching_maxima",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=50), frozenset(), compile_context,
        )


def test_percent_change_refuses_equal_before_and_after(compile_context):
    """No change is not what `percent_change` teaches. Two identical bars
    is the `group_reveal` shape, and the sweep would emit zero segments --
    the same shape the magnitude_comparison zero-value refusal targets.
    """
    plan = _percent_change_plan(before=40, after=40)

    with pytest.raises(
        V3ValidationError, match="percent_change_requires_distinct_values",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=40), frozenset(), compile_context,
        )


def test_percent_change_requires_a_sweep_beat_on_the_after_bar(compile_context):
    """The sweep colours segments on the after-bar, so the beat that owns
    the sweep has to name it. Requiring the sweep beat here matches
    `_require_owned_sweep_beat` for magnitude_comparison and lets the
    beat-expander safely pin one focus/derive beat.
    """
    plan = _percent_change_plan(
        before=40, after=50,
        beats=[
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "before_bar"}],
             "intent": "show the before value"},
            {"id": "reveal_after", "kind": "reveal", "targets": [{"visual_ref": "after_bar"}],
             "intent": "bring in the after value"},
            {"id": "focus_before", "kind": "focus", "targets": [{"visual_ref": "before_bar"}],
             "intent": "focus the before bar only"},
            {"id": "state_change", "kind": "conclude", "targets": [{"visual_ref": "after_bar"}],
             "intent": "state the percent change"},
        ],
    )

    with pytest.raises(
        V3ValidationError, match="percent_change_requires_sweep_beat",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=50), frozenset(), compile_context,
        )


def test_percent_change_thirty_of_sixty_acceptance_fixture(compile_context):
    """M9 acceptance: "30% of 60" approves as a percent-of-whole plan.

    "30% of 60" is authored as a percent-of-whole bar (30/100) plus a
    supporting label naming the "of 60" total; the answer expression is
    the literal 18. The compile side is what this test locks: the plan
    validates, the sweep lands on segments [0..29], and the answer
    resolves to 18.
    """
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Read 30% of a whole (60) as the part 18.",
        "primary_visual": {
            "kind": "bar", "ref": "thirty_percent",
            "value": {"node": "literal", "value": 30},
            "maximum": {"node": "literal", "value": 100},
        },
        "supporting_visuals": [
            {"kind": "label", "ref": "whole_label", "text": "of 60"},
        ],
        "strategy": "percent_of_whole",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient",
             "targets": [{"visual_ref": "thirty_percent"}, {"visual_ref": "whole_label"}],
             "intent": "show the percent bar and the whole label"},
            {"id": "sweep_part", "kind": "derive",
             "targets": [{"visual_ref": "thirty_percent"}],
             "intent": "sweep the 30 percent"},
            {"id": "state_answer", "kind": "conclude",
             "targets": [{"visual_ref": "thirty_percent"}],
             "intent": "state the value of the part"},
        ],
        "variation_seed": "thirty-of-sixty",
    })

    program = compile_teaching_plan(
        plan, LiteralNode(value=18), frozenset(), compile_context,
    )
    focus_indices = [
        entry.action.target.index for entry in program.timeline
        if entry.beat_id == "sweep_part" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert focus_indices == list(range(30))


def test_percent_change_markup_acceptance_fixture(compile_context):
    """M9 acceptance: "$40 marked up 25%" approves as a percent-change plan.

    The before-bar carries the $40, the after-bar carries the $50, and
    the delta sweep animates the $10 change segment-by-segment.
    """
    plan = _percent_change_plan(before=40, after=50)

    program = compile_teaching_plan(
        plan, LiteralNode(value=50), frozenset(), compile_context,
    )
    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep_delta" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert len(focus_actions) == 10
    assert all(action.target.visual_ref == "after_bar" for action in focus_actions)


def test_percent_change_emits_labeled_delta_ribbon(compile_context):
    """`percent_change` must stage a labelled Δ ribbon on the after-bar so
    the swept delta reads as the change the strategy names, not as an
    unlabelled recolour of arbitrary segments.
    """
    plan = _percent_change_plan(before=40, after=50)

    program = compile_teaching_plan(
        plan, LiteralNode(value=50), frozenset(), compile_context,
    )

    ribbon = next(
        (relation for relation in program.relations if relation.ref == "delta_ribbon"),
        None,
    )
    assert ribbon is not None, "percent_change must emit a Δ ribbon relation"
    assert ribbon.target.visual_ref == "after_bar"
    assert ribbon.target.part == "segment"
    # Midpoint of the delta range [40..49] is index 45.
    assert ribbon.target.index == 45
    assert "10" in ribbon.text and "Δ" in ribbon.text

    show_events = [
        entry for entry in program.timeline
        if entry.action.kind == "show_relation"
        and entry.action.relation_ref == "delta_ribbon"
    ]
    assert len(show_events) == 1, "the ribbon must be shown exactly once"
    assert show_events[0].beat_id == "sweep_delta", (
        "the ribbon should land on the sweep beat so it labels the change "
        "being animated"
    )


def test_percent_change_discount_ribbon_names_absolute_delta(compile_context):
    """A discount ($50 -> $40) and a mark-up ($40 -> $50) both sweep the
    same segments; the Δ ribbon reports the delta's absolute magnitude so
    the label is consistent with the walk.
    """
    plan = _percent_change_plan(before=50, after=40)

    program = compile_teaching_plan(
        plan, LiteralNode(value=40), frozenset(), compile_context,
    )

    ribbon = next(
        (relation for relation in program.relations if relation.ref == "delta_ribbon"),
        None,
    )
    assert ribbon is not None
    assert "10" in ribbon.text


def test_percent_of_whole_refuses_value_beyond_action_budget(compile_context):
    """A 50% sweep would emit 50 focus actions on its own, more than the
    40-action program cap. Reject at compile time with a strategy-specific
    error rather than letting the plan through to a downstream
    `too_many_timeline_actions` failure.
    """
    plan = _percent_of_whole_plan(value=50)

    with pytest.raises(
        V3ValidationError, match="percent_of_whole_sweep_over_budget",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=50), frozenset(), compile_context,
        )


def test_percent_change_refuses_delta_beyond_action_budget(compile_context):
    """A delta wider than the 30-segment budget would overrun the program
    cap once the sweep expands segment-by-segment. Reject at compile time.
    """
    plan = _percent_change_plan(before=10, after=45)

    with pytest.raises(
        V3ValidationError, match="percent_change_sweep_over_budget",
    ):
        compile_teaching_plan(
            plan, LiteralNode(value=45), frozenset(), compile_context,
        )


def test_percent_of_whole_resolves_a_lesson_that_fits_the_safe_frame(compile_context):
    """End-to-end acceptance: a 100-unit percent bar must reach a resolved
    scene that fits the safe frame. Rendered as a 100-cell horizontal row
    the bar measured 64.95 units wide and layout rejected it at
    `below_minimum_text_scale`, so no percent lesson could ever be
    rendered. The compact grid layout has to solve for a uniform scale of
    at least MIN_TEXT_SCALE with every visual inside the safe frame.
    """
    plan = _percent_of_whole_plan(value=30)

    program = compile_teaching_plan(
        plan, LiteralNode(value=30), frozenset(), compile_context,
    )

    scene = resolve_scene(program, {}, _LiteralTextMeasurer())

    bar = next(visual for visual in scene.visuals if visual.measured.ref == "percent_bar")
    assert bar.scale >= MIN_TEXT_SCALE
    assert SAFE_FRAME.left <= bar.bounds.left
    assert bar.bounds.right <= SAFE_FRAME.right
    assert SAFE_FRAME.bottom <= bar.bounds.bottom
    assert bar.bounds.top <= SAFE_FRAME.top
    assert len([part for part in bar.measured.parts if part[0] == "segment"]) == 100


def test_percent_change_ribbon_reserves_safe_frame_clearance(compile_context):
    """The Δ ribbon anchors `top` on the after-bar. Without the
    outer-callout reservation on supporting visuals, the ribbon's label
    would render past the safe frame's top edge and fail render-probe's
    `frame_out_of_bounds` check. Verify the layout reserves an envelope
    above the column when a top-anchored callout targets a non-primary
    visual.
    """
    plan = _percent_change_plan(before=40, after=50)

    program = compile_teaching_plan(
        plan, LiteralNode(value=50), frozenset(), compile_context,
    )

    scene = resolve_scene(program, {}, _LiteralTextMeasurer())

    ribbon = next(relation for relation in scene.relations if relation.ref == "delta_ribbon")
    assert ribbon.anchor == "top"
    assert ribbon.target.y + CALLOUT_ENVELOPE <= SAFE_FRAME.top + 1e-9, (
        "the anchor's callout envelope must land inside the safe frame"
    )
    for visual in scene.visuals:
        assert visual.bounds.top <= SAFE_FRAME.top
        assert visual.bounds.bottom >= SAFE_FRAME.bottom
