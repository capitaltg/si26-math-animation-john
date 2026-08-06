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
        (
            "coordinate_plane", "group_reveal",
            {
                "x_min": Fraction(-3), "x_max": Fraction(5),
                "y_min": Fraction(-3), "y_max": Fraction(5),
                "points": [{"x": Fraction(2), "y": Fraction(3)}, {"x": Fraction(-1), "y": Fraction(4)}],
            },
            ("point", 1),
        ),
    ],
)
def test_default_registry_measures_literal_visuals_with_finite_root_and_child_anchors(
    kind, strategy, values, child_part
):
    visual = default_visual_registry().measure(
        SimpleNamespace(kind=kind, ref=kind, initial_role="neutral"), values, LiteralTextMeasurer(), strategy=strategy
    )

    assert all(isfinite(value) for value in (visual.bounds.left, visual.bounds.right, visual.bounds.bottom, visual.bounds.top))
    assert isinstance(visual.anchor(part=None, index=None, name="center"), Point)
    if child_part is not None:
        assert isinstance(visual.anchor(part=child_part[0], index=child_part[1], name="center"), Point)


def test_default_registry_keeps_seven_value_median_inside_safe_frame():
    visual = default_visual_registry().measure(
        SimpleNamespace(kind="ordered_values", ref="values", initial_role="neutral"),
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


def test_the_answer_visual_is_measured_at_its_widest_stage():
    """Layout has to reserve the final width, or the statement reflows mid-scene."""
    from app.meta.v3.visual_registry import default_visual_registry

    spec = type("Spec", (), {"kind": "answer_expression", "ref": "evaluated_answer"})()
    stages = {
        "unknown": "? m",
        "work": "2.75 × 1000 = ? m",
        "value": "2.75 × 1000 = 2750 m",
    }

    measured = default_visual_registry().measure(
        spec, {"stages": stages}, LiteralTextMeasurer(),
    )

    widest, _height = LiteralTextMeasurer().measure(stages["value"], "label")
    assert measured.bounds.right - measured.bounds.left == pytest.approx(widest)
    assert measured.payload["stages"] == stages


def test_the_cardinality_hint_carries_the_cap_and_an_alternative_kind():
    """The retry loop only forwards `code`, `path` and `hint`.

    `generation_pipeline.generate_and_validate_revision` builds its repair
    feedback from those three fields, so a ceiling stated only in `expected`
    never reaches the model. Two Bedrock attempts on job
    645f54b89af444fca04ea00a25d876cc both proposed `maximum=10000` unchanged,
    because "reduce the value driving this visual's size" named no target and no
    alternative -- and no value of `maximum` can draw 2750-out-of-10000 anyway.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="bar", ref="m_bar"),
            {"value": Fraction(2750), "maximum": Fraction(10000)},
            LiteralTextMeasurer(),
        )

    hint = exc_info.value.failure.hint
    assert "128" in hint
    assert "number_line" in hint
    assert "maximum" in hint


def test_a_number_line_labels_each_marker_and_reserves_room_below_the_line():
    """A line of unlabelled dots shows a position without saying what it is.

    `number_line` is the kind the cardinality hint steers a large magnitude
    towards, so it has to teach that magnitude rather than show a bare line.
    Labels are payload, not parts: nothing addresses them, and
    `test_a_number_line_keeps_a_large_numeric_range` pins the part count.
    """
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="number_line", ref="line"),
        {"minimum": Fraction(0), "maximum": Fraction(3000),
         "markers": [Fraction(0), Fraction(1500), Fraction(3000)]},
        LiteralTextMeasurer(),
    )

    assert measured.payload["marker_labels"] == ("0", "1500", "3000")
    # The label strip sits below the line's own -0.2 extent.
    assert measured.bounds.bottom < -0.2
    assert measured.payload["label_center_y"] < -0.2
    # The line's own endpoints stay at +/-2.75 -- `_line_visual` reads these
    # from payload, so bounds can widen to reserve room for endpoint labels
    # without stretching the line under them.
    assert (measured.payload["line_left"], measured.payload["line_right"]) == (-2.75, 2.75)


def test_a_number_line_rejects_markers_whose_labels_would_collide():
    """A magnitude with four evenly-spaced six-digit markers packs its labels

    onto the same strip -- adjacent labels overlap, but the inter-visual
    overlap gate compares different visuals, so a collision inside one
    number_line slipped through. Reject at measurement time; hint should
    steer the generator toward fewer markers or a wider range.
    """
    with pytest.raises(V3ValidationError) as excinfo:
        default_visual_registry().measure(
            SimpleNamespace(kind="number_line", ref="line"),
            {"minimum": Fraction(0), "maximum": Fraction(1_000_000),
             "markers": [Fraction(250_000), Fraction(500_000),
                         Fraction(750_000), Fraction(1_000_000)]},
            LiteralTextMeasurer(),
        )
    failure = excinfo.value.failure
    assert failure.code == "visual_extent_unrenderable"
    assert failure.path == "visuals.line"
    assert "overlap" in failure.observed
    # Retry only forwards code/path/hint (see draft_generation), so the
    # hint has to name the actual colliding labels and steer the generator
    # AWAY from widening the range (which packs markers closer, not apart).
    assert "'250000'" in failure.hint and "'500000'" in failure.hint
    assert "drop" in failure.hint
    assert "widening" in failure.hint


def test_a_number_line_reserves_bounds_for_a_wide_endpoint_label():
    """A "3000" label centered on the rightmost marker overhangs +2.75.

    Before, horizontal bounds stopped at the line's own extent, so layout
    tucked the next visual against the label and the two overlapped. Bounds
    must widen by the label's half-width; the line endpoints live in payload
    now so widening the strip doesn't stretch the line.
    """
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="number_line", ref="line"),
        {"minimum": Fraction(0), "maximum": Fraction(3000),
         "markers": [Fraction(0), Fraction(3000)]},
        LiteralTextMeasurer(),
    )

    label_half_width = LiteralTextMeasurer().measure("3000", "label")[0] / 2
    assert measured.bounds.right == pytest.approx(2.75 + label_half_width)
    assert measured.bounds.left == pytest.approx(-2.75 - LiteralTextMeasurer().measure("0", "label")[0] / 2)
    assert (measured.payload["line_left"], measured.payload["line_right"]) == (-2.75, 2.75)


def test_a_tape_within_cap_that_overflows_the_frame_names_the_driving_field():
    """A tape can pass the 8-box cap and still blow the frame on label width.

    `box_width = _TAPE_BOX_PADDING + max(label widths)`, so long unit words or a
    large `per_unit` overflow `_require_renderable_extent`'s frame limit well
    below 8 boxes. `_SIZE_DRIVING_FIELDS` had no entry for a tape's `value`,
    `per_unit`, `source_unit` or `target_unit`, so the failure's hint named no
    field at all -- the same dead end this branch exists to abolish, recreated
    inside the visual added to fix it.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="unit_tape", ref="t"),
            {"value": Fraction(7), "per_unit": Fraction(1000),
             "source_unit": "kilometers", "target_unit": "meters"},
            LiteralTextMeasurer(),
        )

    failure = exc_info.value.failure
    assert failure.code == "visual_extent_unrenderable"
    assert "value" in failure.hint
    assert "source_unit" in failure.hint
    assert "target_unit" in failure.hint


