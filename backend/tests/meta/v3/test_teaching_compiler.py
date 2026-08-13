from copy import deepcopy

import pytest

from app.meta.dsl.expression import (
    AddNode, DivideNode, FieldRefNode, LiteralNode, MultiplyNode, SubtractNode,
)
from app.meta.dsl.scene_program import (
    DrawAction, MoveAction, RevealAction, SetRoleAction, TransformAction,
)
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext, TargetRef
from app.meta.v3.beat_expander import ExpandedBeat
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.timeline import schedule_beats


def _field(name):
    return {"node": "field_ref", "field": name}


@pytest.fixture
def compile_context():
    return CompileContext(concept_family="measurement", grade_band="3-5")


@pytest.fixture
def median_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values",
            "ref": "values",
            "values": [_field(f"v{i}") for i in range(1, 8)],
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


@pytest.fixture
def perimeter_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement",
            "ref": "rectangle",
            "length": _field("length"),
            "width": _field("width"),
            "unit": "cm",
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


@pytest.fixture
def published_perimeter_plan():
    """The shape of the `perimeter` plan actually published to the demo database.

    Two beats name the rectangle, the `organize` beat names a supporting label
    instead of the rectangle, the `reveal` beat declares its own perimeter
    trace, and the `conclude` beat names a second label. Every one of those is
    legal per the plan schema, and each exposed a distinct expander defect.
    """
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find the perimeter of a rectangle by doubling the sum of its sides.",
        "primary_visual": {
            "kind": "rectangle_measurement",
            "ref": "rect",
            "length": _field("length"),
            "width": _field("width"),
            "unit": "cm",
        },
        "supporting_visuals": [
            {"kind": "label", "ref": "formula_label", "text": "P = 2 x (length + width)"},
            {"kind": "label", "ref": "answer_label", "text": "Perimeter = 2 x (l + w)"},
        ],
        "strategy": "boundary_trace",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "rect"}],
             "intent": "show the rectangle with both dimensions"},
            {"id": "reveal_perimeter", "kind": "reveal", "targets": [{"visual_ref": "rect"}],
             "intent": "trace the boundary to show what perimeter means",
             "custom_actions": [{"kind": "trace", "path_ref": "rect.perimeter"}]},
            {"id": "organize", "kind": "organize", "targets": [{"visual_ref": "formula_label"}],
             "intent": "introduce the perimeter formula"},
            {"id": "derive", "kind": "derive",
             "targets": [{"visual_ref": "rect"}, {"visual_ref": "formula_label"}],
             "intent": "substitute the given length and width into the formula"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "answer_label"}],
             "intent": "state the final perimeter"},
        ],
        "variation_seed": "published-perimeter",
    })


@pytest.fixture
def perimeter_answer():
    return MultiplyNode(operands=[
        LiteralNode(value=2),
        AddNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
    ])


def _reveals_of(program, visual_ref):
    return [
        entry for entry in program.timeline
        if entry.action.kind == "reveal"
        and any(target.visual_ref == visual_ref for target in entry.action.targets)
    ]


@pytest.fixture
def answer():
    return FieldRefNode(field="v4")


def test_median_compiles_group_reveal_then_focus_then_conclusion(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan,
        answer,
        frozenset({f"v{i}" for i in range(1, 8)}),
        compile_context,
    )

    actions = [entry.action for entry in program.timeline]
    assert actions[0].model_dump() == {
        "kind": "reveal",
        "targets": [{"visual_ref": "values", "part": None, "index": None}],
        "mode": "together",
        "stagger_seconds": 0.0,
    }
    focus_index = next(
        index for index, action in enumerate(actions)
        if action.kind == "set_role" and action.role == "focus"
    )
    conclusion_index = next(
        index for index, action in enumerate(actions)
        if action.kind == "show_relation" and action.relation_ref == "median_callout"
    )
    assert focus_index < conclusion_index
    # Total-duration bounds are enforced by `SceneProgramDocument`
    # (Field(ge=MIN_SCENE_SECONDS, le=MAX_SCENE_SECONDS)), so a valid return
    # already satisfies them; the scheduler raises `timeline_over_budget`
    # before that when it cannot fit.


def test_pair_elimination_rejects_an_answer_that_is_not_the_middle_value(
    median_plan, compile_context,
):
    with pytest.raises(V3ValidationError, match="pair_elimination_answer_must_be_middle_value"):
        compile_teaching_plan(
            median_plan, FieldRefNode(field="v1"),
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )


def test_pair_elimination_program_names_the_median_as_its_answer_anchor(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    assert program.answer_anchor.model_dump() == {
        "visual_ref": "values", "part": "item", "index": 3,
    }


def test_pair_elimination_values_are_born_structure(median_plan, answer, compile_context):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    values, = [visual for visual in program.visuals if visual.ref == "values"]
    assert values.initial_role == "structure"


def test_other_strategies_leave_ordered_values_neutral(median_plan, answer, compile_context):
    raw = median_plan.model_dump()
    raw["strategy"] = "short_stagger"
    program = compile_teaching_plan(
        TeachingPlanDocument.model_validate(raw), answer,
        frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    values, = [visual for visual in program.visuals if visual.ref == "values"]
    assert values.initial_role == "neutral"


def test_other_strategies_declare_no_answer_anchor(perimeter_plan, compile_context):
    program = compile_teaching_plan(
        perimeter_plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        compile_context,
    )
    assert program.answer_anchor is None


def test_perimeter_compiles_trace_before_answer(perimeter_plan, compile_context):
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])
    program = compile_teaching_plan(
        perimeter_plan,
        answer,
        frozenset({"length", "width"}),
        compile_context,
    )

    trace = next(index for index, entry in enumerate(program.timeline) if entry.action.kind == "trace")
    # The unresolved answer's own reveal is now the first thing on the
    # timeline, ahead of the trace, so ordering the trace against IT no longer
    # says anything about the boundary being taught before the answer is
    # given. What still must hold is that the trace precedes the RESOLVED
    # value, at conclude.
    value_index = next(
        index for index, entry in enumerate(program.timeline)
        if entry.action.kind == "show_answer_stage" and entry.action.stage == "value"
    )
    assert trace < value_index
    assert program.timeline[trace].action.path_ref == "rectangle.perimeter"


def test_boundary_trace_rejects_a_structural_supporting_visual(
    perimeter_plan, perimeter_answer, compile_context,
):
    """The perimeter's derivation IS the traced boundary on the rectangle.

    A second structural companion (e.g. a `number_line` beside the rectangle)
    displaces the rectangle downward and invites off-lesson callouts anchored
    to a scale the lesson never uses, so it is refused at compile time. The
    published perimeter plan carries label supporting_visuals for a formula
    caption, and those stay legal.
    """
    raw = perimeter_plan.model_dump()
    raw["supporting_visuals"] = [{
        "kind": "number_line", "ref": "nl",
        "minimum": {"node": "literal", "value": 0.0},
        "maximum": {"node": "literal", "value": 20.0},
        "markers": [{"node": "literal", "value": 0.0}],
    }]
    plan = TeachingPlanDocument.model_validate(raw)

    with pytest.raises(V3ValidationError, match="boundary_trace_forbids_foreign_structure_supporting_visual"):
        compile_teaching_plan(
            plan, perimeter_answer,
            frozenset({"length", "width"}), compile_context,
        )


