from fractions import Fraction
from math import ceil, cos, floor, isfinite, sin, tau
from typing import Protocol

from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.expression_display import format_number
from app.meta.v3.geometry import Bounds, SemanticPart
from app.meta.v3.layout import INSTRUCTIONAL_FRAME, MIN_TEXT_SCALE, SAFE_FRAME
from app.meta.v3.geometry import MeasuredVisual, TextMeasurer
from app.meta.v3.ordered_values import measure_ordered_values
from app.meta.v3.rectangle_measurement import measure_rectangle


class VisualFactory(Protocol):
    def __call__(self, *, spec, values, measurer: TextMeasurer) -> MeasuredVisual:
        raise NotImplementedError


class VisualRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, kind, factory):
        if kind in self._factories:
            raise ValueError(f"duplicate visual kind {kind}")
        self._factories[kind] = factory

    def measure(self, spec, values, measurer, *, strategy=None):
        try:
            factory = self._factories[spec.kind]
        except KeyError as exc:
            raise ValueError(f"unknown semantic visual {spec.kind}") from exc
        if strategy is not None and strategy not in _SUPPORTED_STRATEGIES[spec.kind]:
            raise V3ValidationError(
                V3Failure(
                    code="incompatible_strategy",
                    path="strategy",
                    expected="a strategy supported by the visual kind",
                    observed=f"{strategy}:{spec.kind}",
                    hint="select a compatible strategy",
                )
            )
        # Before the factory: a count-driven factory builds one part per unit, so
        # an oversized count has to be refused while it is still a number.
        _require_renderable_cardinality(spec, values)
        measured = factory(spec=spec, values=values, measurer=measurer)
        _require_renderable_extent(spec.kind, measured, values)
        return measured


_SUPPORTED_STRATEGIES = {
    "ordered_values": {"group_reveal", "short_stagger", "pair_elimination"},
    "rectangle_measurement": {"group_reveal", "boundary_trace"},
    "number_line": {"group_reveal", "short_stagger", "magnitude_comparison"},
    "grid": {"group_reveal", "short_stagger", "regroup"},
    "partition": {"group_reveal", "partition"},
    "bar": {"group_reveal", "short_stagger", "magnitude_comparison"},
    "object_set": {"group_reveal", "short_stagger", "regroup"},
    "label": {"group_reveal"},
    "unit_tape": {"group_reveal", "unit_substitution", "unit_rate"},
    "coordinate_plane": {"group_reveal"},
}


#: Per KIND, the fields whose value sets a visual's size, so a failure can name
#: the number (or string) to change rather than telling a reviewer to "reduce
#: visual content". Keyed by kind for the same reason `_CARDINALITY_FIELDS`
#: below is: the same field name means different things on different kinds.
#: `bar` also carries its own `value` field (the fill amount, in the same
#: `values` dict as `maximum`), which `_measure_bar` never reads when sizing
#: the bar -- only `maximum` does -- so a flat, kind-agnostic field-name list
#: named `value` as a driver alongside `maximum` for every oversized bar. A
#: tape's width comes from its box count (`value`) AND the widest label, which
#: is set by `per_unit`, `source_unit` and `target_unit` -- so a within-cap
#: tape can still overflow the frame on unit text alone, and the field to
#: shorten is one of these two strings rather than a count.
_SIZE_DRIVING_FIELDS = {
    "bar": ("maximum",),
    "grid": ("rows", "columns"),
    "object_set": ("count",),
    "partition": ("parts",),
    "ordered_values": ("values",),
    "unit_tape": ("value", "per_unit", "source_unit", "target_unit"),
}

#: Per KIND, the fields that decide how many semantic parts a factory builds.
#: Keyed by kind rather than by field name because the same name means different
#: things: `bar.maximum` is a segment count, while `number_line.maximum` is a
#: numeric scale whose markers land inside fixed +/-2.75 bounds -- a line from 0
#: to a million costs nothing to draw and must not be rejected. `ordered_values`
#: and `number_line` bound their lists in the plan schema already.
_CARDINALITY_FIELDS = {
    "bar": ("maximum",),
    "grid": ("rows", "columns"),
    "object_set": ("count",),
    "partition": ("parts",),
}

#: Per KIND, part classes that are NOT on screen when the whole visual is
#: revealed. The renderer keeps them out of the visual's root group, so they
#: arrive by their own reveal -- which means the "revealing a visual reveals its
#: parts" rule that `beat_expander._is_revealed` and `quality.check_repeated_reveal`
#: both apply has to make an exception for them.
DEFERRED_PARTS = {"unit_tape": ("target_label",)}

#: One box per whole unit stops being legible past this, and a ninth box would
#: not fit the 18.9-unit width limit with both labels inside it. `number_line`
#: covers larger magnitudes.
MAX_TAPE_BOXES = 8

#: Per KIND, the field a reviewer would change, its cap, and how the part count
#: is derived from that field's value. Separate from `_CARDINALITY_FIELDS`
#: because a tape's count is ceil(value): the number to name in the failure and
#: the number to compare against the cap are different numbers.
_CARDINALITY_DERIVED = {
    "unit_tape": ("value", MAX_TAPE_BOXES, lambda value: ceil(value)),
}

#: The largest part count any kind could ever need. The tightest pitch is a bar
#: segment at 0.65 units, so the 18.9-unit width limit admits ~29; `object_set`
#: packs five per row, so the 8.6-unit height limit admits ~65. This is a
#: deliberately loose over-approximation -- its only job is to keep a factory from
#: looping past what fits, leaving `_require_renderable_extent` to decide
#: precisely.
MAX_PART_CARDINALITY = 128

_TAPE_BOX_HEIGHT = 1.1
_TAPE_BOX_GAP = 0.08
#: Breathing room either side of the widest label inside a box.
_TAPE_BOX_PADDING = 0.3
#: Keeps the source and target label bands from meeting at the box's vertical
#: midpoint: flush against each other, they read as one block of text rather
#: than two -- especially before the target label is revealed, when the gap is
#: the only cue that a second label lives there.
_TAPE_LABEL_INSET = 0.04


#: What to reach for when a count-driven visual is too large. `number_line`
#: places markers inside fixed +/-2.75 bounds, so its `maximum` is a scale and a
#: line from 0 to a million costs nothing to draw.
_LARGE_MAGNITUDE_ALTERNATIVE = "a number_line, whose maximum is a scale rather than a part count"


