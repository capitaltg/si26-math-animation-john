from copy import deepcopy

import pytest

from app.meta.dsl.expression import AddNode, FieldRefNode, LiteralNode, MultiplyNode
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
    assert 6 <= program.total_duration_seconds <= 12


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
    answer_reveal = next(
        index for index, entry in enumerate(program.timeline)
        if entry.action.kind == "reveal" and entry.action.targets[0].visual_ref == "evaluated_answer"
    )
    assert trace < answer_reveal
    assert program.timeline[trace].action.path_ref == "rectangle.perimeter"


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
    assert program.total_duration_seconds <= 12


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
    assert 6 <= program.total_duration_seconds <= 12


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


def test_answer_visual_is_revealed_only_by_the_conclusion(
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
    assert answer_entries[0].beat_id == "conclude"


def test_conclusion_reveal_and_role_hold_together_for_at_least_one_and_a_half_seconds(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    """The answer card's reveal and its `conclusion` recolour must land together.

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

    assert {entry.action.kind for entry in conclusion_entries} == {"reveal", "set_role"}
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


def test_scheduler_rejects_minimum_timeline_that_exceeds_twelve_seconds():
    beats = [
        ExpandedBeat(
            beat_id=f"organize_{index}",
            actions=[SetRoleAction(target=TargetRef(visual_ref="values"), role="structure")],
            minimum_seconds=1.25,
            weight=1.0,
        )
        for index in range(9)
    ]
    beats.append(ExpandedBeat(
        beat_id="conclude",
        actions=[RevealAction(targets=[TargetRef(visual_ref="evaluated_answer")], mode="together")],
        minimum_seconds=1.5,
        weight=1.5,
    ))

    with pytest.raises(V3ValidationError, match="timeline_over_budget"):
        schedule_beats(beats)


def test_timeline_entries_fit_the_declared_total_duration(median_plan, answer, compile_context):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    assert all(
        entry.duration_seconds >= 0.15
        and entry.duration_seconds <= 2
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