def test_a_visual_named_by_two_beats_is_revealed_once(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    assert len(_reveals_of(program, "rect")) == 1


def test_a_beat_reveals_the_target_it_names(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    """The `organize` beat names `formula_label`, so compiling must reveal it.

    The expander's `boundary_trace` branch replaced the beat's own actions with
    a perimeter trace, so the label the beat named got no action at all and only
    became visible as a side effect of a later `set_role` -- appearing abruptly,
    with no fade, four seconds in.
    """
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    reveals = _reveals_of(program, "formula_label")
    assert len(reveals) == 1
    assert reveals[0].beat_id == "organize"


def test_boundary_trace_does_not_duplicate_a_trace_the_plan_declares(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    traces = [entry for entry in program.timeline if entry.action.kind == "trace"]
    assert [entry.action.path_ref for entry in traces] == ["rect.perimeter"]


def test_a_beat_does_not_restate_a_role_the_target_already_holds(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    """Every `set_role` must actually change the target's role.

    The renderer plays each one as a colour `Transform`, so re-asserting a role
    the target already holds animates a recolour from a colour to itself -- a
    visible mid-lesson flicker that teaches nothing. The rectangle starts
    `structure`, and `derive` used to re-assert `structure` on it.
    """
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    role = next(
        visual.initial_role for visual in program.visuals if visual.ref == "rect"
    )
    for entry in program.timeline:
        if entry.action.kind != "set_role" or entry.action.target.visual_ref != "rect":
            continue
        assert entry.action.role != role, (
            f"beat {entry.beat_id} restates role {role!r} the rectangle already holds"
        )
        role = entry.action.role


def test_every_beat_produces_an_observable_state_change(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    """`docs/meta-template-dsl-v3-design.md`: "every beat produces an observable
    state change".

    `derive` used to fall through to `set_role ... "structure"` on targets that
    already held `structure`, so the beat's whole allocation was a recolour from
    a colour to itself. Suppressing that no-op leaves the beat empty, which is
    idle time the spec forbids -- the beat needs a real state change, and the
    spec permits `focus` during `derive`.
    """
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    assert {entry.beat_id for entry in program.timeline} == {
        beat.id for beat in published_perimeter_plan.beats
    }


def test_pair_elimination_dims_pairs_outside_in_before_focusing_the_middle(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    dimmed = [
        entry for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "neutral"
    ]
    assert [entry.action.target.index for entry in dimmed] == [0, 6, 1, 5, 2, 4]

    focus, = [
        entry for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    ]
    assert focus.action.target.index == 3
    assert all(entry.at_seconds < focus.at_seconds for entry in dimmed)


def test_pair_elimination_dims_both_partners_at_one_instant(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    by_start = {}
    for entry in program.timeline:
        if entry.action.kind == "set_role" and entry.action.role == "neutral":
            by_start.setdefault(entry.at_seconds, []).append(entry.action.target.index)

    assert sorted(sorted(pair) for pair in by_start.values()) == [[0, 6], [1, 5], [2, 4]]


def test_each_pair_step_is_long_enough_to_read(median_plan, answer, compile_context):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    dimmed = [
        entry for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "neutral"
    ]
    assert all(entry.duration_seconds >= 1.3 for entry in dimmed)


def test_a_fifteen_value_elimination_still_fits_the_scene_budget(answer, compile_context):
    raw = {
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [_field(f"v{i}") for i in range(1, 16)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 7}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 7}],
             "intent": "state the median"},
        ],
        "variation_seed": "median-fifteen",
    }
    program = compile_teaching_plan(
        TeachingPlanDocument.model_validate(raw), FieldRefNode(field="v8"),
        frozenset({f"v{i}" for i in range(1, 16)}), compile_context,
    )
    # Successful return means SceneProgramDocument's bounds
    # (ge=MIN_SCENE_SECONDS, le=MAX_SCENE_SECONDS) already accepted the total;
    # what this test asserts specifically is that 15 values still compile.
    assert program.timeline, "15-value plan must produce a timeline"


def test_pair_elimination_declares_no_answer_card(median_plan, answer, compile_context):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    assert not [visual for visual in program.visuals if visual.ref == "evaluated_answer"]


def test_the_conclusion_names_the_median_and_recolours_nothing(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    conclusion = [entry for entry in program.timeline if entry.beat_id == "show_answer"]

    assert [entry.action.kind for entry in conclusion] == ["show_relation"]
    assert conclusion[0].action.relation_ref == "median_callout"
    assert conclusion[0].duration_seconds >= 1.5


def test_a_multi_action_conclusion_co_starts_its_actions_and_holds_the_floor(
    median_plan, answer, compile_context,
):
    """The conclusion holds everything it does at one instant, card or no card.

    This used to fall out of the answer card: `timeline.schedule_beats` forced a
    single slot for any beat containing a `reveal` of `evaluated_answer`. A
    `pair_elimination` lesson declares no such card, so a conclusion with more
    than one action was split into sequential slots of `beat_seconds / N` -- two
    actions here held 0.9868s each -- while `quality.check_conclusion_hold`
    requires EVERY final-beat action to clear `MIN_CONCLUSION_HOLD_SECONDS`
    individually. `schedule_beats` now keys the single slot on the last beat that
    acts, which is the same beat that check reads off `timeline[-1].beat_id`.
    """
    raw = median_plan.model_dump()
    raw["beats"][3]["custom_actions"] = [{
        "kind": "callout",
        "target": {"visual_ref": "values", "part": "item", "index": 0, "anchor": "bottom"},
        "text": "eliminated",
    }]
    program = compile_teaching_plan(
        TeachingPlanDocument.model_validate(raw), answer,
        frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    conclusion = [entry for entry in program.timeline if entry.beat_id == "show_answer"]

    assert len(conclusion) == 2, "this plan must compile to a multi-action conclusion"
    assert {entry.at_seconds for entry in conclusion} == {conclusion[0].at_seconds}
    assert all(entry.duration_seconds >= 1.5 for entry in conclusion)


def test_a_plan_supplied_callout_replaces_the_generated_one(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["beats"][3]["custom_actions"] = [{
        "kind": "callout",
        "target": {"visual_ref": "values", "part": "item", "index": 3, "anchor": "bottom"},
        "text": "This is the median - the middle value!",
    }]
    program = compile_teaching_plan(
        TeachingPlanDocument.model_validate(raw), answer,
        frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    assert [relation.text for relation in program.relations] == [
        "This is the median - the middle value!",
    ]


def test_the_conclusion_creates_an_item_specific_median_callout(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    assert [relation.model_dump() for relation in program.relations] == [{
        "kind": "callout",
        "ref": "median_callout",
        "target": {"visual_ref": "values", "part": "item", "index": 3, "anchor": "bottom"},
        "text": "median",
    }]


def test_answer_visual_is_revealed_once_in_the_first_beat(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    answer_entries = [
        entry for entry in program.timeline
        if entry.action.kind == "reveal" and entry.action.targets[0].visual_ref == "evaluated_answer"
    ]
    assert len(answer_entries) == 1
    assert answer_entries[0].beat_id == published_perimeter_plan.beats[0].id


def test_conclusion_reveal_and_role_hold_together_for_at_least_one_and_a_half_seconds(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    """The label's reveal, the resolved value, and the `conclusion` recolour
    must land together.

    The answer itself is no longer revealed here -- that happens in the first
    beat -- but this plan's own `conclude` beat still names `answer_label`, a
    supporting visual, so its reveal remains one of the actions that must
    co-start with the value resolving and the role change.

    Asserted on a lesson that still draws an answer card: `pair_elimination`
    names one of the collection's own values instead, so its conclusion is a
    single `show_relation` with nothing to co-ordinate (see
    `test_the_conclusion_names_the_median_and_recolours_nothing`).
    """
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )
    conclusion_entries = [entry for entry in program.timeline if entry.beat_id == "conclude"]

    assert {entry.action.kind for entry in conclusion_entries} == {
        "reveal", "show_answer_stage", "set_role",
    }
    assert {entry.at_seconds for entry in conclusion_entries} == {conclusion_entries[0].at_seconds}
    assert all(entry.duration_seconds >= 1.5 for entry in conclusion_entries)


def test_custom_actions_lower_to_typed_program_actions_and_restore_prior_role(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["strategy"] = "short_stagger"
    raw["beats"][2]["custom_actions"] = [
        {"kind": "dim", "target": {"visual_ref": "values", "part": "item", "index": 3}},
        {"kind": "restore", "target": {"visual_ref": "values", "part": "item", "index": 3}},
        {"kind": "callout", "target": {
            "visual_ref": "values", "part": "item", "index": 3, "anchor": "bottom",
        }, "text": "middle value"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)

    program = compile_teaching_plan(
        plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    actions = [entry.action for entry in program.timeline if entry.beat_id == "focus_middle"]

    role_actions = [action for action in actions if action.kind == "set_role"]
    assert [(action.kind, action.role) for action in role_actions[:3]] == [
        ("set_role", "focus"), ("set_role", "neutral"), ("set_role", "focus"),
    ]
    assert actions[-1].kind == "show_relation"
    assert program.relations[-1].target.anchor == "bottom"


def test_nested_dim_restores_the_role_before_the_first_dim(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["strategy"] = "short_stagger"
    raw["beats"][2]["custom_actions"] = [
        {"kind": "dim", "target": {"visual_ref": "values", "part": "item", "index": 3}},
        {"kind": "dim", "target": {"visual_ref": "values", "part": "item", "index": 3}},
        {"kind": "restore", "target": {"visual_ref": "values", "part": "item", "index": 3}},
    ]
    program = compile_teaching_plan(
        TeachingPlanDocument.model_validate(raw), answer,
        frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )
    roles = [
        action.role for entry in program.timeline if entry.beat_id == "focus_middle"
        for action in [entry.action] if action.kind == "set_role" and action.target.index == 3
    ]

    assert roles == ["focus", "neutral", "neutral", "focus"]


def test_custom_item_callout_requires_the_declared_bottom_anchor(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["beats"][2]["custom_actions"] = [{
        "kind": "callout",
        "target": {"visual_ref": "values", "part": "item", "index": 3, "anchor": "top"},
        "text": "middle value",
    }]

    with pytest.raises(V3ValidationError, match="incompatible_callout_anchor"):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )


def test_compiler_rejects_unknown_visual_and_out_of_range_item_targets(
    median_plan, answer, compile_context,
):
    unknown = median_plan.model_dump()
    unknown["beats"][0]["targets"] = [{"visual_ref": "missing"}]
    with pytest.raises(V3ValidationError, match="unknown_visual_ref"):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(unknown), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    out_of_range = median_plan.model_dump()
    out_of_range["strategy"] = "short_stagger"
    out_of_range["beats"][2]["targets"][0]["index"] = 7
    with pytest.raises(V3ValidationError, match="target_index_out_of_range"):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(out_of_range), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )


def test_compiler_rejects_duplicate_refs_and_incompatible_strategy(
    median_plan, answer, compile_context,
):
    duplicate = median_plan.model_dump()
    duplicate["supporting_visuals"] = [deepcopy(duplicate["primary_visual"])]
    with pytest.raises(V3ValidationError, match="duplicate_visual_ref"):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(duplicate), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    incompatible = median_plan.model_dump()
    incompatible["primary_visual"] = {
        "kind": "rectangle_measurement", "ref": "rectangle",
        "length": _field("length"), "width": _field("width"), "unit": "cm",
    }
    incompatible["beats"] = [
        {**beat, "targets": [{"visual_ref": "rectangle"}]}
        for beat in incompatible["beats"]
    ]
    with pytest.raises(V3ValidationError, match="incompatible_strategy"):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(incompatible), FieldRefNode(field="length"),
            frozenset({"length", "width"}), compile_context,
        )


def test_style_recipe_is_deterministic(median_plan, answer, compile_context):
    known_fields = frozenset({f"v{i}" for i in range(1, 8)})
    first = compile_teaching_plan(median_plan, answer, known_fields, compile_context)
    second = compile_teaching_plan(median_plan, answer, known_fields, compile_context)

    assert first.style_recipe == second.style_recipe


def test_style_recipe_varies_when_the_variation_seed_changes(
    median_plan, answer, compile_context,
):
    """Determinism is only interesting if the hash is actually consumed.
    `resolve_style_recipe` derives BOTH palette (from `digest[0] % 3`) and
    motion (from `digest[1] % 2`) off the same sha256 of the joined key, so
    a compiler that stopped feeding `variation_seed` through would freeze
    palette AND motion at once. Assert each field takes more than one value
    across a seed sweep -- an OR would let a bug that pins the palette but
    varies motion (or vice versa) go undetected.
    """
    known_fields = frozenset({f"v{i}" for i in range(1, 8)})
    recipes = []
    for seed in (
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta",
        "eta", "theta", "iota", "kappa", "lambda", "mu",
    ):
        raw = median_plan.model_dump()
        raw["variation_seed"] = seed
        plan = TeachingPlanDocument.model_validate(raw)
        recipes.append(
            compile_teaching_plan(plan, answer, known_fields, compile_context).style_recipe,
        )

    palettes = {recipe.palette for recipe in recipes}
    motions = {recipe.motion_variant for recipe in recipes}
    assert len(palettes) > 1, (
        f"palette should vary with variation_seed; got only {palettes!r}"
    )
    assert len(motions) > 1, (
        f"motion_variant should vary with variation_seed; got only {motions!r}"
    )


def test_bounded_custom_draw_transform_and_move_actions_are_preserved(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["supporting_visuals"] = [{
        "kind": "rectangle_measurement", "ref": "comparison",
        "length": _field("length"), "width": _field("width"), "unit": "cm",
    }]
    raw["beats"][1]["custom_actions"] = [
        {"kind": "draw", "target": {"visual_ref": "rectangle"}},
        {"kind": "transform", "source": {"visual_ref": "rectangle"},
         "target": {"visual_ref": "comparison"}},
        {"kind": "move", "target": {"visual_ref": "rectangle"},
         "path_ref": "rectangle.perimeter"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    program = compile_teaching_plan(
        plan, answer, frozenset({"length", "width"}), compile_context,
    )
    actions = [entry.action for entry in program.timeline if entry.beat_id == "trace_boundary"]

    assert any(isinstance(action, DrawAction) for action in actions)
    assert any(isinstance(action, TransformAction) for action in actions)
    assert any(isinstance(action, MoveAction) for action in actions)


@pytest.mark.parametrize(
    ("action_request", "error"),
    [
        ({"kind": "draw", "target": {"visual_ref": "values"}}, "incompatible_draw_target"),
        ({"kind": "move", "target": {"visual_ref": "rectangle", "part": "edge", "index": 0},
          "path_ref": "rectangle.perimeter"}, "incompatible_move_target"),
    ],
)
def test_custom_draw_and_move_reject_incompatible_visual_targets(
    action_request, error, median_plan, perimeter_plan, answer, compile_context,
):
    if action_request["kind"] == "draw":
        raw = median_plan.model_dump()
        # short_stagger, not pair_elimination: the organize beat under test rejects
        # every custom action for pair_elimination now, and this test's subject
        # (draw/target compatibility) is strategy-independent.
        raw["strategy"] = "short_stagger"
        known_fields, expression = frozenset({f"v{i}" for i in range(1, 8)}), answer
    else:
        raw = perimeter_plan.model_dump()
        known_fields = frozenset({"length", "width"})
        expression = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])
    raw["beats"][1]["custom_actions"] = [action_request]

    with pytest.raises(V3ValidationError, match=error):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), expression, known_fields, compile_context,
        )


def test_custom_transform_rejects_semantic_part_targets(perimeter_plan, compile_context):
    raw = perimeter_plan.model_dump()
    raw["supporting_visuals"] = [{
        "kind": "rectangle_measurement", "ref": "comparison",
        "length": _field("length"), "width": _field("width"), "unit": "cm",
    }]
    raw["beats"][1]["custom_actions"] = [{
        "kind": "transform", "source": {"visual_ref": "rectangle", "part": "edge", "index": 0},
        "target": {"visual_ref": "comparison"},
    }]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError, match="incompatible_transform_target"):
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )


def test_scheduler_batches_dense_same_beat_actions_without_exceeding_budget():
    actions = [
        SetRoleAction(target=TargetRef(visual_ref="values"), role="focus")
        for _ in range(50)
    ]
    timeline, total = schedule_beats([
        ExpandedBeat(beat_id="dense", actions=actions, minimum_seconds=0.15, weight=1.0),
        # A trailing beat, so `dense` is not the conclusion. The conclusion holds
        # all its actions at one instant by design, which would collapse the dense
        # beat to a single batch and make the batching under test here vacuous.
        ExpandedBeat(
            beat_id="conclude",
            actions=[SetRoleAction(target=TargetRef(visual_ref="values"), role="conclusion")],
            minimum_seconds=1.5,
            weight=1.5,
        ),
    ])

    dense = [entry for entry in timeline if entry.beat_id == "dense"]
    starts = {entry.at_seconds for entry in dense}
    assert 1 < len(starts) < len(dense)
    assert all(entry.at_seconds + entry.duration_seconds <= total for entry in timeline)


def test_scheduler_rejects_minimum_timeline_that_exceeds_twenty_four_seconds():
    beats = [
        ExpandedBeat(
            beat_id=f"organize_{index}",
            actions=[SetRoleAction(target=TargetRef(visual_ref="values"), role="structure")],
            minimum_seconds=2.5,
            weight=1.0,
        )
        for index in range(9)
    ]
    beats.append(ExpandedBeat(
        beat_id="conclude",
        actions=[RevealAction(targets=[TargetRef(visual_ref="evaluated_answer")], mode="together")],
        minimum_seconds=3.0,
        weight=1.5,
    ))

    with pytest.raises(V3ValidationError, match="timeline_over_budget"):
        schedule_beats(beats)


def test_timeline_entries_fit_the_declared_total_duration(median_plan, answer, compile_context):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    assert all(
        entry.duration_seconds >= 0.3
        and entry.duration_seconds <= 4
        and entry.at_seconds + entry.duration_seconds <= program.total_duration_seconds
        for entry in program.timeline
    )


def test_unknown_semantic_part_hint_names_every_legal_part(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["beats"][2]["targets"] = [{"visual_ref": "rectangle", "part": "top", "index": 0}]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "unknown_semantic_part"
    assert failure.hint == (
        "choose a declared semantic part: edge, length_edge, vertex, width_edge"
    )


def test_unknown_semantic_part_hint_says_so_when_the_visual_exposes_none(
    compile_context,
):
    raw = {
        "plan_version": 3,
        "learning_objective": "A label exposes no semantic parts.",
        "primary_visual": {"kind": "label", "ref": "caption", "text": "hello"},
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal_caption", "kind": "reveal",
             "targets": [{"visual_ref": "caption"}], "intent": "show the caption"},
            {"id": "focus_caption", "kind": "focus",
             "targets": [{"visual_ref": "caption", "part": "text", "index": 0}],
             "intent": "point at the caption text"},
            {"id": "state_answer", "kind": "conclude",
             "targets": [{"visual_ref": "caption"}], "intent": "state the answer"},
        ],
        "variation_seed": "label-parts",
    }

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), FieldRefNode(field="value"),
            frozenset({"value"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "unknown_semantic_part"
    assert failure.hint == "this visual exposes no semantic parts"


def test_incompatible_strategy_hint_names_the_strategies_the_kind_supports(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["strategy"] = "boundary_trace"

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "incompatible_strategy"
    assert failure.hint == (
        "select a compatible strategy: group_reveal, pair_elimination, short_stagger"
    )


def test_unknown_visual_ref_hint_names_the_declared_visuals(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["supporting_visuals"] = [{"kind": "label", "ref": "caption", "text": "middle"}]
    raw["beats"][0]["targets"] = [{"visual_ref": "missing"}]

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "unknown_visual_ref"
    assert failure.hint == (
        "reference the primary or a supporting visual: caption, values"
    )


def test_unknown_declared_path_hint_names_the_declared_paths(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["beats"][1]["custom_actions"] = [
        {"kind": "trace", "path_ref": "rectangle.diagonal"}
    ]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "unknown_declared_path"
    assert failure.hint == "use a declared semantic path: perimeter"


def test_invalid_path_ref_hint_names_the_declared_paths(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["beats"][1]["custom_actions"] = [
        {"kind": "trace", "path_ref": "rectangle.length_edge.0"}
    ]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "invalid_path_ref"
    assert failure.hint == "use the form visual_ref.path_name: perimeter"


def test_invalid_path_ref_hint_falls_back_when_the_visual_ref_is_unresolved(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["beats"][1]["custom_actions"] = [
        {"kind": "trace", "path_ref": "missing.length_edge.0"}
    ]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "invalid_path_ref"
    assert failure.hint == "use the form visual_ref.path_name"


def test_unknown_declared_path_hint_says_so_when_the_visual_declares_none(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    # short_stagger, not pair_elimination: the organize beat under test rejects
    # every custom action for pair_elimination now, and this test's subject
    # (declared-path hints) is strategy-independent.
    raw["strategy"] = "short_stagger"
    raw["beats"][1]["custom_actions"] = [
        {"kind": "trace", "path_ref": "values.outline"}
    ]

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "unknown_declared_path"
    assert failure.hint == "this visual exposes no semantic paths"


def test_unknown_visual_ref_hint_names_the_declared_visuals_from_a_path_ref(
    perimeter_plan, compile_context,
):
    # `_validate_path_ref` raises unknown_visual_ref independently of
    # `_validate_target` -- the visual_ref prefix of a path_ref string, not a
    # beat or custom-action target. Task 4 enumerated the target-ref site;
    # this pins the path-ref site to the same treatment.
    raw = perimeter_plan.model_dump()
    raw["beats"][1]["custom_actions"] = [
        {"kind": "trace", "path_ref": "missing.perimeter"}
    ]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "unknown_visual_ref"
    assert failure.hint == "reference the primary or a supporting visual: rectangle"


def test_incompatible_transform_hint_names_the_compatible_kinds(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["supporting_visuals"] = [{"kind": "label", "ref": "caption", "text": "same area"}]
    raw["beats"][1]["custom_actions"] = [{
        "kind": "transform",
        "source": {"visual_ref": "rectangle"},
        "target": {"visual_ref": "caption"},
    }]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "incompatible_transform_target"
    assert failure.hint == (
        "transform between whole visuals of a compatible kind: rectangle_measurement"
    )


def test_incompatible_transform_hint_says_so_when_the_source_kind_cannot_transform(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    # short_stagger, not pair_elimination: the organize beat under test rejects
    # every custom action for pair_elimination now, and this test's subject
    # (transform target compatibility) is strategy-independent.
    raw["strategy"] = "short_stagger"
    raw["supporting_visuals"] = [{"kind": "label", "ref": "caption", "text": "median callout"}]
    raw["beats"][1]["custom_actions"] = [{
        "kind": "transform",
        "source": {"visual_ref": "values"},
        "target": {"visual_ref": "caption"},
    }]

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "incompatible_transform_target"
    assert failure.hint == "this visual kind cannot be transformed"


def test_incompatible_callout_anchor_hint_names_the_permitted_anchors(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    raw["beats"][2]["custom_actions"] = [{
        "kind": "callout",
        "target": {"visual_ref": "values", "part": "item", "index": 3, "anchor": "top"},
        "text": "middle value",
    }]

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "incompatible_callout_anchor"
    assert failure.hint == "attach item callouts to a permitted anchor: bottom"


def test_incompatible_draw_hint_names_the_drawable_kinds(
    median_plan, answer, compile_context,
):
    raw = median_plan.model_dump()
    # short_stagger, not pair_elimination: the organize beat under test rejects
    # every custom action for pair_elimination now, and this test's subject
    # (draw target compatibility) is strategy-independent.
    raw["strategy"] = "short_stagger"
    raw["beats"][1]["custom_actions"] = [
        {"kind": "draw", "target": {"visual_ref": "values"}}
    ]

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "incompatible_draw_target"
    assert failure.hint == (
        "draw a whole visual of a drawable kind: rectangle_measurement"
    )


def test_incompatible_move_hint_names_the_movable_kinds(
    perimeter_plan, compile_context,
):
    raw = perimeter_plan.model_dump()
    raw["beats"][1]["custom_actions"] = [{
        "kind": "move",
        "target": {"visual_ref": "rectangle", "part": "edge", "index": 0},
        "path_ref": "rectangle.perimeter",
    }]
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(
            TeachingPlanDocument.model_validate(raw), answer,
            frozenset({"length", "width"}), compile_context,
        )

    failure = exc_info.value.failure
    assert failure.code == "incompatible_move_target"
    assert failure.hint == (
        "move a whole visual of a movable kind: rectangle_measurement"
    )


def _reveal_parts_of_a_revealed_whole_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Read the endpoints of a number line.",
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": {"node": "literal", "value": 0},
            "maximum": {"node": "literal", "value": 10},
            "markers": [_field("a"), _field("b")],
        },
        "strategy": "group_reveal",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "line"}],
             "intent": "show the number line"},
            {"id": "reveal_ends", "kind": "reveal", "targets": [
                {"visual_ref": "line", "part": "marker", "index": 0},
                {"visual_ref": "line", "part": "marker", "index": 1},
            ], "intent": "point out the two endpoints"},
            {"id": "derive", "kind": "derive", "targets": [{"visual_ref": "line"}],
             "intent": "measure the distance between them"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "line"}],
             "intent": "state the distance"},
        ],
        "variation_seed": "reveal-ends",
    })


def test_a_beat_naming_parts_already_on_screen_emphasizes_them(compile_context):
    """A part of a revealed visual is already visible, so revealing it again is a
    no-op -- but the beat still has to teach something.

    `_line_visual` puts the marker dots inside the group the reveal fades in, so
    `FadeIn` on one of them changes nothing. Suppressing that left the beat with
    no actions at all, and a plan whose second beat says "now point out the
    endpoints" -- entirely reasonable -- was rejected as `beat_without_action`.
    """
    plan = _reveal_parts_of_a_revealed_whole_plan()
    program = compile_teaching_plan(
        plan, FieldRefNode(field="a"), frozenset({"a", "b"}), compile_context,
    )

    beat_actions = [entry for entry in program.timeline if entry.beat_id == "reveal_ends"]
    assert [entry.action.kind for entry in beat_actions] == ["set_role", "set_role"]
    assert {entry.action.role for entry in beat_actions} == {"focus"}
    assert {entry.action.target.index for entry in beat_actions} == {0, 1}


def test_an_organize_beat_on_an_already_structural_visual_still_acts(compile_context):
    """`organize` defaults to the `structure` role, which a grid already holds."""
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "See multiplication as equal rows.",
        "primary_visual": {
            "kind": "grid", "ref": "array",
            "rows": {"node": "literal", "value": 3},
            "columns": {"node": "literal", "value": 4},
        },
        "strategy": "group_reveal",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "array"}],
             "intent": "show the array"},
            {"id": "focus_cell", "kind": "focus",
             "targets": [{"visual_ref": "array", "part": "cell", "index": 0}],
             "intent": "look at a single cell"},
            {"id": "organize_multiplication", "kind": "organize",
             "targets": [{"visual_ref": "array"}],
             "intent": "group the array into equal rows"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "array"}],
             "intent": "state the product"},
        ],
        "variation_seed": "organize-grid",
    })

    program = compile_teaching_plan(
        plan, FieldRefNode(field="a"), frozenset({"a"}), compile_context,
    )

    assert {entry.beat_id for entry in program.timeline} == {beat.id for beat in plan.beats}


