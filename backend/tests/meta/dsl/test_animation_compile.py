import pytest

from app.meta.dsl.animation import (
    AnimationDocument,
    AppearNode,
    ArrowNode,
    LabelNode,
    NumberLineNode,
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


def test_total_duration_limit_enforced():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(steps=[WaitNode(seconds=5) for _ in range(10)]),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code == "total_duration_exceeded"
