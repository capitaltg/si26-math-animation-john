from manim import DOWN, LEFT, RIGHT, UP, Square, config

from app.meta.manim_primitives.layout import (
    build_align,
    build_column,
    build_overlay,
    build_padding,
    build_parallel,
    build_row,
    build_sequence,
)


def test_build_row_arranges_left_to_right_without_overlap():
    a, b = Square(side_length=1), Square(side_length=1)
    group = build_row([a, b], gap=0.5)
    assert b.get_left()[0] > a.get_right()[0] - 1e-6


def test_build_column_arranges_top_to_bottom_without_overlap():
    a, b = Square(side_length=1), Square(side_length=1)
    group = build_column([a, b], gap=0.5)
    assert a.get_bottom()[1] > b.get_top()[1] - 1e-6


def test_build_overlay_centers_children_on_same_point():
    a, b = Square(side_length=1), Square(side_length=2)
    build_overlay([a, b])
    assert list(a.get_center()) == list(b.get_center())


def test_build_align_moves_to_named_edge():
    square = Square(side_length=1)
    build_align(square, "left")
    safe_left = -config.frame_width / 2
    assert abs(square.get_left()[0] - safe_left) < 1.0


def test_build_padding_shrinks_child_slightly():
    square = Square(side_length=2)
    original_width = square.width
    build_padding(square, amount=0.25)
    assert square.width < original_width


def test_build_sequence_calls_steps_in_order_and_waits():
    calls = []

    class _StubScene:
        def wait(self, duration):
            calls.append(("wait", duration))

    build_sequence(_StubScene(), [lambda: calls.append(("a",)), lambda: calls.append(("b",))], step_duration=0.5)
    assert calls == [("a",), ("wait", 0.5), ("b",), ("wait", 0.5)]


def test_build_parallel_plays_all_returned_animations_together():
    played = []

    class _StubScene:
        def play(self, *animations):
            played.append(animations)

    from manim import FadeIn

    square = Square()
    build_parallel(_StubScene(), [lambda: FadeIn(square), lambda: FadeIn(square)])
    assert len(played) == 1
    assert len(played[0]) == 2
