from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.meta.v3.geometry import Bounds, MeasuredVisual, Point, SemanticPart
from app.meta.v3.ordered_values import measure_ordered_values
from app.meta.v3.visual_registry import VisualRegistry


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        widths = {"3": 10, "5": 10, "6": 10, "8": 10, "9": 10, "12": 22, "15": 22}
        return widths[text], 20


def test_median_item_anchor_uses_eight_bounds_not_row_center():
    visual = measure_ordered_values(
        ref="values",
        values=["3", "5", "6", "8", "9", "12", "15"],
        measurer=LiteralTextMeasurer(),
        gap=8,
        initial_role="neutral",
    )
    item_bottom = visual.anchor(part="item", index=3, name="bottom")
    row_bottom = visual.anchor(part=None, index=None, name="bottom")
    assert item_bottom.x != row_bottom.x
    assert item_bottom.x == visual.parts[("item", 3)].bounds.center.x


def test_measured_geometry_rejects_mutation_and_defensively_copies_inputs():
    parts = {("item", 0): SemanticPart("item", 0, Bounds(0, 10, -5, 5))}
    paths = {"trace": [Point(0, 0), Point(1, 1)]}
    visual = MeasuredVisual(
        ref="values",
        bounds=Bounds(0, 10, -5, 5),
        parts=parts,
        paths=paths,
        payload={"values": ("3",)},
    )

    parts.clear()
    paths["trace"].append(Point(2, 2))

    assert ("item", 0) in visual.parts
    assert visual.paths["trace"] == (Point(0, 0), Point(1, 1))
    with pytest.raises(TypeError):
        visual.parts[("item", 1)] = visual.parts[("item", 0)]
    with pytest.raises(TypeError):
        visual.paths["trace"] = ()
    with pytest.raises(AttributeError):
        visual.paths["trace"].append(Point(2, 2))
    with pytest.raises(FrozenInstanceError):
        visual.bounds = Bounds(0, 20, -5, 5)


def test_measured_payload_carries_the_declared_initial_role():
    measured = measure_ordered_values(
        ref="values", values=["3", "5", "8"], measurer=LiteralTextMeasurer(),
        gap=0.45, initial_role="structure",
    )
    assert measured.payload["initial_role"] == "structure"


def test_visual_registry_rejects_duplicate_kinds():
    registry = VisualRegistry()
    registry.register("ordered_values", lambda **kwargs: None)

    with pytest.raises(ValueError, match="duplicate visual kind ordered_values"):
        registry.register("ordered_values", lambda **kwargs: None)


def test_visual_registry_rejects_unknown_kinds():
    registry = VisualRegistry()

    with pytest.raises(ValueError, match="unknown semantic visual missing"):
        registry.measure(SimpleNamespace(kind="missing"), [], None)
