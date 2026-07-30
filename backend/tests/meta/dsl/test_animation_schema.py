import pytest
from pydantic import ValidationError

from app.meta.dsl.animation import (
    AnimationDocument,
    AppearNode,
    ExpressionLabelNode,
    LabelNode,
    NumberLineNode,
    RectangleNode,
    RowNode,
    SequenceNode,
    WaitNode,
)
from app.meta.dsl.expression import FieldRefNode, LiteralNode


def test_valid_document_parses():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                RowNode(
                    children=[
                        NumberLineNode(
                            ref="line",
                            minimum=LiteralNode(value=0),
                            maximum=LiteralNode(value=10),
                            marker_value=LiteralNode(value=4),
                        ),
                        LabelNode(text="4 apples"),
                    ]
                ),
                AppearNode(target_ref="line"),
                WaitNode(seconds=1),
            ]
        ),
    )
    assert document.root.steps[0].children[0].ref == "line"


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        AnimationDocument.model_validate(
            {"animation_version": 1, "root": {"kind": "teleport"}}
        )


def test_extra_key_rejected():
    with pytest.raises(ValidationError):
        WaitNode.model_validate({"kind": "wait", "seconds": 1, "sneaky": True})


def test_wait_seconds_bounded():
    with pytest.raises(ValidationError):
        WaitNode(seconds=10)
    with pytest.raises(ValidationError):
        WaitNode(seconds=0)


def test_label_text_length_bounded():
    with pytest.raises(ValidationError):
        LabelNode(text="x" * 500)


def test_style_token_is_closed_enum():
    with pytest.raises(ValidationError):
        NumberLineNode(
            minimum=LiteralNode(value=0),
            maximum=LiteralNode(value=10),
            marker_value=LiteralNode(value=4),
            style="neon",
        )


def test_expression_label_schema_accepts_bounded_dynamic_text():
    node = ExpressionLabelNode(
        ref="answer",
        expression=FieldRefNode(field="n"),
        prefix="= ",
        suffix=" cm",
        role="answer",
        style="success",
    )
    assert node.kind == "expression_label"
    assert node.role == "answer"


def test_rectangle_schema_accepts_expression_dimensions():
    node = RectangleNode(
        ref="diagram",
        length=FieldRefNode(field="length"),
        width=FieldRefNode(field="width"),
        unit="cm",
    )
    assert node.kind == "rectangle"
    assert node.unit == "cm"