def _plan_with_custom_reveals(custom_actions):
    # short_stagger, not pair_elimination: this fixture puts custom actions on
    # the organize beat, which pair_elimination now rejects outright (its
    # organize beat is staged entirely by the compiler). The reveal-tracking
    # behaviour under test here is strategy-independent.
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [_field(f"v{i}") for i in range(1, 8)],
        },
        "strategy": "short_stagger",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward",
             "custom_actions": custom_actions},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "custom-reveal-tracking",
    })


@pytest.mark.parametrize("target", [
    {"visual_ref": "values", "part": "item", "index": 3},
    {"visual_ref": "values"},
])
def test_a_custom_reveal_of_something_already_on_screen_emits_nothing(
    target, answer, compile_context,
):
    """Custom reveals must share the expander's revealed-set.

    `_custom_actions` returned a `RevealAction` unconditionally, so an author's
    `reveal` re-faded a mobject the first beat had already faded in. For a PART
    that also slipped past `check_repeated_reveal`, which compared whole and part
    keys as if they were unrelated -- yet the item is a child of the group the
    whole reveal brought on screen, so fading it again is a visible flicker.
    """
    plan = _plan_with_custom_reveals([{"kind": "reveal", "targets": [target]}])

    program = compile_teaching_plan(
        plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    reveals = [
        entry for entry in program.timeline
        if entry.action.kind == "reveal" and entry.beat_id == "organize_pairs"
    ]
    assert reveals == []


def test_a_custom_reveal_of_an_unrevealed_visual_still_reveals_it(answer, compile_context):
    """Regression guard: tracking must not swallow a reveal that is doing work."""
    raw = _plan_with_custom_reveals([]).model_dump()
    raw["supporting_visuals"] = [{"kind": "label", "ref": "caption", "text": "the middle one"}]
    raw["beats"][1]["custom_actions"] = [
        {"kind": "reveal", "targets": [{"visual_ref": "caption"}]},
    ]
    plan = TeachingPlanDocument.model_validate(raw)

    program = compile_teaching_plan(
        plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    assert len(_reveals_of(program, "caption")) == 1


def test_the_unresolved_answer_is_revealed_in_the_first_beat(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    reveals = [
        entry for entry in program.timeline
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    ]
    assert len(reveals) == 1
    assert reveals[0].beat_id == published_perimeter_plan.beats[0].id


def test_the_work_stage_lands_on_the_derive_beat_and_the_value_on_conclude(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    stages = {
        entry.action.stage: entry.beat_id
        for entry in program.timeline if entry.action.kind == "show_answer_stage"
    }
    work_beat = next(
        beat.id for beat in reversed(published_perimeter_plan.beats[:-1])
        if beat.kind in {"derive", "focus"}
    )
    assert stages == {"work": work_beat, "value": published_perimeter_plan.beats[-1].id}


def test_the_answer_unit_becomes_the_answer_visual_suffix(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    plan = published_perimeter_plan.model_copy(update={"answer_unit": "cm"})

    program = compile_teaching_plan(
        plan, perimeter_answer, frozenset({"length", "width"}), compile_context,
    )

    answer, = [visual for visual in program.visuals if visual.ref == "evaluated_answer"]
    assert answer.suffix == " cm"


def test_an_answer_with_no_arithmetic_gets_no_work_stage(
    published_perimeter_plan, compile_context,
):
    """`has_operation` is false for a bare field reference, so there is nothing
    to show and the lesson goes straight from "?" to the value."""
    bare_answer = FieldRefNode(field="length")

    program = compile_teaching_plan(
        published_perimeter_plan, bare_answer,
        frozenset({"length", "width"}), compile_context,
    )

    stages = {
        entry.action.stage for entry in program.timeline
        if entry.action.kind == "show_answer_stage"
    }
    assert stages == {"value"}


def test_pair_elimination_still_declares_no_answer_visual(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    assert not [visual for visual in program.visuals if visual.ref == "evaluated_answer"]
    assert not [entry for entry in program.timeline if entry.action.kind == "show_answer_stage"]
    assert program.answer_anchor is not None


# ---------------------------------------------------------------------------
# regroup and magnitude_comparison
# ---------------------------------------------------------------------------
#
# Before these branches existed, a `regroup` grid or a `magnitude_comparison`
# bar/number_line validated, compiled, and rendered as a whole-visual reveal
# with no strategy-specific animation. The expander now walks the primary
# visual's semantic parts and emits observable role changes that read as the
# strategy names them. See issue #66.


def _grid_regroup_plan(rows, columns):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "See a rectangle as rows of equal groups.",
        "primary_visual": {
            "kind": "grid", "ref": "array",
            "rows": {"node": "literal", "value": rows},
            "columns": {"node": "literal", "value": columns},
        },
        "strategy": "regroup",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "array"}],
             "intent": "show the array"},
            {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "array"}],
             "intent": "see the array as rows"},
            {"id": "count", "kind": "derive", "targets": [{"visual_ref": "array"}],
             "intent": "multiply rows by columns"},
            {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "array"}],
             "intent": "state the total"},
        ],
        "variation_seed": "grid-regroup",
    })


