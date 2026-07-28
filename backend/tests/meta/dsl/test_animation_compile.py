import pytest

from app.meta.dsl.animation import (
    AnimationDocument,
    AppearNode,
    ArrowNode,
    HighlightNode,
    LabelNode,
    NumberLineNode,
    ObjectSetNode,
    ParallelNode,
    RowNode,
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
        root=RowNode(
            children=[
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
        root=RowNode(
            children=[
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


def test_parallel_containing_sequence_with_producing_step_is_fine():
    # The guard is about parallel's *direct* children only. A parallel step that
    # is itself a sequence containing a producing-kind node is fine, since the
    # inner sequence returns None to build_parallel (it doesn't route the
    # producing node's return value into scene.play).
    document = AnimationDocument(
        animation_version=1,
        root=RowNode(
            children=[
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
    compiled = compile_animation_document(document, known_fields=frozenset())
    assert compiled.refs == {"a", "c"}


def test_total_duration_limit_enforced():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(steps=[WaitNode(seconds=5) for _ in range(10)]),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "total_duration_exceeded"
