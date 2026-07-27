import pytest
from manim import Dot, Square, Text

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
from app.meta.dsl.expression import FieldRefNode, LiteralNode
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


def test_scene_requires_compiled_animation_and_values():
    scene = DynamicTemplateScene()
    with pytest.raises(ValueError):
        scene.construct()