def test_regroup_grid_walks_every_cell_row_by_row_into_a_constraint_accent(compile_context):
    plan = _grid_regroup_plan(rows=2, columns=3)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    organize = [entry for entry in program.timeline if entry.beat_id == "regroup"]
    role_actions = [entry.action for entry in organize if entry.action.kind == "set_role"]

    assert role_actions, "regroup must emit set_role actions on the primary visual"
    assert all(action.target.visual_ref == "array" for action in role_actions)
    assert all(action.target.part == "cell" for action in role_actions)
    assert all(action.role == "constraint" for action in role_actions)
    assert [action.target.index for action in role_actions] == [0, 1, 2, 3, 4, 5]


def test_regroup_grid_recolours_each_row_at_a_single_instant(compile_context):
    """Row-simultaneous recolour is the point: three cells that fade at the
    same time read as ONE group, three that fade sequentially read as a wave.
    """
    plan = _grid_regroup_plan(rows=2, columns=3)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    starts = {}
    for entry in program.timeline:
        if entry.beat_id == "regroup" and entry.action.kind == "set_role":
            starts.setdefault(entry.at_seconds, []).append(entry.action.target.index)

    assert len(starts) == 2, "one slot per row for a 2-row grid"
    for slot_indices in starts.values():
        assert len(slot_indices) == 3, "each row's three cells share one slot"