def _cardinality_failure(spec, field_name, observed, cap, unit_word) -> V3ValidationError:
    """A refusal that names the cap, the field, and what to use instead.

    The hint carries all three because it is the only one of these fields the
    generation retry loop forwards to the model
    (`draft_generation._STABLE_REPAIR_FEEDBACK_FIELDS`).
    """
    return V3ValidationError(V3Failure(
        code="visual_extent_unrenderable",
        path=f"visuals.{spec.ref}",
        expected=f"a {spec.kind} of at most {cap} parts",
        observed=f"{spec.ref} would draw {observed} parts ({field_name}={observed})",
        hint=(
            f"{spec.kind} draws one part per {unit_word}, at most {cap}; "
            f"reduce {field_name} (currently {observed}) or use {_LARGE_MAGNITUDE_ALTERNATIVE}"
        ),
    ))


def _require_renderable_cardinality(spec, values) -> None:
    for name in _CARDINALITY_FIELDS.get(spec.kind, ()):
        if name not in values:
            continue
        count = _whole(values[name], name) if _is_whole(values[name]) else None
        if count is not None and count <= MAX_PART_CARDINALITY:
            continue
        raise _cardinality_failure(
            spec, name, _describe(values[name]), MAX_PART_CARDINALITY, f"unit of {name}",
        )
    derived = _CARDINALITY_DERIVED.get(spec.kind)
    if derived is None:
        return
    name, cap, count_from = derived
    if name not in values:
        return
    if count_from(values[name]) > cap:
        raise _cardinality_failure(
            spec, name, _describe(values[name]), cap, "whole unit",
        )


def _is_whole(value) -> bool:
    return getattr(value, "denominator", 1) == 1


def _require_renderable_extent(kind, measured, values) -> None:
    """Reject a visual too large to fit the frame at any permitted scale.

    `_measure_bar`, `_measure_grid` and `_measure_object_set` derive their extent
    linearly from a numeric parameter, and nothing bounded it -- the expression
    DSL allows magnitudes to 10**12 and no limit caps how many semantic parts a
    visual may measure. A bar with `maximum` 10000 measured 6500 units wide and
    built 10000 parts; the only complaint reached the operator as
    `below_minimum_text_scale` at 0.002, a code about text carrying the hint
    "reduce visual content" for a scene holding a single bar.

    A visual wider or taller than the frame divided by MIN_TEXT_SCALE cannot fit
    however little else the lesson holds, so it is rejected here -- where the
    driving field is still in hand and can be named.
    """
    width_limit = (SAFE_FRAME.right - SAFE_FRAME.left) / MIN_TEXT_SCALE
    height_limit = (INSTRUCTIONAL_FRAME.top - INSTRUCTIONAL_FRAME.bottom) / MIN_TEXT_SCALE
    width = measured.bounds.right - measured.bounds.left
    height = measured.bounds.top - measured.bounds.bottom
    if width <= width_limit and height <= height_limit:
        return
    driving_names = [name for name in _SIZE_DRIVING_FIELDS.get(kind, ()) if name in values]
    drivers = ", ".join(f"{name}={_describe(values[name])}" for name in driving_names)
    fields_to_change = ", ".join(driving_names) if driving_names else "the field driving its size"
    raise V3ValidationError(V3Failure(
        code="visual_extent_unrenderable",
        path=f"visuals.{measured.ref}",
        expected=f"a visual within {width_limit:.1f} x {height_limit:.1f} units",
        observed=f"{measured.ref} spans {width:.1f} x {height:.1f} units ({drivers})",
        hint=f"reduce or shorten {fields_to_change} (currently {drivers or 'unknown'})",
    ))


def _require_marker_labels_do_not_collide(spec, marker_xs, label_widths, labels):
    """Reject a number_line whose adjacent labels would run into each other.

    The inter-visual overlap gate compares each visual's bounds against every
    other's, so a collision inside a single visual slips through -- and
    `_measure_number_line` packs every marker's label onto one strip, so
    dense magnitudes (250000, 500000, 750000, 1000000 in [0, 1_000_000])
    put their labels straight on top of each other while `bounds` stay
    within the frame. Markers may arrive unsorted, so sort by x before
    checking adjacency.
    """
    order = sorted(range(len(marker_xs)), key=lambda i: marker_xs[i])
    for a, b in zip(order, order[1:]):
        gap = (marker_xs[b] - label_widths[b] / 2) - (marker_xs[a] + label_widths[a] / 2)
        if gap >= MARKER_LABEL_INTER_GAP:
            continue
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=f"marker labels separated by at least {MARKER_LABEL_INTER_GAP:g} units",
            observed=(
                f"labels {labels[a]!r} and {labels[b]!r} overlap by "
                f"{MARKER_LABEL_INTER_GAP - gap:.2f} units"
            ),
            # Retry discards `observed` and only forwards `hint`
            # (see `draft_generation._STABLE_REPAIR_FEEDBACK_FIELDS`), so
            # spell the colliding labels here. Do NOT suggest widening the
            # numeric range: markers are positioned proportionally within
            # fixed +/-2.75 bounds, so a wider range packs the same markers
            # closer together, not further apart -- dropping one of the
            # colliding markers is the only recovery.
            hint=(
                f"drop marker {labels[a]!r} or {labels[b]!r} -- their labels "
                "overlap on the number_line's single label strip; widening "
                "the numeric range would not help, since markers are placed "
                "proportionally within fixed horizontal bounds"
            ),
        ))


