from fractions import Fraction

import pytest

from app.meta.v3.rectangle_measurement import measure_rectangle


def test_rectangle_exposes_edge_pairs_and_closed_perimeter_path():
    visual = measure_rectangle(
        ref="rectangle", length=Fraction(8), width=Fraction(3), unit="cm"
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
        ref="rectangle", length=Fraction(8), width=Fraction(3), unit="cm"
    )

    assert set(("edge", index) for index in range(4)) <= visual.parts.keys()
    assert set(("vertex", index) for index in range(4)) <= visual.parts.keys()
    assert visual.anchor(part="vertex", index=0, name="center") == visual.paths["perimeter"][0]
    assert visual.anchor(part="vertex", index=3, name="center") == visual.paths["perimeter"][3]


@pytest.mark.parametrize("length,width", [(Fraction(0), Fraction(1)), (Fraction(1), Fraction(-1))])
def test_rectangle_rejects_non_positive_dimensions(length, width):
    with pytest.raises(ValueError, match="rectangle dimensions must be positive"):
        measure_rectangle(ref="rectangle", length=length, width=width, unit="cm")
