import pytest
from manim import Dot, Square, Text

from app.meta.dsl.animation import (
    AnimationDocument,
    AppearNode,
    ArrowNode,
    ExpressionLabelNode,
    LabelNode,
    NumberLineNode,
    ObjectSetNode,
    ParallelNode,
    RectangleNode,
    RowNode,
    SequenceNode,
    WaitNode,
    compile_animation_document,
)
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode, FractionNode, LiteralNode
from app.meta.dynamic_scene import DynamicTemplateScene, render_animation_node


class _StubScene:
    def __init__(self):
        self.played = []
        self.waited = []

    def play(self, *animations):
        self.played.append(animations)

    def wait(self, seconds):
        self.waited.append(seconds)


def test_render_row_of_visuals_populates_mobjects_by_ref():
    document = AnimationDocument(
        animation_version=1,
        root=RowNode(
            children=[
                NumberLineNode(
                    ref="line", minimum=LiteralNode(value=0), maximum=LiteralNode(value=10),
                    marker_value=FieldRefNode(field="value"),
                ),
                LabelNode(ref="caption", text="four"),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset({"value"}))
    scene = _StubScene()
    mobjects = {}
    render_animation_node(scene, compiled.document.root, {"value": 4}, mobjects)
    assert "line" in mobjects and "caption" in mobjects


def test_render_sequence_plays_appear_then_waits():
    document = AnimationDocument(
        animation_version=1,
        root=SequenceNode(
            steps=[
                LabelNode(ref="caption", text="hi"),
                AppearNode(target_ref="caption"),
                WaitNode(seconds=1),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset())
    scene = _StubScene()
    render_animation_node(scene, compiled.document.root, {}, {})
    assert len(scene.played) == 1
    assert scene.waited == [1]


def test_render_arrow_connects_previously_built_refs():
    document = AnimationDocument(
        animation_version=1,
        root=RowNode(
            children=[
                LabelNode(ref="a", text="a"),
                LabelNode(ref="b", text="b"),
                ArrowNode(from_ref="a", to_ref="b"),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset())
    scene = _StubScene()
    mobjects = {}
    render_animation_node(scene, compiled.document.root, {}, mobjects)
    assert "a" in mobjects and "b" in mobjects


def test_parallel_batches_steps_into_single_play_call():
    # Two AppearNodes over two already-built visuals must fire in ONE scene.play
    # (batched), not two sequential plays.
    mobjects = {"a": Dot(), "b": Square()}
    node = ParallelNode(steps=[AppearNode(target_ref="a"), AppearNode(target_ref="b")])
    scene = _StubScene()
    render_animation_node(scene, node, {}, mobjects)
    assert len(scene.played) == 1
    assert len(scene.played[0]) == 2


def test_resolve_rejects_non_integer_fraction():
    # object_set count evaluating to 9/2 must raise, not silently truncate to 4.
    node = ObjectSetNode(count=FractionNode(operands=[LiteralNode(value=9), LiteralNode(value=2)]))
    scene = _StubScene()
    with pytest.raises(DslValidationError) as exc:
        render_animation_node(scene, node, {}, {})
    assert exc.value.code == "non_integer_value"


def test_render_expression_label_displays_evaluated_integer():
    node = ExpressionLabelNode(
        ref="answer",
        expression=FieldRefNode(field="n"),
        prefix="Answer: ",
        suffix=" cm",
        role="answer",
    )
    mobjects = {}
    render_animation_node(_StubScene(), node, {"n": 22}, mobjects)
    assert isinstance(mobjects["answer"], Text)
    assert mobjects["answer"].original_text == "Answer: 22 cm"


def test_render_expression_label_displays_fraction_without_float_rounding():
    node = ExpressionLabelNode(
        ref="answer",
        expression=FractionNode(operands=[LiteralNode(value=3), LiteralNode(value=4)]),
        role="answer",
    )
    mobjects = {}
    render_animation_node(_StubScene(), node, {}, mobjects)
    assert mobjects["answer"].original_text == "3/4"


def test_render_rectangle_uses_evaluated_dimensions():
    node = RectangleNode(
        ref="diagram",
        length=FieldRefNode(field="length"),
        width=FieldRefNode(field="width"),
        unit="cm",
    )
    mobjects = {}
    render_animation_node(_StubScene(), node, {"length": 8, "width": 3}, mobjects)
    texts = [
        child.original_text
        for child in mobjects["diagram"].submobjects
        if isinstance(child, Text)
    ]
    assert "8 cm" in texts
    assert "3 cm" in texts


def test_scene_requires_scene_program_and_values():
    scene = DynamicTemplateScene()
    with pytest.raises(ValueError):
        scene.construct()