def _describe(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return str(len(value))
    return str(_whole(value, "size") if getattr(value, "denominator", 1) == 1 else value)


def _whole(value, name):
    if getattr(value, "denominator", 1) != 1:
        raise ValueError(f"{name} must be a whole number")
    return int(value)


def _measured_visual(*, ref, bounds, parts, payload):
    return MeasuredVisual(ref=ref, bounds=bounds, parts=parts, paths={}, payload=payload)


#: Clear of the line without crowding it, matching `rectangle_measurement.LABEL_GAP`.
MARKER_LABEL_GAP = 0.28

#: Minimum whitespace to hold between two adjacent marker labels. The
#: inter-visual overlap gate cannot catch a collision inside one visual, so
#: `_measure_number_line` enforces this itself.
MARKER_LABEL_INTER_GAP = 0.1


def _measure_number_line(*, spec, values, measurer):
    minimum, maximum = values["minimum"], values["maximum"]
    if maximum <= minimum:
        raise ValueError("number_line maximum must exceed minimum")
    line_left, line_right = -2.75, 2.75
    markers = values["markers"]
    parts = {}
    labels = []
    label_widths = []
    marker_xs = []
    for index, marker in enumerate(markers):
        if not minimum <= marker <= maximum:
            raise ValueError(f"marker {marker} outside [{minimum}, {maximum}]")
        x = line_left + (line_right - line_left) * float((marker - minimum) / (maximum - minimum))
        parts[("marker", index)] = SemanticPart("marker", index, Bounds(x, x, 0, 0))
        label = format_number(marker)
        labels.append(label)
        width, _ = measurer.measure(label, "label")
        label_widths.append(width)
        marker_xs.append(x)
    label_height = max(
        (measurer.measure(text, "label")[1] for text in labels), default=0.0,
    )
    _require_marker_labels_do_not_collide(spec, marker_xs, label_widths, labels)
    bottom = -0.2 - MARKER_LABEL_GAP - label_height
    # A wide endpoint label overhangs the line's own extent -- if the bounds
    # stopped at +/-2.75, layout would tuck the next visual against the label
    # and the two would overlap. Widen the bounds so each label's half-width
    # is reserved; keep the line's own endpoints in payload so `_line_visual`
    # still draws from marker to marker, not across the padded strip.
    left_extent = min(
        (x - width / 2 for x, width in zip(marker_xs, label_widths)),
        default=line_left,
    )
    right_extent = max(
        (x + width / 2 for x, width in zip(marker_xs, label_widths)),
        default=line_right,
    )
    bounds_left = min(line_left, left_extent)
    bounds_right = max(line_right, right_extent)
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(bounds_left, bounds_right, bottom, 0.2),
        parts=parts,
        payload={
            "minimum": minimum, "maximum": maximum, "markers": tuple(markers),
            "marker_labels": tuple(labels),
            "label_center_y": bottom + label_height / 2,
            # Where the marker parts sit (see `Bounds(x, x, 0, 0)` above). The
            # line's own bounds are no longer vertically symmetric now that
            # they reserve a label strip below, so `_line_visual` reads this
            # instead of `bounds.center.y` to stay level with its markers.
            "line_center_y": 0.0,
            # The line's own horizontal endpoints. Bounds now include the label
            # strip's overhang, so `_line_visual` can't derive endpoints from
            # them without stretching the line under the labels.
            "line_left": line_left,
            "line_right": line_right,
        },
    )


def _measure_grid(*, spec, values, measurer):
    rows, columns = _whole(values["rows"], "rows"), _whole(values["columns"], "columns")
    if rows <= 0 or columns <= 0:
        raise ValueError("grid rows and columns must be positive")
    cell_size, gap = 0.6, 0.1
    width = columns * cell_size + (columns - 1) * gap
    height = rows * cell_size + (rows - 1) * gap
    left, bottom = -width / 2, -height / 2
    parts = {}
    for index in range(rows * columns):
        row, column = divmod(index, columns)
        cell_left = left + column * (cell_size + gap)
        cell_bottom = bottom + (rows - row - 1) * (cell_size + gap)
        parts[("cell", index)] = SemanticPart(
            "cell", index, Bounds(cell_left, cell_left + cell_size, cell_bottom, cell_bottom + cell_size)
        )
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, left + width, bottom, bottom + height),
        parts=parts,
        payload={"rows": rows, "columns": columns},
    )


def _measure_partition(*, spec, values, measurer):
    whole, count = values["whole"], _whole(values["parts"], "parts")
    if whole <= 0 or count <= 0:
        raise ValueError("partition whole and parts must be positive")
    radius = 1.2
    parts = {}
    for index in range(count):
        angle = tau * (index + 0.5) / count
        x, y = radius * cos(angle) / 2, radius * sin(angle) / 2
        parts[("partition", index)] = SemanticPart("partition", index, Bounds(x, x, y, y))
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(-radius, radius, -radius, radius),
        parts=parts,
        payload={"whole": whole, "parts": count},
    )


def _measure_bar(*, spec, values, measurer):
    value, maximum = values["value"], _whole(values["maximum"], "maximum")
    if maximum <= 0 or value < 0 or value > maximum:
        raise ValueError("bar requires 0 <= value <= maximum")
    segment_width, gap, height = 0.6, 0.05, 0.6
    width = maximum * segment_width + (maximum - 1) * gap
    left = -width / 2
    parts = {
        ("segment", index): SemanticPart(
            "segment", index,
            Bounds(left + index * (segment_width + gap), left + index * (segment_width + gap) + segment_width, -height / 2, height / 2),
        )
        for index in range(maximum)
    }
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, left + width, -height / 2, height / 2),
        parts=parts,
        payload={"value": value, "maximum": maximum},
    )


def _measure_object_set(*, spec, values, measurer):
    count = _whole(values["count"], "count")
    if count <= 0:
        raise ValueError("object_set count must be positive")
    columns, spacing = min(5, count), 0.7
    rows = ceil(count / columns)
    width, height = (columns - 1) * spacing, (rows - 1) * spacing
    left, bottom = -width / 2, -height / 2
    parts = {}
    for index in range(count):
        row, column = divmod(index, columns)
        x, y = left + column * spacing, bottom + (rows - row - 1) * spacing
        parts[("item", index)] = SemanticPart("item", index, Bounds(x, x, y, y))
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left - 0.1, left + width + 0.1, bottom - 0.1, bottom + height + 0.1),
        parts=parts,
        payload={"count": count},
    )


def _measure_label(*, spec, values, measurer):
    text = values["text"]
    width, height = measurer.measure(text, "label")
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(-width / 2, width / 2, -height / 2, height / 2),
        parts={},
        payload={"text": text},
    )


def _measure_answer(*, spec, values, measurer):
    """Reserve the widest stage, so resolving the answer never reflows the lesson."""
    stages = values["stages"]
    measured = [measurer.measure(text, "label") for text in stages.values()]
    width = max(width for width, _height in measured)
    height = max(height for _width, height in measured)
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(-width / 2, width / 2, -height / 2, height / 2),
        parts={},
        payload={"stages": stages},
    )


