from fractions import Fraction
from math import isfinite
from types import SimpleNamespace

import pytest

from app.meta.v3.errors import V3ValidationError
from app.meta.v3.geometry import Point
from app.meta.v3.layout import SAFE_FRAME
from app.meta.v3.visual_registry import VisualRegistry, default_visual_registry


class LiteralTextMeasurer:
    # Scaled like real text: `ManimTextMeasurer` reports roughly 0.3 x 0.45 units
    # per character at the label font size. This returned 10 x 20 units per
    # character, which made a six-character label 60 units wide -- harmless while
    # nothing checked extent, but larger than the frame can hold at any scale, so
    # `_require_renderable_extent` now rejects it.
    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


class SceneTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


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


def test_default_registry_keeps_seven_value_median_inside_safe_frame():
    visual = default_visual_registry().measure(
        SimpleNamespace(kind="ordered_values", ref="values"),
        {"values": ["3", "5", "6", "8", "9", "12", "15"]},
        SceneTextMeasurer(),
        strategy="pair_elimination",
    )

    assert all(isfinite(value) for value in (
        visual.bounds.left, visual.bounds.right, visual.bounds.bottom, visual.bounds.top,
    ))
    assert visual.bounds.left >= SAFE_FRAME.left
    assert visual.bounds.right <= SAFE_FRAME.right
    assert visual.bounds.bottom >= SAFE_FRAME.bottom
    assert visual.bounds.top <= SAFE_FRAME.top


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


@pytest.mark.parametrize(
    ("kind", "values", "driver"),
    [
        ("bar", {"value": Fraction(1), "maximum": Fraction(10000)}, "maximum"),
        ("grid", {"rows": Fraction(2), "columns": Fraction(4000)}, "columns"),
        ("object_set", {"count": Fraction(20000)}, "count"),
    ],
)
def test_a_count_driven_visual_too_large_to_render_is_rejected_by_name(kind, values, driver):
    """A visual whose size comes from a number needs a ceiling.

    `_measure_bar`, `_measure_grid` and `_measure_object_set` derive their extent
    linearly from a parameter, and nothing bounded it: `MAX_NUMERIC_MAGNITUDE` is
    10**12 and no limit caps how many semantic parts a visual may measure. A bar
    with `maximum` 10000 measured 6500 units wide -- 10000 segments the renderer
    would have built as 10000 mobjects -- and surfaced only as
    `below_minimum_text_scale` at 0.002, a code about text with the hint "reduce
    visual content" for a scene holding one bar. Two generation attempts burned
    on a failure that named neither the visual nor the number driving it.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind=kind, ref="oversized"), values, LiteralTextMeasurer(),
        )

    failure = exc_info.value.failure
    assert failure.code == "visual_extent_unrenderable"
    assert "oversized" in failure.observed
    assert driver in failure.hint or driver in failure.observed


def test_a_visual_that_fits_the_frame_still_measures():
    visual = default_visual_registry().measure(
        SimpleNamespace(kind="bar", ref="bar"),
        {"value": Fraction(3), "maximum": Fraction(5)},
        LiteralTextMeasurer(),
    )

    assert visual.bounds.right - visual.bounds.left < 19


def test_an_oversized_count_is_rejected_before_the_factory_materializes_parts():
    """The extent check must not run after the parts already exist.

    `_measure_bar` builds one `SemanticPart` per segment, so validating extent
    only after the factory returned meant a `maximum` of 10**12 -- which
    `MAX_NUMERIC_MAGNITUDE` permits -- looped 10**12 times before anything
    rejected it. Measured: 2,000,000 took 1.66s, so 10**12 is days of wall time
    or an OOM inside the probe subprocess.
    """
    registry = VisualRegistry()

    def must_not_run(*, spec, values, measurer):
        raise AssertionError("the factory ran before the count was checked")

    registry.register("bar", must_not_run)

    with pytest.raises(V3ValidationError) as exc_info:
        registry.measure(
            SimpleNamespace(kind="bar", ref="huge"),
            {"value": Fraction(1), "maximum": Fraction(10**12)},
            LiteralTextMeasurer(),
        )

    assert exc_info.value.failure.code == "visual_extent_unrenderable"
    assert "maximum" in exc_info.value.failure.observed


def test_a_number_line_keeps_a_large_numeric_range():
    """`number_line.maximum` is a scale, not a count.

    Markers are placed inside fixed +/-2.75 bounds, so a line from 0 to a million
    costs nothing to draw. A preflight keyed on field NAME rather than visual kind
    would reject it, since `bar.maximum` and `number_line.maximum` share a name
    and mean entirely different things.
    """
    visual = default_visual_registry().measure(
        SimpleNamespace(kind="number_line", ref="line"),
        {"minimum": Fraction(0), "maximum": Fraction(1_000_000),
         "markers": [Fraction(250_000), Fraction(750_000)]},
        LiteralTextMeasurer(),
    )

    assert visual.bounds.right - visual.bounds.left < 19
    assert len(visual.parts) == 2