def test_regroup_grid_stays_under_the_forty_action_timeline_cap(compile_context):
    """A 4x5 regroup grid used to emit 40 organize actions alone (two per
    cell) and overrun the 40-entry timeline cap in `compile_teaching_plan`
    once anything else needed a slot.
    """
    plan = _grid_regroup_plan(rows=4, columns=5)
    answer = MultiplyNode(operands=[LiteralNode(value=4), LiteralNode(value=5)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    organize_actions = [entry for entry in program.timeline if entry.beat_id == "regroup"]
    assert len(organize_actions) == 20, "one action per cell, no release phase"
    assert len(program.timeline) <= 40


def test_regroup_rejects_a_grid_larger_than_the_cap(compile_context):
    plan_raw = _grid_regroup_plan(rows=6, columns=6).model_dump()
    plan = TeachingPlanDocument.model_validate(plan_raw)
    answer = MultiplyNode(operands=[LiteralNode(value=6), LiteralNode(value=6)])

    with pytest.raises(V3ValidationError, match="regroup_too_many_cells"):
        compile_teaching_plan(plan, answer, frozenset(), compile_context)


def test_regroup_rejects_a_grid_with_non_literal_dimensions(compile_context):
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["primary_visual"]["rows"] = {"node": "field_ref", "field": "row_count"}
    plan = TeachingPlanDocument.model_validate(raw)
    answer = FieldRefNode(field="row_count")

    with pytest.raises(V3ValidationError, match="regroup_requires_literal_dimensions"):
        compile_teaching_plan(plan, answer, frozenset({"row_count"}), compile_context)


def test_regroup_rejects_custom_actions_on_its_organize_beat():
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["beats"][1]["custom_actions"] = [
        {"kind": "emphasize", "target": {"visual_ref": "array"}},
    ]

    with pytest.raises(ValueError, match="regroup's walk beat"):
        TeachingPlanDocument.model_validate(raw)


def test_regroup_object_set_walks_five_per_row_and_stops_at_count(compile_context):
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "See a group of objects as rows of five.",
        "primary_visual": {
            "kind": "object_set", "ref": "objects",
            "count": {"node": "literal", "value": 6},
        },
        "strategy": "regroup",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "objects"}],
             "intent": "show the objects"},
            {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "objects"}],
             "intent": "see them as rows of five"},
            {"id": "count", "kind": "derive", "targets": [{"visual_ref": "objects"}],
             "intent": "count by rows"},
            {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "objects"}],
             "intent": "state the total"},
        ],
        "variation_seed": "objects-regroup",
    })
    answer = LiteralNode(value=6)

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    indices = [
        entry.action.target.index for entry in program.timeline
        if entry.beat_id == "regroup" and entry.action.kind == "set_role"
    ]
    # Row 0 has five cells (indices 0..4) and row 1 has the remaining one
    # (index 5). The walk stops at `count`, so the partial second row emits
    # a single cell rather than a padded index that no mobject would receive.
    assert indices == [0, 1, 2, 3, 4, 5]


def test_regroup_stages_the_walk_on_exactly_one_organize_beat(compile_context):
    """Two organize beats naming the primary grid would double-stage the row
    walk. The second organize beat must fall through to `_generic_role_change`.
    """
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["beats"] = [
        {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "array"}],
         "intent": "show the array"},
        {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "array"}],
         "intent": "see the array as rows"},
        {"id": "again", "kind": "organize", "targets": [{"visual_ref": "array"}],
         "intent": "revisit the grouping"},
        {"id": "count", "kind": "derive", "targets": [{"visual_ref": "array"}],
         "intent": "multiply rows by columns"},
        {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "array"}],
         "intent": "state the total"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    first_walk = [
        entry.action for entry in program.timeline if entry.beat_id == "regroup"
        and entry.action.kind == "set_role" and entry.action.role == "constraint"
    ]
    second_walk = [
        entry.action for entry in program.timeline if entry.beat_id == "again"
        and entry.action.kind == "set_role" and entry.action.role == "constraint"
    ]
    assert [action.target.index for action in first_walk] == [0, 1, 2, 3, 4, 5]
    assert not second_walk, "the second organize beat must not restage the walk"