def _measure_unit_tape(*, spec, values, measurer):
    """One box per whole source unit, each box measured for both of its labels.

    Both labels are measured even though only the source label is drawn at first:
    `unit_substitution` reveals the target label mid-lesson, and a box sized for
    the shorter text would have to grow when the longer one arrives -- reflowing
    the lesson under the learner. This is the reservation `_measure_answer` makes
    for the staged answer, applied per box.
    """
    value, per_unit = values["value"], values["per_unit"]
    source_unit, target_unit = values["source_unit"], values["target_unit"]
    if value <= 0 or per_unit <= 0:
        raise ValueError("unit_tape value and per_unit must be positive")
    full_boxes = int(value)
    remainder = value - full_boxes
    source_texts = [f"1 {source_unit}"] * full_boxes
    target_texts = [f"{format_number(per_unit)} {target_unit}"] * full_boxes
    if remainder:
        source_texts.append(f"{format_number(remainder)} {source_unit}")
        target_texts.append(f"{format_number(remainder * per_unit)} {target_unit}")
    box_width = _TAPE_BOX_PADDING + max(
        measurer.measure(text, "label")[0] for text in (*source_texts, *target_texts)
    )
    box_count = len(source_texts)
    width = box_count * box_width + (box_count - 1) * _TAPE_BOX_GAP
    left = -width / 2
    parts = {}
    for index in range(box_count):
        box_left = left + index * (box_width + _TAPE_BOX_GAP)
        box = Bounds(box_left, box_left + box_width, -_TAPE_BOX_HEIGHT / 2, _TAPE_BOX_HEIGHT / 2)
        parts[("box", index)] = SemanticPart("box", index, box)
        parts[("source_label", index)] = SemanticPart(
            "source_label", index, _tape_label_bounds(box, upper=True),
        )
        parts[("target_label", index)] = SemanticPart(
            "target_label", index, _tape_label_bounds(box, upper=False),
        )
    # A group part per label class, because the compiler stages the substitution
    # without knowing the box count -- `value` is a fixture param at compile time.
    for part_name in ("source_label", "target_label"):
        spans = [parts[(part_name, index)].bounds for index in range(box_count)]
        parts[(part_name, None)] = SemanticPart(part_name, None, Bounds(
            min(span.left for span in spans), max(span.right for span in spans),
            min(span.bottom for span in spans), max(span.top for span in spans),
        ))
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, left + width, -_TAPE_BOX_HEIGHT / 2, _TAPE_BOX_HEIGHT / 2),
        parts=parts,
        payload={
            "boxes": tuple(
                {
                    "source_label": source_texts[index],
                    "target_label": target_texts[index],
                    "fill_fraction": 1.0 if index < full_boxes else float(remainder),
                }
                for index in range(box_count)
            ),
            "source_unit": source_unit,
            "target_unit": target_unit,
        },
    )


def _tape_label_bounds(box: Bounds, *, upper: bool) -> Bounds:
    """The upper or lower half of a box, where one of its two labels sits.

    Inset so the two bands do not meet: a label sitting flush against the
    other's edge reads as one block of text rather than two.
    """
    quarter = (box.top - box.bottom) / 4
    center_y = box.center.y + (quarter if upper else -quarter)
    return Bounds(
        box.left, box.right,
        center_y - quarter + _TAPE_LABEL_INSET, center_y + quarter - _TAPE_LABEL_INSET,
    )


#: The plane's half-extent in scene units. Chosen once so every downstream
#: ticket that plots on a coordinate_plane places a point at the same fraction
#: of the frame -- an M17-style transformation and an M21-style scatter share
#: the same grid without renegotiating axis spans.
COORDINATE_PLANE_HALF_WIDTH = 2.6
COORDINATE_PLANE_HALF_HEIGHT = 2.2

#: Hard ceiling on labeled ticks per axis, applied AFTER the collision-driven
#: stride below. Ticks are dense enough by then that further limits are only
#: a legibility bound, not a fit bound.
COORDINATE_PLANE_MAX_TICKS_PER_AXIS = 10

#: Hard ceiling on grid lines per axis. Grid ignores the tick-thinning stride
#: (grid contract: a line at every integer), so a very wide span would otherwise
#: paint a solid band -- refuse instead of silently omitting integer lines.
COORDINATE_PLANE_MAX_GRID_LINES_PER_AXIS = 20

#: Vertical gap between a plotted point and the label above it.
COORDINATE_POINT_LABEL_OFFSET = 0.12

#: Perpendicular gap between an axis and its tick labels.
COORDINATE_TICK_LABEL_GAP = 0.12

#: Minimum whitespace between two adjacent tick labels on the same axis.
COORDINATE_TICK_LABEL_INTER_GAP = 0.1

#: Minimum projected half-extent per axis, in scene units. When one span is
#: many orders of magnitude wider than the other, the uniform unit scale
#: collapses the shorter axis to near-zero length: [0, 10**12] x [0, 4]
#: projects the y-axis to ~1e-11 scene units, indistinct from a point. Reject
#: rather than paint an unreadable plane.
COORDINATE_PLANE_MIN_PROJECTED_EXTENT = 0.5

#: Radius of a plotted point dot in scene units. Matches Manim's default Dot
#: radius; used as the obstacle bound when checking that a label rectangle
#: does not cover any other point's dot.
COORDINATE_PLANE_DOT_RADIUS = 0.08

#: Half-width of the axis obstacle corridor a point label must clear. Kept
#: small (visual axis stroke, not the tick label gap) so a label sitting
#: above (0, 2) is caught for straddling the y-axis but a label a full
#: quadrant over is not.
COORDINATE_PLANE_AXIS_STROKE_HALF = 0.02

#: Half-length of a tick mark drawn perpendicular to its axis. Matches the
#: renderer's `tick_len` (see backend/app/meta/v3/renderer.py). Bounds have
#: to include this half-length around the projected axis position so ticks
#: on an axis clamped to an outer edge don't stick past the reported box.
COORDINATE_PLANE_TICK_HALF_LENGTH = 0.08


