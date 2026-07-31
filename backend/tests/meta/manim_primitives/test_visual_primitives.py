from fractions import Fraction

import pytest
from manim import Dot, Line, Rectangle, Text

from app.meta.manim_primitives.visuals import (
    build_arrow,
    build_bar,
    build_brace,
    build_rectangle,
    build_grid,
    build_label,
    build_number_line,
    build_object_set,
    build_shape_partition,
    build_tally_marks,
    format_expression_value,
)


def test_build_number_line_places_marker_at_value():
    group = build_number_line(minimum=0, maximum=10, marker_value=4)
    line, marker = group[0], group[1]
    assert marker.get_center()[0] == pytest.approx(line.number_to_point(4)[0], abs=1e-6)


def test_build_grid_creates_rows_times_cols_squares():
    group = build_grid(rows=2, cols=3)
    assert len(group.submobjects) == 6


def test_build_bar_colors_only_filled_cells():
    group = build_bar(filled=2, total=5)
    assert len(group.submobjects) == 5


def test_build_object_set_creates_count_dots():
    group = build_object_set(count=7)
    dots = [m for m in group.submobjects if isinstance(m, Dot)]
    assert len(dots) == 7


def test_build_shape_partition_creates_parts_wedges():
    group = build_shape_partition(parts=4, shaded=1)
    assert len(group.submobjects) == 4


def test_build_shape_partition_rejects_shaded_over_parts():
    with pytest.raises(ValueError):
        build_shape_partition(parts=4, shaded=5)


def test_build_arrow_connects_two_mobjects():
    start, end = Dot(), Dot().shift([3, 0, 0])
    arrow = build_arrow(start, end)
    assert arrow.get_start()[0] == pytest.approx(start.get_center()[0], abs=1e-6)
    assert arrow.get_end()[0] == pytest.approx(end.get_center()[0], abs=1e-6)


def test_build_brace_labels_target():
    target = Dot()
    group = build_brace(target, text="4 items")
    texts = [m for m in group.submobjects if isinstance(m, Text)]
    assert texts[0].original_text == "4 items"


def test_build_tally_marks_groups_by_five():
    group = build_tally_marks(count=7)
    lines = [m for m in group.submobjects if isinstance(m, Line)]
    assert len(lines) == 7


def test_build_label_creates_text():
    label = build_label("hello")
    assert isinstance(label, Text)
    assert label.original_text == "hello"


def test_format_expression_value_preserves_integer_and_fraction():
    assert format_expression_value(Fraction(22, 1)) == "22"
    assert format_expression_value(Fraction(3, 4)) == "3/4"


def test_build_rectangle_preserves_ratio_and_labels_dimensions():
    group = build_rectangle(Fraction(8), Fraction(3), unit="cm")
    shapes = [m for m in group.submobjects if isinstance(m, Rectangle)]
    texts = [m.original_text for m in group.submobjects if isinstance(m, Text)]
    assert len(shapes) == 1
    assert shapes[0].width / shapes[0].height == pytest.approx(8 / 3, rel=0.02)
    assert "8 cm" in texts
    assert "3 cm" in texts


@pytest.mark.parametrize(
    ("length", "width", "expected_ratio", "expected_labels"),
    [
        (
            Fraction(1),
            Fraction(1, 10**400),
            4.0,
            {"1 cm", f"1/{10**400} cm"},
        ),
        (
            Fraction(1, 10**400),
            Fraction(1),
            0.25,
            {f"1/{10**400} cm", "1 cm"},
        ),
    ],
)
def test_build_rectangle_clamps_extreme_ratios_without_losing_exact_dimension_labels(
    length, width, expected_ratio, expected_labels
):
    group = build_rectangle(length, width, unit="cm")
    rectangle = next(mobject for mobject in group.submobjects if isinstance(mobject, Rectangle))
    labels = {mobject.original_text for mobject in group.submobjects if isinstance(mobject, Text)}

    assert rectangle.width / rectangle.height == pytest.approx(expected_ratio, rel=0.02)
    assert labels == expected_labels


@pytest.mark.parametrize(
    ("length", "width"),
    [(Fraction(0), Fraction(3)), (Fraction(8), Fraction(-1))],
)
def test_build_rectangle_rejects_non_positive_dimensions(length, width):
    with pytest.raises(ValueError, match="positive"):
        build_rectangle(length, width)