def test_a_bar_past_the_frame_limit_but_within_cardinality_names_only_maximum():
    """A flat, kind-agnostic driver-field list leaks a bar's unrelated `value`.

    `maximum=50` is well under the 128 cardinality cap (so
    `_require_renderable_cardinality` never fires) but past the ~29-segment
    frame-extent limit (so `_require_renderable_extent` does). `bar` also
    carries a `value` field in the same `values` dict -- the fill amount,
    which `_measure_bar` and `_CARDINALITY_FIELDS["bar"] = ("maximum",)` both
    agree has zero effect on the bar's width. A field-name list shared across
    every kind cannot tell `bar.value` (irrelevant) from `unit_tape.value`
    (very relevant) apart, so it named both.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="bar", ref="wide_bar"),
            {"value": Fraction(50), "maximum": Fraction(50)},
            LiteralTextMeasurer(),
        )

    hint = exc_info.value.failure.hint
    assert "maximum" in hint
    assert "value" not in hint


def test_a_number_line_marker_label_is_a_decimal_not_a_ratio():
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="number_line", ref="line"),
        {"minimum": Fraction(0), "maximum": Fraction(4), "markers": [Fraction(11, 4)]},
        LiteralTextMeasurer(),
    )

    assert measured.payload["marker_labels"] == ("2.75",)


def test_a_coordinate_plane_places_plotted_points_inside_a_fixed_scene_extent():
    """The M14 fixture: plot (2, 3) and (-1, 4) on a plane spanning [-3, 5].

    The plane's scene-coord extent is fixed (see COORDINATE_PLANE_HALF_WIDTH /
    _HALF_HEIGHT), so a downstream ticket that reuses the kind gets the same
    frame fraction per data point regardless of the numeric span the lesson
    declares. Both points land inside the plane's bounds and every point is
    addressable as a `point` semantic part.
    """
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(-3), "x_max": Fraction(5),
            "y_min": Fraction(-3), "y_max": Fraction(5),
            "points": [
                {"x": Fraction(2), "y": Fraction(3)},
                {"x": Fraction(-1), "y": Fraction(4)},
            ],
        },
        LiteralTextMeasurer(),
    )

    for index in (0, 1):
        part = measured.parts[("point", index)]
        assert measured.bounds.left <= part.bounds.left
        assert measured.bounds.right >= part.bounds.right
        assert measured.bounds.bottom <= part.bounds.bottom
        assert measured.bounds.top >= part.bounds.top
    labels = tuple(point["label"] for point in measured.payload["points"])
    assert labels == ("(2, 3)", "(-1, 4)")


def test_a_coordinate_plane_rejects_a_point_outside_the_declared_span():
    """A dot outside the plane would draw against the axis wall while the plan
    still claimed the fixture value was on screen. Refuse at measurement so the
    fixture author sees the mismatch."""
    with pytest.raises(ValueError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="coordinate_plane", ref="plane"),
            {
                "x_min": Fraction(0), "x_max": Fraction(4),
                "y_min": Fraction(0), "y_max": Fraction(4),
                "points": [{"x": Fraction(5), "y": Fraction(2)}],
            },
            LiteralTextMeasurer(),
        )

    assert "outside" in str(exc_info.value)


def test_a_coordinate_plane_bounded_tick_material_survives_a_trillion_wide_span():
    """A span of [0, 10**12] used to materialize every integer before the
    per-axis cap thinned the list, which exhausted process memory. The
    stride is now derived from the count before `range` is expanded, so a
    trillion-unit span resolves under the tick ceiling with no allocation
    spike. Both axes carry the same magnitude so the projected extent check
    does not reject the span."""
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(0), "x_max": Fraction(10 ** 12),
            "y_min": Fraction(0), "y_max": Fraction(10 ** 12),
            "points": [{"x": Fraction(0), "y": Fraction(0)}],
        },
        LiteralTextMeasurer(),
    )

    from app.meta.v3.visual_registry import COORDINATE_PLANE_MAX_TICKS_PER_AXIS
    assert len(measured.payload["x_ticks"]) <= COORDINATE_PLANE_MAX_TICKS_PER_AXIS


def test_a_coordinate_plane_rejects_an_imbalanced_span_that_collapses_one_axis():
    """[0, 10**12] x [0, 4] gets a uniform unit scale drawn from the x-axis,
    which pins the y-axis projected extent at ~1e-11 scene units -- every y
    coordinate lands on the same pixel row and tick thinning strips the
    y-axis labels entirely. Refuse at measurement so the fixture author
    picks compatible spans instead of shipping a blank axis."""
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="coordinate_plane", ref="plane"),
            {
                "x_min": Fraction(0), "x_max": Fraction(10 ** 12),
                "y_min": Fraction(0), "y_max": Fraction(4),
                "points": [{"x": Fraction(0), "y": Fraction(0)}],
            },
            LiteralTextMeasurer(),
        )

    assert exc_info.value.failure.code == "visual_extent_unrenderable"
    assert "collapse" in exc_info.value.failure.observed


def test_a_coordinate_plane_point_label_moves_out_of_a_tick_label_rectangle():
    """The acceptance fixture places (-1, 4) whose label rectangle sits on
    top of the y-axis tick labels 4 and 5 if it is drawn above the dot.
    The measurer now probes the four quadrants and picks one whose rect
    does not overlap any tick or prior point label, so the label offset
    for the second point is not the historical above-the-dot placement."""
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(-3), "x_max": Fraction(5),
            "y_min": Fraction(-3), "y_max": Fraction(5),
            "points": [
                {"x": Fraction(2), "y": Fraction(3)},
                {"x": Fraction(-1), "y": Fraction(4)},
            ],
        },
        LiteralTextMeasurer(),
    )

    second = measured.payload["points"][1]
    assert (second["label_dx"], second["label_dy"]) != (0.0, second["label_dy"]) or second["label_dy"] < 0
    # No point label rectangle overlaps any rendered tick label rectangle.
    point_rects = [
        (
            p["x"] + p["label_dx"] - p["label_width"] / 2,
            p["x"] + p["label_dx"] + p["label_width"] / 2,
            p["y"] + p["label_dy"] - p["label_height"] / 2,
            p["y"] + p["label_dy"] + p["label_height"] / 2,
        )
        for p in measured.payload["points"]
    ]
    zero_v = measured.payload["axis_zero_v"]
    zero_u = measured.payload["axis_zero_u"]
    from app.meta.v3.visual_registry import (
        COORDINATE_TICK_LABEL_GAP, _rects_overlap,
    )
    for tick in measured.payload["x_ticks"]:
        if not tick["label"]:
            continue
        w, h = tick["label_width"], tick["label_height"]
        u = tick["u"]
        cy = zero_v - COORDINATE_TICK_LABEL_GAP - h / 2
        tick_rect = (u - w / 2, u + w / 2, cy - h / 2, cy + h / 2)
        for pr in point_rects:
            assert not _rects_overlap(pr, tick_rect)
    for tick in measured.payload["y_ticks"]:
        if not tick["label"]:
            continue
        w, h = tick["label_width"], tick["label_height"]
        v = tick["v"]
        cx = zero_u - COORDINATE_TICK_LABEL_GAP - w / 2
        tick_rect = (cx - w / 2, cx + w / 2, v - h / 2, v + h / 2)
        for pr in point_rects:
            assert not _rects_overlap(pr, tick_rect)


def test_a_coordinate_plane_emits_grid_lines_only_when_the_grid_flag_is_set():
    """Issue #108's acceptance calls the grid optional. The payload carries
    an integer grid line for each axis unit when `grid` is true and an
    empty tuple otherwise, so a plan that does not opt in renders bare
    axes."""
    off = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(-2), "x_max": Fraction(2),
            "y_min": Fraction(-2), "y_max": Fraction(2),
            "points": [{"x": Fraction(1), "y": Fraction(1)}],
        },
        LiteralTextMeasurer(),
    )
    on = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(-2), "x_max": Fraction(2),
            "y_min": Fraction(-2), "y_max": Fraction(2),
            "points": [{"x": Fraction(1), "y": Fraction(1)}],
            "grid": True,
        },
        LiteralTextMeasurer(),
    )

    assert off.payload["grid"] is False
    assert off.payload["x_grid_lines"] == ()
    assert off.payload["y_grid_lines"] == ()
    assert on.payload["grid"] is True
    assert len(on.payload["x_grid_lines"]) == 5
    assert len(on.payload["y_grid_lines"]) == 5


def test_a_coordinate_plane_rejects_a_span_with_no_integer_tick():
    """A fractional span like [0.1, 0.9] carries no integer, so the integer
    tick generator returns an empty list -- the plane would render axes with
    no ticks or grid lines. Refuse at measurement so the fixture author fixes
    the span rather than shipping an unticked plane."""
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="coordinate_plane", ref="plane"),
            {
                "x_min": Fraction(1, 10), "x_max": Fraction(9, 10),
                "y_min": Fraction(0), "y_max": Fraction(4),
                "points": [{"x": Fraction(1, 2), "y": Fraction(2)}],
            },
            LiteralTextMeasurer(),
        )

    assert "integer" in exc_info.value.failure.observed


def test_a_coordinate_plane_rejects_duplicate_point_coordinates():
    """Two points at the same (x, y) stack their labels at one dot; the
    fallback quadrant would draw one coordinate label on top of the other."""
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="coordinate_plane", ref="plane"),
            {
                "x_min": Fraction(-3), "x_max": Fraction(5),
                "y_min": Fraction(-3), "y_max": Fraction(5),
                "points": [
                    {"x": Fraction(2), "y": Fraction(3)},
                    {"x": Fraction(2), "y": Fraction(3)},
                ],
            },
            LiteralTextMeasurer(),
        )

    assert "more than once" in exc_info.value.failure.observed


def test_a_coordinate_plane_rejects_points_that_leave_no_free_label_quadrant():
    """Three points clustered within one world unit exhaust every quadrant for
    the third label's rectangle -- the earlier fallback silently overlaid it
    on the second label. Refuse so the crowding surfaces before render."""
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="coordinate_plane", ref="plane"),
            {
                "x_min": Fraction(-3), "x_max": Fraction(5),
                "y_min": Fraction(-3), "y_max": Fraction(5),
                "points": [
                    {"x": Fraction(0), "y": Fraction(0)},
                    {"x": Fraction(1, 20), "y": Fraction(0)},
                    {"x": Fraction(0), "y": Fraction(1, 20)},
                ],
            },
            LiteralTextMeasurer(),
        )

    assert "cannot place its label" in exc_info.value.failure.observed


def test_a_coordinate_plane_point_label_avoids_the_axis_corridor():
    """A point plotted at (0, 2) has its default above-quadrant label rectangle
    centered on the y-axis stroke; the picker used to only avoid tick labels
    and prior point labels, so the label rendered on top of the axis.
    Placement now treats the axis as a corridor obstacle so a non-crossing
    quadrant is chosen instead."""
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(-3), "x_max": Fraction(5),
            "y_min": Fraction(-3), "y_max": Fraction(5),
            "points": [{"x": Fraction(0), "y": Fraction(2)}],
        },
        LiteralTextMeasurer(),
    )

    from app.meta.v3.visual_registry import (
        COORDINATE_PLANE_AXIS_STROKE_HALF,
        _rects_overlap,
    )
    payload = measured.payload
    p = payload["points"][0]
    y_axis_rect = (
        payload["axis_zero_u"] - COORDINATE_PLANE_AXIS_STROKE_HALF,
        payload["axis_zero_u"] + COORDINATE_PLANE_AXIS_STROKE_HALF,
        -payload["extent_y"], payload["extent_y"],
    )
    label_rect = (
        p["x"] + p["label_dx"] - p["label_width"] / 2,
        p["x"] + p["label_dx"] + p["label_width"] / 2,
        p["y"] + p["label_dy"] - p["label_height"] / 2,
        p["y"] + p["label_dy"] + p["label_height"] / 2,
    )
    assert not _rects_overlap(label_rect, y_axis_rect)


def test_a_coordinate_plane_point_label_avoids_covering_other_dots():
    """Two points at the same x with y one apart -- (3, 2) and (3, 3) -- have
    above-quadrant label rectangles that cover the neighbouring dot because
    labels render above dots. Placement now checks every other point's dot
    as an obstacle, so a non-covering quadrant wins."""
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="coordinate_plane", ref="plane"),
        {
            "x_min": Fraction(-5), "x_max": Fraction(5),
            "y_min": Fraction(-5), "y_max": Fraction(5),
            "points": [
                {"x": Fraction(3), "y": Fraction(2)},
                {"x": Fraction(3), "y": Fraction(3)},
            ],
        },
        LiteralTextMeasurer(),
    )

    from app.meta.v3.visual_registry import (
        COORDINATE_PLANE_DOT_RADIUS,
        _rects_overlap,
    )
    payload = measured.payload
    dot_rects = [
        (
            p["x"] - COORDINATE_PLANE_DOT_RADIUS,
            p["x"] + COORDINATE_PLANE_DOT_RADIUS,
            p["y"] - COORDINATE_PLANE_DOT_RADIUS,
            p["y"] + COORDINATE_PLANE_DOT_RADIUS,
        )
        for p in payload["points"]
    ]
    for index, p in enumerate(payload["points"]):
        label_rect = (
            p["x"] + p["label_dx"] - p["label_width"] / 2,
            p["x"] + p["label_dx"] + p["label_width"] / 2,
            p["y"] + p["label_dy"] - p["label_height"] / 2,
            p["y"] + p["label_dy"] + p["label_height"] / 2,
        )
        for other_index, dot_rect in enumerate(dot_rects):
            if other_index == index:
                continue
            assert not _rects_overlap(label_rect, dot_rect)


def test_a_coordinate_plane_rejects_a_point_whose_label_cannot_clear_the_axes():
    """Point (0, 0) sits at the axis intersection: every candidate quadrant
    rect straddles either the x-axis or the y-axis. With axis corridors
    treated as hard obstacles the plane refuses, so a fixture that plots
    directly on the origin surfaces the problem instead of rendering glyphs
    stacked on the axis stroke."""
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="coordinate_plane", ref="plane"),
            {
                "x_min": Fraction(-3), "x_max": Fraction(3),
                "y_min": Fraction(-3), "y_max": Fraction(3),
                "points": [{"x": Fraction(0), "y": Fraction(0)}],
            },
            LiteralTextMeasurer(),
        )

    assert exc_info.value.failure.code == "visual_extent_unrenderable"