def test_regroup_skips_organize_beats_that_do_not_name_the_primary(compile_context):
    """An organize beat that names only a supporting label must not restyle
    the grid's cells.
    """
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["supporting_visuals"] = [
        {"kind": "label", "ref": "caption", "text": "count by rows"},
    ]
    raw["beats"] = [
        {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "array"}],
         "intent": "show the array"},
        {"id": "caption_first", "kind": "organize", "targets": [{"visual_ref": "caption"}],
         "intent": "read the caption"},
        {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "array"}],
         "intent": "see the array as rows"},
        {"id": "count", "kind": "derive", "targets": [{"visual_ref": "array"}],
         "intent": "multiply rows by columns"},
        {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "array"}],
         "intent": "state the total"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    caption_beat_actions = [
        entry.action for entry in program.timeline if entry.beat_id == "caption_first"
    ]
    assert not any(
        action.kind == "set_role"
        and getattr(action.target, "visual_ref", None) == "array"
        and action.target.part == "cell"
        for action in caption_beat_actions
    ), "the caption-only organize beat must not restyle grid cells"
    walked = [
        entry.action.target.index for entry in program.timeline
        if entry.beat_id == "regroup" and entry.action.kind == "set_role"
        and entry.action.role == "constraint"
    ]
    assert walked == [0, 1, 2, 3, 4, 5], "the walk must still run on the beat that names the grid"


def test_regroup_rejects_a_part_level_reveal_as_a_prior_whole_reveal(compile_context):
    """A prior beat naming `array.cell[0]` reveals that cell but not the whole
    grid; the walk beat's `_reveal_unrevealed` still emits a whole-grid reveal
    and steals a row's slot. Only a whole-visual reveal satisfies the
    reveal-before-organize requirement.
    """
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["beats"] = [
        {"id": "orient_cell", "kind": "orient",
         "targets": [{"visual_ref": "array", "part": "cell", "index": 0}],
         "intent": "point at the first cell (reveals only that cell)"},
        {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "array"}],
         "intent": "see the array as rows"},
        {"id": "count", "kind": "derive", "targets": [{"visual_ref": "array"}],
         "intent": "multiply rows by columns"},
        {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "array"}],
         "intent": "state the total"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    with pytest.raises(V3ValidationError,
                       match="regroup_requires_primary_revealed_before_organize"):
        compile_teaching_plan(plan, answer, frozenset(), compile_context)


def test_regroup_accepts_a_prior_custom_whole_reveal(compile_context):
    """A custom `reveal` naming the whole primary visual on an earlier beat
    should satisfy the reveal-before-organize requirement -- the whole grid
    is on screen before the walk runs, so no reveal action lands in the walk
    beat.
    """
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["beats"] = [
        {"id": "orient_cell", "kind": "orient",
         "targets": [{"visual_ref": "array", "part": "cell", "index": 0}],
         "intent": "point at the first cell first",
         "custom_actions": [
             {"kind": "reveal", "targets": [{"visual_ref": "array"}]},
         ]},
        {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "array"}],
         "intent": "see the array as rows"},
        {"id": "count", "kind": "derive", "targets": [{"visual_ref": "array"}],
         "intent": "multiply rows by columns"},
        {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "array"}],
         "intent": "state the total"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    walk_entries = [entry for entry in program.timeline if entry.beat_id == "regroup"]
    assert not any(entry.action.kind == "reveal" for entry in walk_entries), (
        "the walk beat must emit only role changes when the whole grid is already revealed"
    )
    starts = {}
    for entry in walk_entries:
        if entry.action.kind == "set_role":
            starts.setdefault(entry.at_seconds, []).append(entry.action.target.index)
    assert len(starts) == 2 and all(len(row) == 3 for row in starts.values()), (
        "row-per-slot arithmetic must survive when the walk beat holds only role changes"
    )


def test_regroup_requires_the_grid_to_be_revealed_before_its_organize_beat(compile_context):
    """When organize is the first beat naming the primary visual, a reveal
    action lands in the same beat as the row walk. That reveal steals a slot
    from the row-per-slot arithmetic and splits a row across two slots. The
    plan is refused so the walk never renders as a wave.
    """
    raw = _grid_regroup_plan(rows=2, columns=3).model_dump()
    raw["supporting_visuals"] = [
        {"kind": "label", "ref": "caption", "text": "count by rows"},
    ]
    raw["beats"] = [
        {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "caption"}],
         "intent": "read the caption first"},
        {"id": "regroup", "kind": "organize", "targets": [{"visual_ref": "array"}],
         "intent": "see the array as rows"},
        {"id": "count", "kind": "derive", "targets": [{"visual_ref": "array"}],
         "intent": "multiply rows by columns"},
        {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "array"}],
         "intent": "state the total"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)
    answer = MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)])

    with pytest.raises(V3ValidationError,
                       match="regroup_requires_primary_revealed_before_organize"):
        compile_teaching_plan(plan, answer, frozenset(), compile_context)


def _bar_magnitude_plan(value, maximum):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Read a bar's magnitude against its maximum.",
        "primary_visual": {
            "kind": "bar", "ref": "usage",
            "value": {"node": "literal", "value": value},
            "maximum": {"node": "literal", "value": maximum},
        },
        "strategy": "magnitude_comparison",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "usage"}],
             "intent": "show the bar"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "usage"}],
             "intent": "sweep the bar's magnitude"},
            {"id": "state_value", "kind": "conclude", "targets": [{"visual_ref": "usage"}],
             "intent": "state the value"},
        ],
        "variation_seed": "bar-magnitude",
    })


def test_magnitude_comparison_bar_sweeps_focus_across_the_value_not_the_maximum(compile_context):
    """A bar with value=3, maximum=5 must animate 3 segments, not 5. Sweeping
    to the maximum teaches capacity; sweeping to the value teaches the actual
    magnitude the lesson names.
    """
    plan = _bar_magnitude_plan(value=3, maximum=5)
    answer = LiteralNode(value=3)

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert [action.target.part for action in focus_actions] == ["segment"] * 3
    assert [action.target.index for action in focus_actions] == [0, 1, 2]


def test_magnitude_comparison_bar_focuses_one_segment_per_instant(compile_context):
    """`check_salience` rejects two focus role changes at the same at_seconds.
    A per-part slot count is what keeps the sweep passing that gate.
    """
    plan = _bar_magnitude_plan(value=3, maximum=5)
    answer = LiteralNode(value=3)

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    starts = [
        entry.at_seconds for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert len(set(starts)) == len(starts) == 3


def test_magnitude_comparison_rejects_a_non_literal_bar_value(compile_context):
    raw = _bar_magnitude_plan(value=3, maximum=5).model_dump()
    raw["primary_visual"]["value"] = {"node": "field_ref", "field": "usage"}
    plan = TeachingPlanDocument.model_validate(raw)

    with pytest.raises(V3ValidationError, match="magnitude_comparison_requires_literal_bar_value"):
        compile_teaching_plan(plan, LiteralNode(value=3), frozenset({"usage"}), compile_context)


def test_magnitude_comparison_rejects_custom_actions_on_its_sweep_beat():
    raw = _bar_magnitude_plan(value=3, maximum=5).model_dump()
    raw["beats"][1]["custom_actions"] = [
        {"kind": "emphasize", "target": {"visual_ref": "usage"}},
    ]

    with pytest.raises(ValueError, match="magnitude_comparison's sweep beat"):
        TeachingPlanDocument.model_validate(raw)


def _number_line_magnitude_plan(marker_values):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Compare numeric magnitudes on a line.",
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": {"node": "literal", "value": 0},
            "maximum": {"node": "literal", "value": 10},
            "markers": [{"node": "literal", "value": value} for value in marker_values],
        },
        "strategy": "magnitude_comparison",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "line"}],
             "intent": "show the number line"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "line"}],
             "intent": "compare each marker's magnitude"},
            {"id": "state_answer", "kind": "conclude", "targets": [{"visual_ref": "line"}],
             "intent": "state the largest"},
        ],
        "variation_seed": "number-line-magnitude",
    })


def test_magnitude_comparison_number_line_focuses_each_declared_marker(compile_context):
    plan = _number_line_magnitude_plan([2, 5, 8])
    program = compile_teaching_plan(plan, LiteralNode(value=8), frozenset(), compile_context)

    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert [action.target.part for action in focus_actions] == ["marker"] * 3
    assert [action.target.index for action in focus_actions] == [0, 1, 2]


def test_magnitude_comparison_rejects_a_zero_magnitude_bar(compile_context):
    """A bar with value 0 has nothing to sweep. The empty sweep would fall
    through to a whole-visual focus -- the group_reveal shape bug #66 targets.
    """
    raw = _bar_magnitude_plan(value=0, maximum=5).model_dump()
    plan = TeachingPlanDocument.model_validate(raw)

    with pytest.raises(V3ValidationError, match="magnitude_comparison_requires_positive_bar_value"):
        compile_teaching_plan(plan, LiteralNode(value=0), frozenset(), compile_context)


def test_magnitude_comparison_rejects_a_number_line_with_no_markers(compile_context):
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Compare magnitudes on an empty line.",
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": {"node": "literal", "value": 0},
            "maximum": {"node": "literal", "value": 10},
            "markers": [],
        },
        "strategy": "magnitude_comparison",
        "answer_unit": "",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "line"}],
             "intent": "show the number line"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "line"}],
             "intent": "sweep markers"},
            {"id": "state", "kind": "conclude", "targets": [{"visual_ref": "line"}],
             "intent": "state"},
        ],
        "variation_seed": "empty-line",
    })

    with pytest.raises(V3ValidationError, match="magnitude_comparison_requires_at_least_one_marker"):
        compile_teaching_plan(plan, LiteralNode(value=0), frozenset(), compile_context)


