from fractions import Fraction

import pytest

from app.meta.v3.rectangle_measurement import measure_rectangle


def test_rectangle_exposes_edge_pairs_and_closed_perimeter_path():
    visual = measure_rectangle(
        ref="rectangle", length=Fraction(8), width=Fraction(3), unit="cm",
        measurer=_WidthPerCharacterMeasurer(),
    )
    assert visual.parts[("length_edge", 0)].bounds.center.y < 0
    assert visual.parts[("length_edge", 1)].bounds.center.y > 0
    assert visual.parts[("width_edge", 0)].bounds.center.x < 0
    assert visual.parts[("width_edge", 1)].bounds.center.x > 0
    path = visual.paths["perimeter"]
    assert path[0] == path[-1]
    assert len(path) == 5


def test_rectangle_exposes_directed_edges_and_vertex_anchors():
    visual = measure_rectangle(
        ref="rectangle", length=Fraction(8), width=Fraction(3), unit="cm",
        measurer=_WidthPerCharacterMeasurer(),
    )

    assert set(("edge", index) for index in range(4)) <= visual.parts.keys()
    assert set(("vertex", index) for index in range(4)) <= visual.parts.keys()
    assert visual.anchor(part="vertex", index=0, name="center") == visual.paths["perimeter"][0]
    assert visual.anchor(part="vertex", index=3, name="center") == visual.paths["perimeter"][3]


class _WidthPerCharacterMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.25, 0.4


def test_rectangle_measures_its_dimension_labels_outside_the_edges_they_name():
    """The length and width must be measured as real text sitting outside the shape.

    `length`, `width` and `unit` reached the renderer only as payload numbers
    used to size the box, so a `rectangle_measurement` lesson drew a rectangle
    whose dimensions appeared nowhere -- a perimeter lesson with no visible
    measurements to add. Measuring them here is what makes layout reserve their
    space, rather than the renderer drawing text into a box nobody accounted for.
    """
    visual = measure_rectangle(
        ref="rectangle", length=Fraction(8), width=Fraction(3), unit="cm",
        measurer=_WidthPerCharacterMeasurer(),
    )

    length_label = visual.parts[("length_label", 0)].bounds
    width_label = visual.parts[("width_label", 0)].bounds
    bottom_edge = visual.parts[("length_edge", 0)].bounds
    left_edge = visual.parts[("width_edge", 0)].bounds
    # The length labels the bottom edge, so it sits below it; the width labels
    # the left edge, so it sits to the left of it.
    assert length_label.top <= bottom_edge.bottom
    assert width_label.right <= left_edge.left
    # And the visual's own bounds must contain both, or layout reserves a box
    # smaller than what gets drawn.
    assert visual.bounds.bottom <= length_label.bottom
    assert visual.bounds.left <= width_label.left


def test_rectangle_dimension_labels_carry_the_value_and_unit():
    visual = measure_rectangle(
        ref="rectangle", length=Fraction(8), width=Fraction(3), unit="cm",
        measurer=_WidthPerCharacterMeasurer(),
    )

    assert visual.payload["length_label"] == "8 cm"
    assert visual.payload["width_label"] == "3 cm"


@pytest.mark.parametrize("length,width", [(Fraction(0), Fraction(1)), (Fraction(1), Fraction(-1))])
def test_rectangle_rejects_non_positive_dimensions(length, width):
    with pytest.raises(ValueError, match="rectangle dimensions must be positive"):
        measure_rectangle(
            ref="rectangle", length=length, width=width, unit="cm",
            measurer=_WidthPerCharacterMeasurer(),
        )