def _measure_coordinate_plane(*, spec, values, measurer):
    """Axes projected through the world origin, with plotted points and labels.

    Uniform unit scale (finding: distinct u/v scales distorted slopes and
    distances). Zero is projected through each declared span and clamped to
    the nearest edge when outside; the axes cross at the projected zero
    rather than the visual centre so (0, 0) reads as the origin.

    Refuses a point outside the declared span rather than clipping silently.

    Point labels probe four candidate quadrants (above, right, left, below)
    and pick the first whose rectangle collides with no already-placed tick
    label or previously placed point label; if every quadrant collides the
    default (above) quadrant wins and any tick labels it overlaps are
    suppressed so no glyphs are drawn on top of each other. When `grid` is
    set, integer grid lines are emitted so the renderer can draw them behind
    the axes.
    """
    x_min, x_max = values["x_min"], values["x_max"]
    y_min, y_max = values["y_min"], values["y_max"]
    for axis, low, high in (("x", x_min, x_max), ("y", y_min, y_max)):
        if high <= low:
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}",
                expected=f"{axis}_max strictly greater than {axis}_min",
                observed=(
                    f"{spec.ref} {axis} span [{format_number(low)}, "
                    f"{format_number(high)}] is empty or inverted"
                ),
                hint=(
                    f"raise {axis}_max above {axis}_min so the plane has a "
                    "positive span on this axis"
                ),
            ))
    grid_enabled = bool(values.get("grid", False))
    # Ticked axes are the coordinate_plane's readable contract; a span with no
    # integer inside (e.g. 0.1..0.9) yields zero ticks -- refuse rather than
    # ship an unticked plane the fixture author did not ask for.
    for axis, low, high in (("x", x_min, x_max), ("y", y_min, y_max)):
        if not _integer_ticks_in_span(low, high):
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}",
                expected=f"a {axis}-axis span containing at least one integer tick",
                observed=(
                    f"{spec.ref} {axis} span [{format_number(low)}, "
                    f"{format_number(high)}] contains no integer"
                ),
                hint=(
                    f"widen the {axis} span to include an integer, or shift it "
                    "so an integer tick falls inside the declared range"
                ),
            ))
    seen_points = set()
    for point in values["points"]:
        key = (point["x"], point["y"])
        if key in seen_points:
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}",
                expected="distinct point coordinates on the coordinate_plane",
                observed=(
                    f"{spec.ref} plots ({format_number(point['x'])}, "
                    f"{format_number(point['y'])}) more than once"
                ),
                hint=(
                    "remove the duplicate point -- stacked point labels render "
                    "as overlapping glyphs at the same dot"
                ),
            ))
        seen_points.add(key)
    # Centers stay exact as Fraction so a narrow span at a large magnitude
    # (e.g. [10**9 - 10**-8, 10**9]) doesn't collapse to a single float and
    # project both endpoints onto the same scene coord. Differences from the
    # center are computed exactly, then narrowed to float once.
    x_min_q = Fraction(x_min)
    x_max_q = Fraction(x_max)
    y_min_q = Fraction(y_min)
    y_max_q = Fraction(y_max)
    span_x_q = x_max_q - x_min_q
    span_y_q = y_max_q - y_min_q
    span_x = float(span_x_q)
    span_y = float(span_y_q)
    # A schema-valid positive span can underflow to 0.0 during the Fraction
    # -> float narrowing (e.g. Fraction(1, 10**309) - Fraction(0)), which
    # would fall into a ZeroDivisionError below. Refuse with a named failure
    # instead of the raw arithmetic error.
    for axis, span, low, high in (
        ("x", span_x, x_min, x_max),
        ("y", span_y, y_min, y_max),
    ):
        if span <= 0.0 or not isfinite(span):
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}",
                expected=(
                    f"a {axis} span whose float width is a positive finite "
                    "number"
                ),
                observed=(
                    f"{spec.ref} {axis} span [{format_number(low)}, "
                    f"{format_number(high)}] narrows to {span!r} in float "
                    "precision"
                ),
                hint=(
                    f"widen the {axis} span -- an axis narrower than float "
                    "precision projects to a single scene coordinate"
                ),
            ))
    # One scale drawn from whichever axis is tighter, so a unit step in world
    # coords covers the same scene distance on both axes.
    unit_scale = min(
        (2 * COORDINATE_PLANE_HALF_WIDTH) / span_x,
        (2 * COORDINATE_PLANE_HALF_HEIGHT) / span_y,
    )
    # A subnormal-but-positive span survives the check above yet still drives
    # the scale to infinity, which contaminates every downstream projected
    # value. Refuse rather than paint an unbounded plane.
    if not isfinite(unit_scale) or unit_scale <= 0.0:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected="a coordinate_plane whose uniform unit scale is finite",
            observed=(
                f"{spec.ref} unit scale computes to {unit_scale!r} from "
                f"x span [{format_number(x_min)}, {format_number(x_max)}] "
                f"and y span [{format_number(y_min)}, {format_number(y_max)}]"
            ),
            hint=(
                "widen both spans so the projected scale stays finite -- a "
                "span near float precision has no representable projection"
            ),
        ))
    extent_x = span_x * unit_scale / 2
    extent_y = span_y * unit_scale / 2
    # Uniform scale drawn from the tighter axis collapses the looser axis when
    # the two spans are wildly unbalanced. A span like [0, 10**12] x [0, 4]
    # yields a y-axis extent of ~1e-11 scene units, so every plotted y falls
    # on the same pixel row and tick thinning strips the y labels entirely.
    for axis, extent, low, high in (
        ("x", extent_x, x_min, x_max),
        ("y", extent_y, y_min, y_max),
    ):
        if extent < COORDINATE_PLANE_MIN_PROJECTED_EXTENT:
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}",
                expected=(
                    f"a {axis}-axis whose projected extent stays above "
                    f"{COORDINATE_PLANE_MIN_PROJECTED_EXTENT:g} scene units "
                    "after uniform scaling"
                ),
                observed=(
                    f"{spec.ref} {axis} span [{format_number(low)}, "
                    f"{format_number(high)}] projects to {extent:g} scene "
                    "units -- the other axis is orders of magnitude wider "
                    "and forces this one to collapse"
                ),
                hint=(
                    "narrow the wider span or widen this one so the two axis "
                    "ranges are within a few orders of magnitude of each other"
                ),
            ))
    x_center = (x_min_q + x_max_q) / 2
    y_center = (y_min_q + y_max_q) / 2

    def project(px, py):
        return (
            float(Fraction(px) - x_center) * unit_scale,
            float(Fraction(py) - y_center) * unit_scale,
        )

    # World origin projected into scene coords, clamped to the nearest edge
    # when the declared span excludes zero, so the axis line stays visible.
    zero_u = max(-extent_x, min(extent_x, float(-x_center) * unit_scale))
    zero_v = max(-extent_y, min(extent_y, float(-y_center) * unit_scale))

    x_tick_payload = _coordinate_tick_payload(
        _integer_ticks_in_span(x_min_q, x_max_q), unit_scale, measurer, axis="x",
    )
    y_tick_payload = _coordinate_tick_payload(
        _integer_ticks_in_span(y_min_q, y_max_q), unit_scale, measurer, axis="y",
    )
    _require_coordinate_tick_labels_do_not_collide(
        spec, x_tick_payload, unit_scale, axis="x",
    )
    _require_coordinate_tick_labels_do_not_collide(
        spec, y_tick_payload, unit_scale, axis="y",
    )

    # Rectangles for every tick label in the same scene coordinates the
    # renderer paints them at; the collision search below reads these.
    x_tick_rects = [
        _tick_label_rect_x(
            float(value - x_center) * unit_scale, zero_v, w, h,
        )
        for value, _text, w, h in x_tick_payload
    ]
    y_tick_rects = [
        _tick_label_rect_y(
            float(value - y_center) * unit_scale, zero_u, w, h,
        )
        for value, _text, w, h in y_tick_payload
    ]
    x_tick_suppressed = [False] * len(x_tick_payload)
    y_tick_suppressed = [False] * len(y_tick_payload)

    # Cross-axis tick labels can occupy the same rectangle: for span [-3, 5]
    # the x-axis "-1" (below x-axis) and y-axis "-1" (left of y-axis) can land
    # on top of each other at Manim's actual label metrics. Suppress the
    # y-axis label per collision so the label content still appears once.
    for xi, xr in enumerate(x_tick_rects):
        for yi, yr in enumerate(y_tick_rects):
            if y_tick_suppressed[yi]:
                continue
            if _rects_overlap(xr, yr):
                y_tick_suppressed[yi] = True

    # Pre-check every point sits inside the declared span before projecting
    # anything -- an off-plane point is refused regardless of label placement.
    for index, point in enumerate(values["points"]):
        px, py = point["x"], point["y"]
        if not (x_min <= px <= x_max) or not (y_min <= py <= y_max):
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}.points[{index}]",
                expected=(
                    f"a point inside the declared plane [{format_number(x_min)}, "
                    f"{format_number(x_max)}] x [{format_number(y_min)}, "
                    f"{format_number(y_max)}]"
                ),
                observed=(
                    f"{spec.ref} plots ({format_number(px)}, {format_number(py)}) "
                    "outside the declared span"
                ),
                hint=(
                    "move the point inside the span, or widen the axis span to "
                    "include the point -- an off-plane dot draws against the axis wall"
                ),
            ))

    # Pre-project every dot so a label rect can be checked against every other
    # rendered dot (labels paint above dots -- a later dot under an earlier
    # label reads as an obscured dot).
    projected_points = [project(p["x"], p["y"]) for p in values["points"]]
    dot_rects = [
        (
            pu - COORDINATE_PLANE_DOT_RADIUS, pu + COORDINATE_PLANE_DOT_RADIUS,
            pv - COORDINATE_PLANE_DOT_RADIUS, pv + COORDINATE_PLANE_DOT_RADIUS,
        )
        for pu, pv in projected_points
    ]
    # A plotted dot can land on top of a tick label rectangle: e.g. (2, -0.6)
    # on [-3, 5]^2 puts the dot directly over the x-axis "2" label. Point
    # labels avoid dots, but the tick label glyph would still render under
    # the dot. Suppress any tick label whose rect a dot intersects so no
    # glyph is drawn beneath a rendered dot.
    for xi, xr in enumerate(x_tick_rects):
        if x_tick_suppressed[xi]:
            continue
        if any(_rects_overlap(xr, dr) for dr in dot_rects):
            x_tick_suppressed[xi] = True
    for yi, yr in enumerate(y_tick_rects):
        if y_tick_suppressed[yi]:
            continue
        if any(_rects_overlap(yr, dr) for dr in dot_rects):
            y_tick_suppressed[yi] = True
    # Axes as thin obstacle corridors: a coordinate label centered over the
    # y-axis (e.g. above the point (0, 2)) renders glyphs on top of the axis
    # stroke. The corridor is the axis stroke half-width, so a label a full
    # quadrant away does not collide.
    x_axis_rect = (
        -extent_x, extent_x,
        zero_v - COORDINATE_PLANE_AXIS_STROKE_HALF,
        zero_v + COORDINATE_PLANE_AXIS_STROKE_HALF,
    )
    y_axis_rect = (
        zero_u - COORDINATE_PLANE_AXIS_STROKE_HALF,
        zero_u + COORDINATE_PLANE_AXIS_STROKE_HALF,
        -extent_y, extent_y,
    )

    parts: dict = {}
    point_payload = []
    point_label_rects: list = []
    for index, point in enumerate(values["points"]):
        px, py = point["x"], point["y"]
        u, v = projected_points[index]
        parts[("point", index)] = SemanticPart("point", index, Bounds(u, u, v, v))
        label_text = _coordinate_label(px, py)
        label_w, label_h = measurer.measure(label_text, "label")
        other_dot_rects = [r for i, r in enumerate(dot_rects) if i != index]
        hard_obstacles = other_dot_rects + [x_axis_rect, y_axis_rect]
        chosen_dx, chosen_dy, chosen_rect = _pick_point_label_offset(
            u, v, label_w, label_h,
            x_tick_rects, y_tick_rects,
            x_tick_suppressed, y_tick_suppressed,
            point_label_rects, hard_obstacles,
        )
        if chosen_rect is None:
            # No fully clear quadrant. A quadrant that only collides with tick
            # labels is still usable (the collided ticks get suppressed), but
            # a quadrant that overlaps a prior point label, another point's
            # dot, or an axis corridor cannot be recovered -- refuse.
            chosen_dx, chosen_dy, chosen_rect = _pick_point_label_offset_over_ticks(
                u, v, label_w, label_h,
                x_tick_rects, y_tick_rects,
                x_tick_suppressed, y_tick_suppressed,
                point_label_rects, hard_obstacles,
            )
            if chosen_rect is None:
                raise V3ValidationError(V3Failure(
                    code="visual_extent_unrenderable",
                    path=f"visuals.{spec.ref}",
                    expected=(
                        "point labels with a collision-free quadrant on the "
                        "coordinate_plane"
                    ),
                    observed=(
                        f"{spec.ref} point ({format_number(px)}, "
                        f"{format_number(py)}) cannot place its label without "
                        "overlapping another point label, another dot, or an "
                        "axis line"
                    ),
                    hint=(
                        "spread the points, widen the axis span, or drop "
                        "points -- clustered coordinates or points on the axes "
                        "leave no quadrant free for the label"
                    ),
                ))
            for i, tr in enumerate(x_tick_rects):
                if not x_tick_suppressed[i] and _rects_overlap(chosen_rect, tr):
                    x_tick_suppressed[i] = True
            for i, tr in enumerate(y_tick_rects):
                if not y_tick_suppressed[i] and _rects_overlap(chosen_rect, tr):
                    y_tick_suppressed[i] = True
        point_label_rects.append(chosen_rect)
        point_payload.append({
            "x": u, "y": v, "label": label_text,
            "label_width": label_w, "label_height": label_h,
            "label_dx": chosen_dx, "label_dy": chosen_dy,
        })

    if grid_enabled:
        # Grid contract: a line at every integer. Do NOT reuse the tick helper,
        # which thins to at most COORDINATE_PLANE_MAX_TICKS_PER_AXIS values --
        # a [0, 10] span would silently drop the odd integers. Instead, expand
        # the integer range directly and refuse spans that would exceed the
        # per-axis grid ceiling rather than paint a dense wall of lines.
        x_grid_ints = _integer_grid_values(spec, x_min_q, x_max_q, axis="x")
        y_grid_ints = _integer_grid_values(spec, y_min_q, y_max_q, axis="y")
        x_grid_lines = tuple(
            float(v - x_center) * unit_scale for v in x_grid_ints
        )
        y_grid_lines = tuple(
            float(v - y_center) * unit_scale for v in y_grid_ints
        )
    else:
        x_grid_lines = ()
        y_grid_lines = ()

    bounds = _coordinate_plane_bounds(
        extent_x, extent_y, zero_u, zero_v,
        point_payload, x_tick_payload, y_tick_payload,
        x_tick_suppressed, y_tick_suppressed,
        unit_scale=unit_scale, x_center=x_center, y_center=y_center,
    )
    return _measured_visual(
        ref=spec.ref,
        bounds=bounds,
        parts=parts,
        payload={
            "x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
            "extent_x": extent_x, "extent_y": extent_y,
            "axis_zero_u": zero_u, "axis_zero_v": zero_v,
            "unit_scale": unit_scale,
            "points": tuple(point_payload),
            "point_label_offset": COORDINATE_POINT_LABEL_OFFSET,
            "tick_label_gap": COORDINATE_TICK_LABEL_GAP,
            "x_ticks": tuple(
                {"value": value,
                 "u": float(value - x_center) * unit_scale,
                 "label": ("" if x_tick_suppressed[i] else text),
                 "label_width": w, "label_height": h}
                for i, (value, text, w, h) in enumerate(x_tick_payload)
            ),
            "y_ticks": tuple(
                {"value": value,
                 "v": float(value - y_center) * unit_scale,
                 "label": ("" if y_tick_suppressed[i] else text),
                 "label_width": w, "label_height": h}
                for i, (value, text, w, h) in enumerate(y_tick_payload)
            ),
            "grid": grid_enabled,
            "x_grid_lines": x_grid_lines,
            "y_grid_lines": y_grid_lines,
        },
    )


