from fractions import Fraction
from math import isfinite
from types import SimpleNamespace

import pytest

from app.meta.v3.errors import V3ValidationError
from app.meta.v3.geometry import Point
from app.meta.v3.visual_registry import default_visual_registry


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 10, 20


@pytest.mark.parametrize(
    ("kind", "strategy", "values", "child_part"),
    [
        ("ordered_values", "pair_elimination", {"values": ["3", "5", "8"]}, ("item", 1)),
        ("rectangle_measurement", "boundary_trace", {"length": Fraction(8), "width": Fraction(3), "unit": "cm"}, ("edge", 0)),
        ("number_line", "magnitude_comparison", {"minimum": Fraction(0), "maximum": Fraction(10), "markers": [Fraction(4)]}, ("marker", 0)),
        ("grid", "regroup", {"rows": 2, "columns": 3}, ("cell", 5)),
        ("partition", "partition", {"whole": Fraction(8), "parts": 4}, ("partition", 3)),
        ("bar", "magnitude_comparison", {"value": Fraction(3), "maximum": Fraction(5)}, ("segment", 4)),
        ("object_set", "group_reveal", {"count": 6}, ("item", 5)),
        ("label", "group_reveal", {"text": "Answer"}, None),
    ],
)
def test_default_registry_measures_literal_visuals_with_finite_root_and_child_anchors(
    kind, strategy, values, child_part
):
    visual = default_visual_registry().measure(
        SimpleNamespace(kind=kind, ref=kind), values, LiteralTextMeasurer(), strategy=strategy
    )

    assert all(isfinite(value) for value in (visual.bounds.left, visual.bounds.right, visual.bounds.bottom, visual.bounds.top))
    assert isinstance(visual.anchor(part=None, index=None, name="center"), Point)
    if child_part is not None:
        assert isinstance(visual.anchor(part=child_part[0], index=child_part[1], name="center"), Point)


def test_registry_rejects_unsupported_strategy_kind_pair_with_structured_failure():
    visual = SimpleNamespace(kind="rectangle_measurement", ref="rectangle_measurement")

    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            visual,
            {"length": Fraction(8), "width": Fraction(3), "unit": "cm"},
            LiteralTextMeasurer(),
            strategy="pair_elimination",
        )

    assert exc_info.value.failure.code == "incompatible_strategy"
    assert exc_info.value.failure.path == "strategy"
    assert exc_info.value.failure.expected == "a strategy supported by the visual kind"
    assert exc_info.value.failure.observed == "pair_elimination:rectangle_measurement"
    assert exc_info.value.failure.hint == "select a compatible strategy"