def test_magnitude_comparison_stages_the_sweep_on_exactly_one_beat(compile_context):
    """Two focus/derive beats naming the primary visual would double-stage the
    same sweep. The second beat must fall through to `_generic_role_change`.
    """
    raw = _bar_magnitude_plan(value=3, maximum=5).model_dump()
    raw["beats"] = [
        {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "usage"}],
         "intent": "show the bar"},
        {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "usage"}],
         "intent": "sweep magnitude"},
        {"id": "again", "kind": "focus", "targets": [{"visual_ref": "usage"}],
         "intent": "focus the bar as a whole"},
        {"id": "state_value", "kind": "conclude", "targets": [{"visual_ref": "usage"}],
         "intent": "state the value"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)

    program = compile_teaching_plan(plan, LiteralNode(value=3), frozenset(), compile_context)

    swept = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus" and entry.action.target.part == "segment"
    ]
    later = [
        entry.action for entry in program.timeline
        if entry.beat_id == "again" and entry.action.kind == "set_role"
        and entry.action.role == "focus" and entry.action.target.part == "segment"
    ]
    assert [action.target.index for action in swept] == [0, 1, 2]
    assert not later, "the second focus/derive beat must not restage the sweep"


def test_magnitude_comparison_skips_beats_that_target_only_a_supporting_visual(compile_context):
    """A derive beat that names only a caption must not sweep the bar's
    segments. `beat.targets` filters out those beats before the sweep runs.
    """
    raw = _bar_magnitude_plan(value=3, maximum=5).model_dump()
    raw["supporting_visuals"] = [
        {"kind": "label", "ref": "caption", "text": "current usage"},
    ]
    raw["beats"] = [
        {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "usage"}],
         "intent": "show the bar"},
        {"id": "read_caption", "kind": "derive", "targets": [{"visual_ref": "caption"}],
         "intent": "read the caption text"},
        {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "usage"}],
         "intent": "sweep magnitude"},
        {"id": "state_value", "kind": "conclude", "targets": [{"visual_ref": "usage"}],
         "intent": "state the value"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)

    program = compile_teaching_plan(plan, LiteralNode(value=3), frozenset(), compile_context)

    caption_beat_actions = [
        entry.action for entry in program.timeline if entry.beat_id == "read_caption"
    ]
    assert not any(
        action.kind == "set_role"
        and getattr(action.target, "visual_ref", None) == "usage"
        for action in caption_beat_actions
    ), "the caption-only beat must not restyle the bar"
    swept = [
        entry.action.target.index for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus" and entry.action.target.part == "segment"
    ]
    assert swept == [0, 1, 2], "the sweep must still run on the beat that names the bar"


def test_magnitude_comparison_requires_a_focus_or_derive_beat_naming_the_primary(compile_context):
    """No focus/derive beat targets the primary bar -- the sweep has nowhere
    to land, so the plan must be refused rather than silently rendering as
    group_reveal.
    """
    raw = _bar_magnitude_plan(value=3, maximum=5).model_dump()
    raw["supporting_visuals"] = [
        {"kind": "label", "ref": "caption", "text": "current usage"},
    ]
    raw["beats"] = [
        {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "usage"}],
         "intent": "show the bar"},
        {"id": "read_caption", "kind": "derive", "targets": [{"visual_ref": "caption"}],
         "intent": "read the caption only"},
        {"id": "state_value", "kind": "conclude", "targets": [{"visual_ref": "usage"}],
         "intent": "state the value"},
    ]
    plan = TeachingPlanDocument.model_validate(raw)

    with pytest.raises(V3ValidationError, match="magnitude_comparison_requires_sweep_beat"):
        compile_teaching_plan(plan, LiteralNode(value=3), frozenset(), compile_context)


def test_magnitude_comparison_bar_focuses_one_segment_per_instant_when_the_sweep_beat_also_reveals(compile_context):
    """A bar unrevealed until the sweep beat -- because no earlier beat names
    it -- emits its own `RevealAction` alongside the focus sweep. If the slot
    count was `len(indices)` (three, for value 3), the four actions batched
    into three slots would put segments 1 and 2 in one slot at the same
    `at_seconds` and fail `check_salience`.
    """
    from app.meta.v3.quality import validate_static_quality

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Read a bar's magnitude alongside a caption.",
        "primary_visual": {
            "kind": "bar", "ref": "usage",
            "value": {"node": "literal", "value": 3},
            "maximum": {"node": "literal", "value": 5},
        },
        "supporting_visuals": [
            {"kind": "label", "ref": "caption", "text": "current usage"},
        ],
        "strategy": "magnitude_comparison",
        "answer_unit": "",
        "beats": [
            {"id": "orient_caption", "kind": "orient", "targets": [{"visual_ref": "caption"}],
             "intent": "introduce the caption first"},
            {"id": "sweep", "kind": "derive", "targets": [{"visual_ref": "usage"}],
             "intent": "sweep magnitude while also revealing the bar"},
            {"id": "state_value", "kind": "conclude", "targets": [{"visual_ref": "usage"}],
             "intent": "state the value"},
        ],
        "variation_seed": "reveal-in-sweep",
    })

    program = compile_teaching_plan(plan, LiteralNode(value=3), frozenset(), compile_context)

    sweep_entries = [entry for entry in program.timeline if entry.beat_id == "sweep"]
    assert any(entry.action.kind == "reveal" for entry in sweep_entries), (
        "the sweep beat must be the one that first reveals the bar in this plan"
    )
    focus_at_seconds = [
        entry.at_seconds for entry in sweep_entries
        if entry.action.kind == "set_role" and entry.action.role == "focus"
    ]
    assert len(focus_at_seconds) == 3
    assert len(set(focus_at_seconds)) == 3, "each focus must land on its own at_seconds"

    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]


def test_magnitude_comparison_number_line_sweeps_markers_left_to_right(compile_context):
    """Markers declared out of numeric order (8, 2, 5) must still animate in
    left-to-right axis order (2, 5, 8 -- indices 1, 2, 0), or the sweep reads
    as a jumble against the number line's own axis.
    """
    plan = _number_line_magnitude_plan([8, 2, 5])
    program = compile_teaching_plan(plan, LiteralNode(value=8), frozenset(), compile_context)

    focus_actions = [
        entry.action for entry in program.timeline
        if entry.beat_id == "sweep" and entry.action.kind == "set_role"
        and entry.action.role == "focus"
    ]
    assert [action.target.index for action in focus_actions] == [1, 2, 0]


def test_regroup_and_magnitude_comparison_plans_pass_every_quality_gate(compile_context):
    """A pedagogically thin degrade would still validate; a working expander
    must clear the same static-quality gates the older strategies clear.
    """
    from app.meta.v3.quality import validate_static_quality

    grid_plan = _grid_regroup_plan(rows=2, columns=3)
    grid_program = compile_teaching_plan(
        grid_plan, MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)]),
        frozenset(), compile_context,
    )
    grid_report = validate_static_quality(grid_plan, grid_program)
    assert grid_report.passed, [check for check in grid_report.checks if not check.passed]

    bar_plan = _bar_magnitude_plan(value=3, maximum=5)
    bar_program = compile_teaching_plan(
        bar_plan, LiteralNode(value=3), frozenset(), compile_context,
    )
    bar_report = validate_static_quality(bar_plan, bar_program)
    assert bar_report.passed, [check for check in bar_report.checks if not check.passed]


def test_coordinate_plane_plan_plotting_two_points_compiles(compile_context):
    """M14 acceptance fixture: a plan whose primary visual is a coordinate_plane
    with the two points (2, 3) and (-1, 4) compiles into a scene program and
    passes every static quality gate.

    Foundational: the plane exposes each plotted point as a `point` semantic
    part, and downstream tickets (M10, M12, M13, M17, M21) target those parts
    without renegotiating the plane's numeric span or its scene-coord extent.
    """
    from app.meta.v3.quality import validate_static_quality

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Plot ordered pairs on a coordinate plane.",
        "primary_visual": {
            "kind": "coordinate_plane", "ref": "plane",
            "x_min": {"node": "literal", "value": -3},
            "x_max": {"node": "literal", "value": 5},
            "y_min": {"node": "literal", "value": -3},
            "y_max": {"node": "literal", "value": 5},
            "points": [
                {"x": {"node": "literal", "value": 2}, "y": {"node": "literal", "value": 3}},
                {"x": {"node": "literal", "value": -1}, "y": {"node": "literal", "value": 4}},
            ],
        },
        "strategy": "group_reveal",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "plane"}],
             "intent": "introduce the coordinate plane"},
            {"id": "focus_first", "kind": "focus",
             "targets": [{"visual_ref": "plane", "part": "point", "index": 0}],
             "intent": "point out the first plotted pair"},
            {"id": "focus_second", "kind": "derive",
             "targets": [{"visual_ref": "plane", "part": "point", "index": 1}],
             "intent": "point out the second plotted pair"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "plane"}],
             "intent": "name the two plotted points"},
        ],
        "variation_seed": "m14-plot",
    })

    program = compile_teaching_plan(
        plan, LiteralNode(value=2), frozenset(), compile_context,
    )

    plane_visual = next(v for v in program.visuals if v.ref == "plane")
    assert plane_visual.kind == "coordinate_plane"
    assert [(float(p.x.value), float(p.y.value)) for p in plane_visual.points] == [
        (2.0, 3.0), (-1.0, 4.0),
    ]

    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]