def _rects_overlap(a, b) -> bool:
    return a[0] < b[1] and a[1] > b[0] and a[2] < b[3] and a[3] > b[2]


def _tick_label_rect_x(u, zero_v, w, h):
    cy = zero_v - COORDINATE_TICK_LABEL_GAP - h / 2
    return (u - w / 2, u + w / 2, cy - h / 2, cy + h / 2)


def _tick_label_rect_y(v, zero_u, w, h):
    cx = zero_u - COORDINATE_TICK_LABEL_GAP - w / 2
    return (cx - w / 2, cx + w / 2, v - h / 2, v + h / 2)


def _point_label_candidates(label_w, label_h):
    off = COORDINATE_POINT_LABEL_OFFSET
    dx = off + label_w / 2
    dy = off + label_h / 2
    # Cardinals first (natural reading); diagonals fall back for points on an
    # axis (e.g. the origin), where every cardinal rect straddles the other
    # axis. A diagonal rect sits fully inside one quadrant so it clears both
    # axis corridors at once.
    return (
        (0.0, dy),         # above
        (dx, 0.0),         # right
        (-dx, 0.0),        # left
        (0.0, -dy),        # below
        (dx, dy),          # upper-right
        (-dx, dy),         # upper-left
        (dx, -dy),         # lower-right
        (-dx, -dy),        # lower-left
    )


