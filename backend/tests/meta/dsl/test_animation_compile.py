import pytest

from app.meta.dsl.animation import (
    AnimationDocument,
    AppearNode,
    ArrowNode,
    BraceNode,
    ColumnNode,
    ExpressionLabelNode,
    HighlightNode,
    LabelNode,
    NumberLineNode,
    ObjectSetNode,
    OverlayNode,
    ParallelNode,
    RowNode,
    RectangleNode,
    SequenceNode,
    WaitNode,
    compile_animation_document,
)
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode, LiteralNode


def test_valid_document_compiles_and_reports_refs():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                RowNode(
                    children=[
                        NumberLineNode(
                            ref="line",
                            minimum=LiteralNode(value=0),
                            maximum=FieldRefNode(field="total"),
                            marker_value=FieldRefNode(field="value"),
                        ),
                    ]
                ),
                AppearNode(target_ref="line"),
                WaitNode(seconds=1),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset({"total", "value"}))
    assert compiled.refs == {"line"}
    assert compiled.total_duration_seconds == pytest.approx(2.0)


def test_dangling_ref_rejected():
    document = AnimationDocument(animation_version=1, root=AppearNode(target_ref="ghost"))
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "dangling_ref"


def test_duplicate_ref_rejected():
    document = AnimationDocument(
        animation_version=1,
        root=RowNode(
            children=[
                LabelNode(ref="dup", text="a"),
                LabelNode(ref="dup", text="b"),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "duplicate_ref"


def test_unknown_field_inside_visual_expression_rejected():
    document = AnimationDocument(
        animation_version=1,
        root=NumberLineNode(
            minimum=LiteralNode(value=0),
            maximum=FieldRefNode(field="ghost"),
            marker_value=LiteralNode(value=1),
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "unknown_field"


def test_arrow_referencing_undeclared_endpoint_rejected():
    document = AnimationDocument(
        animation_version=1,
        root=RowNode(
            children=[
                LabelNode(ref="a", text="a"),
                ArrowNode(from_ref="a", to_ref="missing"),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "dangling_ref"


def test_ref_on_non_producing_node_rejected_as_dangling():
    # A WaitNode declares ref "w", but wait produces no mobject at render time, so an
    # AppearNode targeting it would KeyError. Compile must reject it up front.
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                WaitNode(ref="w", seconds=1),
                AppearNode(target_ref="w"),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "dangling_ref"


def test_parallel_with_direct_producing_kind_step_rejected():
    # render_animation_node's `parallel` branch feeds each step's return value
    # straight into scene.play(*animations). A producing-kind step (e.g.
    # ObjectSetNode) returns a raw mobject, not an Animation, and would crash
    # scene.play at render time. Compile must reject this up front.
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="a", text="a"),
                ParallelNode(
                    steps=[
                        AppearNode(target_ref="a"),
                        ObjectSetNode(count=LiteralNode(value=3)),
                    ]
                ),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "invalid_parallel_step"


def test_parallel_with_label_step_rejected():
    # Same failure mode as above, using a different producing kind (label) to
    # confirm the guard isn't hardcoded to a single kind.
    document = AnimationDocument(
        animation_version=1,
        root=ParallelNode(
            steps=[
                LabelNode(text="hello"),
                LabelNode(text="world"),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "invalid_parallel_step"


def test_parallel_with_only_timed_action_steps_compiles_fine():
    # No regression: a parallel block whose direct steps are all timed actions
    # (which return Animations, not mobjects) must still compile successfully.
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="a", text="a"),
                LabelNode(ref="b", text="b"),
                ParallelNode(
                    steps=[
                        AppearNode(target_ref="a"),
                        HighlightNode(target_ref="b"),
                    ]
                ),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset())
    assert compiled.refs == {"a", "b"}


def test_layout_rejects_timed_action_children():
    document = AnimationDocument(
        animation_version=1,
        root=RowNode(
            children=[
                LabelNode(ref="caption", text="caption"),
                AppearNode(target_ref="caption"),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "invalid_layout_child"


def test_multiple_independent_appeared_visuals_require_shared_layout():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="title", text="Perimeter of a Rectangle"),
                AppearNode(target_ref="title"),
                ObjectSetNode(ref="diagram", count=LiteralNode(value=3)),
                AppearNode(target_ref="diagram"),
                LabelNode(ref="formula", text="Perimeter = 2 × (length + width)"),
                AppearNode(target_ref="formula"),
            ]
        ),
    )

    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())

    assert exc.value.code == "missing_shared_layout"
    assert "diagram, formula, title" in exc.value.message


def test_progressively_appeared_visuals_in_one_column_compile():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                ColumnNode(
                    children=[
                        LabelNode(ref="title", text="Perimeter of a Rectangle"),
                        ObjectSetNode(ref="diagram", count=LiteralNode(value=3)),
                        LabelNode(ref="formula", text="Perimeter = 2 × (length + width)"),
                    ]
                ),
                AppearNode(target_ref="title"),
                AppearNode(target_ref="diagram"),
                AppearNode(target_ref="formula"),
            ]
        ),
    )

    compiled = compile_animation_document(document, known_fields=frozenset())

    assert compiled.refs == {"title", "diagram", "formula"}


def test_single_independent_appeared_visual_still_compiles():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="title", text="Perimeter"),
                AppearNode(target_ref="title"),
                AppearNode(target_ref="title"),
            ]
        ),
    )

    compiled = compile_animation_document(document, known_fields=frozenset())

    assert compiled.refs == {"title"}