def test_coordinate_plane_rejects_a_point_target_beyond_the_declared_points(compile_context):
    """A plan indexing past the plotted points names something never drawn."""
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Plot ordered pairs on a coordinate plane.",
        "primary_visual": {
            "kind": "coordinate_plane", "ref": "plane",
            "x_min": {"node": "literal", "value": -3},
            "x_max": {"node": "literal", "value": 5},
            "y_min": {"node": "literal", "value": -3},
            "y_max": {"node": "literal", "value": 5},
            "points": [
                {"x": {"node": "literal", "value": 2}, "y": {"node": "literal", "value": 3}},
            ],
        },
        "strategy": "group_reveal",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "plane"}],
             "intent": "introduce the coordinate plane"},
            {"id": "focus_missing", "kind": "focus",
             "targets": [{"visual_ref": "plane", "part": "point", "index": 4}],
             "intent": "name a point that was not plotted"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "plane"}],
             "intent": "state the coordinates"},
        ],
        "variation_seed": "m14-bad-index",
    })

    with pytest.raises(V3ValidationError) as exc_info:
        compile_teaching_plan(plan, LiteralNode(value=2), frozenset(), compile_context)

    assert exc_info.value.failure.code == "target_index_out_of_range"


# --- M11 acceptance: expressions, one-/two-step equations, inequalities ------
#
# Each fixture is one row of ticket #105's acceptance criteria. The strategies
# and visual kinds involved are:
#
# - `expression_evaluate` (evaluate 3n + 2 at n = 4): label + group_reveal.
#   No new kind or strategy -- the label carries the expression's text and the
#   compiler resolves the answer to its value on the conclude beat.
# - `one_step_equation` (solve x + 7 = 12): bar + inverse_operation.
# - `two_step_equation` (solve 2x + 3 = 11): bar + inverse_operation.
# - `inequality_line` (graph x > 3): number_line + ray_shade.
#
# `inverse_operation` and `ray_shade` join the strategy set as first-class
# literals. They fall through to the generic beat expander (like `group_reveal`
# and `partition` do) rather than staging their own choreography, so the
# strategy name expresses the pedagogical intent without a new compiler pass.


def test_expression_evaluate_label_group_reveal_compiles(compile_context):
    """Ticket #105 acceptance: evaluate 3n + 2 at n = 4 with the existing
    label + group_reveal path (the ticket notes this archetype "may not need
    a new kind"). The plan carries the expression's text on a label; the
    answer expression resolves to 14 = 3 x 4 + 2 on the conclude beat.
    """
    from app.meta.v3.quality import validate_static_quality

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Evaluate the expression 3n + 2 for a given value of n.",
        "primary_visual": {"kind": "label", "ref": "expression", "text": "3n + 2"},
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal_expression", "kind": "reveal",
             "targets": [{"visual_ref": "expression"}],
             "intent": "show the expression to evaluate"},
            {"id": "substitute", "kind": "derive",
             "targets": [{"visual_ref": "expression"}],
             "intent": "substitute n = 4 into the expression"},
            {"id": "state_value", "kind": "conclude",
             "targets": [{"visual_ref": "expression"}],
             "intent": "state the evaluated value"},
        ],
        "variation_seed": "m11-eval-3n-plus-2",
    })
    answer = AddNode(operands=[
        MultiplyNode(operands=[LiteralNode(value=3), FieldRefNode(field="n")]),
        LiteralNode(value=2),
    ])

    program = compile_teaching_plan(
        plan, answer, frozenset({"n"}), compile_context,
    )

    # The answer visual carries the substituted arithmetic on its `work` stage
    # and the value 14 on `value`, so the conclusion resolves without reflowing.
    answer_visual = next(v for v in program.visuals if v.ref == "evaluated_answer")
    assert answer_visual.kind == "answer_expression"

    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]


def test_one_step_equation_bar_inverse_operation_compiles(compile_context):
    """Ticket #105 acceptance: solve x + 7 = 12 on a bar (tape) using the new
    `inverse_operation` strategy. The bar carries 12 total units; the derive
    beat is where the plan applies the inverse operation (subtract 7) to
    isolate x. The compiler resolves the answer to 12 - 7 = 5.
    """
    from app.meta.v3.quality import validate_static_quality

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Solve x + 7 = 12 by applying the inverse operation.",
        "primary_visual": {
            "kind": "bar", "ref": "tape",
            "value": {"node": "literal", "value": 12},
            "maximum": {"node": "literal", "value": 12},
            "constant": {"node": "literal", "value": 7},
            "coefficient": {"node": "literal", "value": 1},
        },
        "strategy": "inverse_operation",
        "beats": [
            {"id": "reveal_equation", "kind": "reveal",
             "targets": [{"visual_ref": "tape"}],
             "intent": "show the tape representing x + 7 = 12"},
            {"id": "isolate_x", "kind": "derive",
             "targets": [{"visual_ref": "tape"}],
             "intent": "subtract 7 from both sides to isolate x"},
            {"id": "state_solution", "kind": "conclude",
             "targets": [{"visual_ref": "tape"}],
             "intent": "state the value of x"},
        ],
        "variation_seed": "m11-one-step",
    })
    answer = SubtractNode(operands=[LiteralNode(value=12), LiteralNode(value=7)])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    tape = next(v for v in program.visuals if v.ref == "tape")
    assert tape.kind == "bar"

    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]


def test_two_step_equation_bar_inverse_operation_compiles(compile_context):
    """Ticket #105 acceptance: solve 2x + 3 = 11 on a bar with two inverse
    steps. The derive beat applies both -- subtract 3, then divide by 2 --
    to isolate x. Answer resolves to (11 - 3) / 2 = 4.
    """
    from app.meta.v3.quality import validate_static_quality

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Solve 2x + 3 = 11 by applying two inverse operations.",
        "primary_visual": {
            "kind": "bar", "ref": "tape",
            "value": {"node": "literal", "value": 11},
            "maximum": {"node": "literal", "value": 11},
            "constant": {"node": "literal", "value": 3},
            "coefficient": {"node": "literal", "value": 2},
        },
        "strategy": "inverse_operation",
        "beats": [
            {"id": "reveal_equation", "kind": "reveal",
             "targets": [{"visual_ref": "tape"}],
             "intent": "show the tape representing 2x + 3 = 11"},
            {"id": "subtract_constant", "kind": "focus",
             "targets": [{"visual_ref": "tape"}],
             "intent": "subtract 3 from both sides"},
            {"id": "divide_by_coefficient", "kind": "derive",
             "targets": [{"visual_ref": "tape"}],
             "intent": "divide both sides by 2 to isolate x"},
            {"id": "state_solution", "kind": "conclude",
             "targets": [{"visual_ref": "tape"}],
             "intent": "state the value of x"},
        ],
        "variation_seed": "m11-two-step",
    })
    answer = DivideNode(operands=[
        SubtractNode(operands=[LiteralNode(value=11), LiteralNode(value=3)]),
        LiteralNode(value=2),
    ])

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    tape = next(v for v in program.visuals if v.ref == "tape")
    assert tape.kind == "bar"

    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]


def test_inequality_number_line_ray_shade_compiles(compile_context):
    """Ticket #105 acceptance: graph x > 3 on a number line using the new
    `ray_shade` strategy. The line's boundary is expressed as a marker at 3
    (the value below the shaded ray). The answer expression carries the
    boundary; a full inequality-as-set is not expressible as an ExpressionNode,
    so the boundary stands in for what conclude resolves.
    """
    from app.meta.v3.quality import validate_static_quality

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Graph the inequality x > 3 on a number line.",
        "primary_visual": {
            "kind": "number_line", "ref": "line",
            "minimum": {"node": "literal", "value": 0},
            "maximum": {"node": "literal", "value": 6},
            "markers": [
                {"node": "literal", "value": 0},
                {"node": "literal", "value": 3},
                {"node": "literal", "value": 6},
            ],
            "boundary": {"node": "literal", "value": 3},
            "boundary_kind": "open",
            "ray_direction": "right",
        },
        "strategy": "ray_shade",
        "beats": [
            {"id": "reveal_line", "kind": "reveal",
             "targets": [{"visual_ref": "line"}],
             "intent": "show the number line with the boundary at 3"},
            {"id": "focus_boundary", "kind": "focus",
             "targets": [{"visual_ref": "line"}],
             "intent": "mark 3 as the boundary of the inequality"},
            {"id": "shade_ray", "kind": "derive",
             "targets": [{"visual_ref": "line"}],
             "intent": "shade every value greater than 3"},
            {"id": "state_solution", "kind": "conclude",
             "targets": [{"visual_ref": "line"}],
             "intent": "state that x > 3 is the shaded ray"},
        ],
        "variation_seed": "m11-inequality",
    })
    answer = LiteralNode(value=3)

    program = compile_teaching_plan(plan, answer, frozenset(), compile_context)

    line = next(v for v in program.visuals if v.ref == "line")
    assert line.kind == "number_line"

    report = validate_static_quality(plan, program)
    assert report.passed, [check for check in report.checks if not check.passed]