def _point_label_rect(u, v, dx, dy, w, h):
    cx, cy = u + dx, v + dy
    return (cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2)


def _pick_point_label_offset(
    u, v, label_w, label_h,
    x_tick_rects, y_tick_rects,
    x_tick_suppressed, y_tick_suppressed,
    point_label_rects, hard_obstacles,
):
    """Return the first quadrant offset whose rect does not collide.

    Returns (dx, dy, rect) on success; (None, None, None) when every
    quadrant collides -- the caller then falls back to the default quadrant
    and suppresses the tick labels the fallback overlaps. `hard_obstacles`
    are axis corridors and other-point dot rects; a label overlapping any
    of these cannot be recovered (labels paint above dots, and axis strokes
    have no glyph the renderer can suppress).
    """
    for dx, dy in _point_label_candidates(label_w, label_h):
        rect = _point_label_rect(u, v, dx, dy, label_w, label_h)
        if any(_rects_overlap(rect, obs) for obs in hard_obstacles):
            continue
        if any(
            _rects_overlap(rect, tr)
            for i, tr in enumerate(x_tick_rects)
            if not x_tick_suppressed[i]
        ):
            continue
        if any(
            _rects_overlap(rect, tr)
            for i, tr in enumerate(y_tick_rects)
            if not y_tick_suppressed[i]
        ):
            continue
        if any(_rects_overlap(rect, pr) for pr in point_label_rects):
            continue
        return dx, dy, rect
    return None, None, None


def _pick_point_label_offset_over_ticks(
    u, v, label_w, label_h,
    x_tick_rects, y_tick_rects,
    x_tick_suppressed, y_tick_suppressed,
    point_label_rects, hard_obstacles,
):
    """Second-chance quadrant search: tick collisions allowed, prior point
    label / dot / axis-corridor collisions still refused. The caller
    suppresses any ticks the returned rect overlaps; other-point dots and
    axis strokes cannot be suppressed, so those quadrants are skipped."""
    for dx, dy in _point_label_candidates(label_w, label_h):
        rect = _point_label_rect(u, v, dx, dy, label_w, label_h)
        if any(_rects_overlap(rect, obs) for obs in hard_obstacles):
            continue
        if any(_rects_overlap(rect, pr) for pr in point_label_rects):
            continue
        return dx, dy, rect
    return None, None, None


def _coordinate_label(x, y) -> str:
    return f"({format_number(x)}, {format_number(y)})"


def _integer_ticks_in_span(low, high) -> list:
    """Whole-number ticks inside [low, high], capped for legibility.

    A wide span (e.g. [0, 10**12]) would materialize every integer before the
    thinning step ran, exhausting memory. Compute the stride from the count
    up front so `range` yields at most COORDINATE_PLANE_MAX_TICKS_PER_AXIS
    values regardless of span size. Endpoints stay exact (Fraction / int) so
    a narrow span at a large magnitude doesn't lose its ceil/floor.
    """
    lo, hi = int(ceil(low)), int(floor(high))
    if hi < lo:
        return []
    count = hi - lo + 1
    if count > COORDINATE_PLANE_MAX_TICKS_PER_AXIS:
        stride = -(-count // COORDINATE_PLANE_MAX_TICKS_PER_AXIS)
        return list(range(lo, hi + 1, stride))
    return list(range(lo, hi + 1))


def _integer_grid_values(spec, low, high, *, axis: str) -> list:
    """Every integer inside [low, high], refusing spans that would exceed
    COORDINATE_PLANE_MAX_GRID_LINES_PER_AXIS.

    Grid lines are a "line at every integer" contract, so this bypasses the
    tick-thinning stride -- a [0, 10] span emits 11 lines, not the 6 the
    thinned tick set would give. Wide spans get rejected so the plane never
    silently omits integer grid lines.
    """
    lo, hi = int(ceil(low)), int(floor(high))
    if hi < lo:
        return []
    count = hi - lo + 1
    if count > COORDINATE_PLANE_MAX_GRID_LINES_PER_AXIS:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=(
                f"a {axis} span whose integer count is at most "
                f"{COORDINATE_PLANE_MAX_GRID_LINES_PER_AXIS} when grid=true"
            ),
            observed=(
                f"{spec.ref} {axis} span [{format_number(low)}, "
                f"{format_number(high)}] would emit {count} grid lines"
            ),
            hint=(
                f"narrow the {axis} span, or set grid=false -- a grid line at "
                "every integer would paint a solid band at this density"
            ),
        ))
    return list(range(lo, hi + 1))


