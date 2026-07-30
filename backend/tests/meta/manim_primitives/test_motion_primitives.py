import pytest
from manim import Dot, FadeIn, Indicate, MoveAlongPath, Transform

from app.meta.manim_primitives.motions import (
    build_appear,
    build_camera_focus,
    build_highlight,
    build_move_along_path,
    build_role_transition,
    build_transform,
    build_wait,
)
from app.meta.manim_primitives.style import resolve_semantic_style


def test_build_appear_returns_fade_in():
    animation = build_appear(Dot())
    assert isinstance(animation, FadeIn)


def test_build_highlight_returns_indicate():
    animation = build_highlight(Dot())
    assert isinstance(animation, Indicate)


def test_build_transform_returns_transform_between_mobjects():
    source, target = Dot(), Dot().shift([1, 0, 0])
    animation = build_transform(source, target)
    assert isinstance(animation, Transform)
    assert animation.mobject is source
    assert animation.target_mobject is target


def test_build_move_along_path_returns_move_along_path():
    from manim import Line

    mobject, path = Dot(), Line([0, 0, 0], [1, 0, 0])
    animation = build_move_along_path(mobject, path)
    assert isinstance(animation, MoveAlongPath)


def test_build_role_transition_returns_a_bounded_transform():
    animation = build_role_transition(Dot(), resolve_semantic_style("ocean", "focus"))
    assert isinstance(animation, Transform)


def test_build_wait_calls_scene_wait():
    calls = []

    class _StubScene:
        def wait(self, seconds):
            calls.append(seconds)

    build_wait(_StubScene(), 2.5)
    assert calls == [2.5]


def test_build_camera_focus_requires_moving_camera_scene():
    class _PlainStubScene:
        pass

    with pytest.raises(TypeError):
        build_camera_focus(_PlainStubScene(), Dot())