def test_nested_layouts_share_their_outer_layout_root():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                ColumnNode(
                    children=[
                        LabelNode(ref="title", text="Perimeter"),
                        RowNode(
                            children=[
                                LabelNode(ref="length", text="Length"),
                                LabelNode(ref="width", text="Width"),
                            ]
                        ),
                    ]
                ),
                AppearNode(target_ref="title"),
                AppearNode(target_ref="length"),
                AppearNode(target_ref="width"),
            ]
        ),
    )

    compiled = compile_animation_document(document, known_fields=frozenset())

    assert compiled.refs == {"title", "length", "width"}


def test_appeared_layout_ref_shares_ancestry_with_its_descendant():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                ColumnNode(
                    ref="panel",
                    children=[LabelNode(ref="title", text="Perimeter")],
                ),
                AppearNode(target_ref="panel"),
                AppearNode(target_ref="title"),
            ]
        ),
    )

    compiled = compile_animation_document(document, known_fields=frozenset())

    assert compiled.refs == {"panel", "title"}


def test_multiple_appeared_overlay_descendants_compile():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                OverlayNode(
                    children=[
                        LabelNode(ref="base", text="Rectangle"),
                        LabelNode(ref="annotation", text="Length"),
                    ]
                ),
                AppearNode(target_ref="base"),
                AppearNode(target_ref="annotation"),
            ]
        ),
    )

    compiled = compile_animation_document(document, known_fields=frozenset())

    assert compiled.refs == {"base", "annotation"}


def test_dangling_appear_ref_precedes_shared_layout_validation():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="title", text="Perimeter"),
                AppearNode(target_ref="title"),
                AppearNode(target_ref="ghost"),
            ]
        ),
    )

    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())

    assert exc.value.code == "dangling_ref"


def test_appeared_visuals_in_separate_layout_trees_are_rejected():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                RowNode(children=[LabelNode(ref="left", text="Left")]),
                ColumnNode(children=[LabelNode(ref="right", text="Right")]),
                AppearNode(target_ref="left"),
                AppearNode(target_ref="right"),
            ]
        ),
    )

    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())

    assert exc.value.code == "missing_shared_layout"


def test_parallel_rejects_control_flow_steps():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="a", text="a"),
                ParallelNode(
                    steps=[
                        AppearNode(target_ref="a"),
                        SequenceNode(
                            steps=[
                                LabelNode(ref="c", text="c"),
                                WaitNode(seconds=1),
                            ]
                        ),
                    ]
                ),
            ]
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "invalid_parallel_step"