def _coordinate_tick_payload(tick_values, unit_scale, measurer, *, axis: str):
    """Tick values with labels, thinned so adjacent labels do not overlap.

    Candidate ticks are not guaranteed one world-unit apart:
    `_integer_ticks_in_span` may have already thinned by a larger stride to
    stay under `COORDINATE_PLANE_MAX_TICKS_PER_AXIS`, so the fit check has to
    read the actual value gap between adjacent candidates rather than assume
    stride corresponds to one unit. Label width sets the fit budget on the
    x-axis (labels sit side by side); label height sets it on the y-axis
    (labels stack vertically).
    """
    if not tick_values:
        return []
    size_index = 2 if axis == "x" else 3
    measured = [(value, format_number(value), *measurer.measure(format_number(value), "label"))
                for value in tick_values]
    stride = 1
    while stride < len(measured):
        thinned = measured[::stride]
        max_size = max(row[size_index] for row in thinned)
        min_value_gap = min(
            float(b[0] - a[0]) for a, b in zip(thinned, thinned[1:])
        )
        if min_value_gap * unit_scale >= max_size + COORDINATE_TICK_LABEL_INTER_GAP:
            break
        stride += 1
    return measured[::stride]


def _require_coordinate_tick_labels_do_not_collide(spec, tick_payload, unit_scale, *, axis: str):
    """The stride picker in `_coordinate_tick_payload` may run out of room.

    If even stride=len still has adjacent widths that don't fit -- e.g. a very
    wide label on a narrow plane -- surface the failure with the colliding
    labels named, so retry can shorten the numeric span rather than the count.
    """
    for a, b in zip(tick_payload, tick_payload[1:]):
        _va, ta, wa, ha = a
        _vb, tb, wb, hb = b
        world_gap = float(b[0] - a[0]) * unit_scale
        size_a, size_b = (wa, wb) if axis == "x" else (ha, hb)
        actual_gap = world_gap - (size_a + size_b) / 2
        if actual_gap >= COORDINATE_TICK_LABEL_INTER_GAP:
            continue
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=(
                f"{axis}-axis tick labels separated by at least "
                f"{COORDINATE_TICK_LABEL_INTER_GAP:g} units"
            ),
            observed=(
                f"labels {ta!r} and {tb!r} overlap by "
                f"{COORDINATE_TICK_LABEL_INTER_GAP - actual_gap:.2f} units"
            ),
            hint=(
                f"narrow the {axis} span or shorten {ta!r}/{tb!r} -- adjacent "
                "coordinate_plane tick labels overlap on their axis strip"
            ),
        ))


def _coordinate_plane_bounds(
    extent_x, extent_y, zero_u, zero_v,
    point_payload, x_tick_payload, y_tick_payload,
    x_tick_suppressed, y_tick_suppressed,
    *, unit_scale, x_center, y_center,
):
    """Widen the raw axis rectangle so no label overhangs its neighbour.

    Every rendered tick label sits inside the returned box: an x-axis tick
    label centred on its tick's u can stretch past the axis's left/right
    endpoints, and a y-axis tick label centred on its tick's v can stretch
    past its top/bottom endpoints, so the union has to include each label's
    full rectangle rather than only the axis-perpendicular strip. Point
    labels contribute their chosen quadrant's rectangle; suppressed tick
    labels contribute nothing because the renderer skips them.
    """
    # Tick marks stick out perpendicular to their axis by the shared half-
    # length. When an axis is clamped to an outer edge (both axes on a
    # [-1.4, -0.6]^2 plane, for example) that overhang lands outside the
    # raw axis rectangle, so seed the union with it.
    tick_half = COORDINATE_PLANE_TICK_HALF_LENGTH
    left = min(-extent_x, zero_u - tick_half)
    right = max(extent_x, zero_u + tick_half)
    bottom = min(-extent_y, zero_v - tick_half)
    top = max(extent_y, zero_v + tick_half)
    for point in point_payload:
        label_center_x = point["x"] + point["label_dx"]
        label_center_y = point["y"] + point["label_dy"]
        left = min(left, label_center_x - point["label_width"] / 2)
        right = max(right, label_center_x + point["label_width"] / 2)
        top = max(top, label_center_y + point["label_height"] / 2)
        bottom = min(bottom, label_center_y - point["label_height"] / 2)
    for i, (value, _text, w, h) in enumerate(x_tick_payload):
        if x_tick_suppressed[i]:
            continue
        u = float(value - x_center) * unit_scale
        left = min(left, u - w / 2)
        right = max(right, u + w / 2)
        bottom = min(bottom, zero_v - COORDINATE_TICK_LABEL_GAP - h)
    for i, (value, _text, w, h) in enumerate(y_tick_payload):
        if y_tick_suppressed[i]:
            continue
        v = float(value - y_center) * unit_scale
        top = max(top, v + h / 2)
        bottom = min(bottom, v - h / 2)
        left = min(left, zero_u - COORDINATE_TICK_LABEL_GAP - w)
    return Bounds(left, right, bottom, top)


def _measure_ordered_values(*, spec, values, measurer):
    return measure_ordered_values(
        ref=spec.ref, values=values["values"], measurer=measurer, gap=0.45,
        initial_role=spec.initial_role,
    )


def _measure_rectangle(*, spec, values, measurer):
    return measure_rectangle(
        ref=spec.ref, length=values["length"], width=values["width"],
        unit=values["unit"], measurer=measurer,
    )


def default_visual_registry() -> VisualRegistry:
    registry = VisualRegistry()
    registry.register("ordered_values", _measure_ordered_values)
    registry.register("rectangle_measurement", _measure_rectangle)
    registry.register("number_line", _measure_number_line)
    registry.register("grid", _measure_grid)
    registry.register("partition", _measure_partition)
    registry.register("bar", _measure_bar)
    registry.register("unit_tape", _measure_unit_tape)
    registry.register("object_set", _measure_object_set)
    registry.register("label", _measure_label)
    registry.register("answer_expression", _measure_answer)
    registry.register("coordinate_plane", _measure_coordinate_plane)
    return registry