def test_total_duration_limit_enforced():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(steps=[WaitNode(seconds=5) for _ in range(10)]),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "total_duration_exceeded"


def test_version_one_static_document_remains_loadable():
    document = AnimationDocument(
        animation_version=1,
        root=LabelNode(ref="caption", text="{legacy_value}"),
    )
    compiled = compile_animation_document(document, known_fields=frozenset({"legacy_value"}))
    assert compiled.refs == {"caption"}
    assert compiled.answer_expressions == ()


def test_version_one_rejects_version_two_visual_nodes():
    document = AnimationDocument(
        animation_version=1,
        root=ExpressionLabelNode(
            expression=FieldRefNode(field="n"),
            role="answer",
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"n"}))
    assert exc.value.code == "unsupported_node_for_version"


def test_version_two_compiles_expression_fields_and_records_answer_expression():
    answer = FieldRefNode(field="n")
    document = AnimationDocument(
        animation_version=2,
        root=ColumnNode(
            children=[
                ExpressionLabelNode(expression=FieldRefNode(field="n"), prefix="Value: "),
                ExpressionLabelNode(expression=answer, prefix="Answer: ", role="answer"),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset({"n"}))
    assert compiled.answer_expressions == (answer,)


def test_version_two_expression_label_rejects_unknown_field():
    document = AnimationDocument(
        animation_version=2,
        root=ExpressionLabelNode(expression=FieldRefNode(field="missing")),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"n"}))
    assert exc.value.code == "unknown_field"


def test_version_two_rejects_static_field_placeholder():
    document = AnimationDocument(
        animation_version=2,
        root=LabelNode(text="{length} cm"),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"length"}))
    assert exc.value.code == "unsupported_text_placeholder"


@pytest.mark.parametrize(
    "node",
    [
        BraceNode(target_ref="caption", text="{length} cm"),
        ExpressionLabelNode(expression=LiteralNode(value=1), prefix="{length}"),
        ExpressionLabelNode(expression=LiteralNode(value=1), suffix="{length}"),
        RectangleNode(
            length=LiteralNode(value=1),
            width=LiteralNode(value=1),
            unit="{length}",
        ),
    ],
    ids=["brace_text", "expression_label_prefix", "expression_label_suffix", "rectangle_unit"],
)
def test_version_two_rejects_field_placeholders_in_all_rendered_static_text(node):
    document = AnimationDocument(
        animation_version=2,
        root=ColumnNode(children=[LabelNode(ref="caption", text="Caption"), node]),
    )

    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"length"}))

    assert exc.value.code == "unsupported_text_placeholder"


@pytest.mark.parametrize(
    "node",
    [
        BraceNode(target_ref="caption", text="Set {2, 4}"),
        ExpressionLabelNode(expression=LiteralNode(value=1), prefix="Set {2, 4}"),
        RectangleNode(
            length=LiteralNode(value=1),
            width=LiteralNode(value=1),
            unit="{cm}",
        ),
    ],
    ids=["brace_text", "expression_label_prefix", "rectangle_unit"],
)
def test_version_two_allows_literal_braces_that_do_not_name_known_fields(node):
    document = AnimationDocument(
        animation_version=2,
        root=ColumnNode(children=[LabelNode(ref="caption", text="Caption"), node]),
    )

    compile_animation_document(document, known_fields=frozenset({"length"}))


@pytest.mark.parametrize("unknown_dimension", ["length", "width"])
def test_version_two_rectangle_rejects_unknown_dimension_expression(unknown_dimension):
    dimensions = {
        "length": LiteralNode(value=1),
        "width": LiteralNode(value=1),
    }
    dimensions[unknown_dimension] = FieldRefNode(field="missing")
    document = AnimationDocument(animation_version=2, root=RectangleNode(**dimensions))

    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"length", "width"}))

    assert exc.value.code == "unknown_field"


def test_version_two_allows_literal_set_notation_without_field_names():
    document = AnimationDocument(
        animation_version=2,
        root=LabelNode(text="Set {2, 4, 6}"),
    )
    compile_animation_document(document, known_fields=frozenset({"length"}))
