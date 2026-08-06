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
    "number_line": {
        "group_reveal", "short_stagger", "magnitude_comparison", "ray_shade",
        "signed_hop", "distance_from_zero",
    },
    "grid": {"group_reveal", "short_stagger", "regroup"},
    "partition": {
        "group_reveal", "partition",
        "equivalence_align", "common_denominator_bridge",
    },
    "bar": {"group_reveal", "short_stagger", "magnitude_comparison", "inverse_operation"},
    "object_set": {"group_reveal", "short_stagger", "regroup"},
    "label": {"group_reveal"},
    "unit_tape": {"group_reveal", "unit_substitution", "unit_rate"},
    "coordinate_plane": {"group_reveal"},
    "data_display": {"group_reveal", "short_stagger"},
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
#: `number_line`'s `boundary` and `ray` are the ray_shade affordance; a plan
#: without `boundary`/`boundary_kind`/`ray_direction` exposes no such parts, so
#: the entry is inert for non-ray_shade lines.
DEFERRED_PARTS = {
    "unit_tape": ("target_label",),
    "number_line": ("boundary", "ray"),
}

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

    def _project(value):
        return line_left + (line_right - line_left) * float(
            (value - minimum) / (maximum - minimum)
        )

    for index, marker in enumerate(markers):
        if not minimum <= marker <= maximum:
            raise ValueError(f"marker {marker} outside [{minimum}, {maximum}]")
        x = _project(marker)
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
    boundary_value = values.get("boundary")
    boundary_kind = values.get("boundary_kind")
    ray_direction = values.get("ray_direction")
    if boundary_value is not None:
        if not minimum <= boundary_value <= maximum:
            raise ValueError(
                f"boundary {boundary_value} outside [{minimum}, {maximum}]"
            )
        boundary_x = _project(boundary_value)
        parts[("boundary", 0)] = SemanticPart(
            "boundary", 0, Bounds(boundary_x, boundary_x, 0, 0),
        )
        ray_end_x = line_right if ray_direction == "right" else line_left
        parts[("ray", 0)] = SemanticPart(
            "ray", 0,
            Bounds(min(boundary_x, ray_end_x), max(boundary_x, ray_end_x), 0, 0),
        )
    else:
        boundary_x = None
        ray_end_x = None
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
            # `ray_shade` payload: `boundary_x`, `boundary_kind`, `ray_end_x`
            # are populated only when the plan carries a boundary. The
            # renderer branches on `boundary_x is None` and skips the
            # circle+ray primitives entirely on a non-inequality line.
            "boundary": boundary_value,
            "boundary_x": boundary_x,
            "boundary_kind": boundary_kind,
            "ray_direction": ray_direction,
            "ray_end_x": ray_end_x,
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
    shaded = _whole(values.get("shaded", 0), "shaded")
    if whole <= 0 or count <= 0:
        raise ValueError("partition whole and parts must be positive")
    if shaded < 0 or shaded > count:
        raise ValueError(f"partition requires 0 <= shaded <= parts, got shaded={shaded} parts={count}")
    radius = 1.2
    parts = {}
    for index in range(count):
        # Wedge centroid (~2/3 of the radius, mid-angle of the wedge). The
        # renderer draws one filled Sector per part; the SemanticPart bounds
        # anchor a `set_role` transform to the wedge's visible centre rather
        # than to a bare marker dot.
        angle = tau * (index + 0.5) / count
        x, y = (2 * radius / 3) * cos(angle), (2 * radius / 3) * sin(angle)
        parts[("partition", index)] = SemanticPart("partition", index, Bounds(x, x, y, y))
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(-radius, radius, -radius, radius),
        parts=parts,
        payload={"whole": whole, "parts": count, "shaded": shaded},
    )


def _measure_bar(*, spec, values, measurer):
    value, maximum = values["value"], _whole(values["maximum"], "maximum")
    if maximum <= 0 or value < 0 or value > maximum:
        raise ValueError("bar requires 0 <= value <= maximum")
    constant_raw = values.get("constant")
    coefficient_raw = values.get("coefficient")
    if constant_raw is not None:
        constant = _whole(constant_raw, "constant")
        coefficient = _whole(coefficient_raw, "coefficient") if coefficient_raw is not None else 1
        if not 0 < constant < maximum:
            raise ValueError(
                f"bar constant must satisfy 0 < constant < maximum "
                f"(constant={constant}, maximum={maximum})"
            )
        if coefficient < 1:
            raise ValueError("bar coefficient must be >= 1")
        x_segment_count = maximum - constant
        if x_segment_count % coefficient != 0:
            raise ValueError(
                f"bar (maximum - constant) must be divisible by coefficient "
                f"(maximum={maximum}, constant={constant}, coefficient={coefficient})"
            )
        segments_per_x = x_segment_count // coefficient
    else:
        constant = None
        coefficient = None
        x_segment_count = None
        segments_per_x = None
    segment_width, gap, height = 0.6, 0.05, 0.6
    width = maximum * segment_width + (maximum - 1) * gap
    left = -width / 2

    def _segment_bounds(index):
        seg_left = left + index * (segment_width + gap)
        return Bounds(seg_left, seg_left + segment_width, -height / 2, height / 2)

    def _range_bounds(first, last):
        """Bounds spanning segments `first..last` inclusive."""
        first_bounds = _segment_bounds(first)
        last_bounds = _segment_bounds(last)
        return Bounds(
            first_bounds.left, last_bounds.right, -height / 2, height / 2,
        )

    parts = {
        ("segment", index): SemanticPart("segment", index, _segment_bounds(index))
        for index in range(maximum)
    }
    if constant is not None:
        parts[("x_region", 0)] = SemanticPart(
            "x_region", 0, _range_bounds(0, x_segment_count - 1),
        )
        parts[("constant_region", 0)] = SemanticPart(
            "constant_region", 0, _range_bounds(x_segment_count, maximum - 1),
        )
        for i in range(coefficient):
            first = i * segments_per_x
            last = first + segments_per_x - 1
            parts[("x_part", i)] = SemanticPart(
                "x_part", i, _range_bounds(first, last),
            )
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, left + width, -height / 2, height / 2),
        parts=parts,
        payload={
            "value": value, "maximum": maximum,
            # `inverse_operation` payload: `constant` is the known-addend
            # segment count carved off the right, `coefficient` is how many
            # equal x-parts the remaining x-region subdivides into. Both are
            # `None` on a plain bar; the renderer branches on this to draw
            # partition dividers between the x_region and the constant_region
            # and (when coefficient > 1) between adjacent x_parts.
            "constant": constant,
            "coefficient": coefficient,
        },
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


#: Base horizontal extent every data_display style paints its axis in. Fixed
#: so downstream tickets that reuse the kind land marks at the same fraction
#: of the frame across variants and lessons.
DATA_DISPLAY_AXIS_WIDTH = 9.0
#: Vertical room reserved above the axis for bars / marks. Same for every
#: style so the safe-frame fit check reads the same intent regardless of the
#: chosen display style.
DATA_DISPLAY_PLOT_HEIGHT = 2.8
#: Vertical gap between the axis line and a category label / tick label.
DATA_DISPLAY_AXIS_LABEL_GAP = 0.18
#: Vertical gap between a bar's top and its numeric count label.
DATA_DISPLAY_COUNT_LABEL_GAP = 0.12
#: Minimum whitespace between two adjacent category labels below the axis.
DATA_DISPLAY_LABEL_INTER_GAP = 0.1
#: Radius of a dot in a dot_plot. Matches Manim's default Dot radius.
DATA_DISPLAY_DOT_RADIUS = 0.09
#: Stacking pitch between adjacent dots at the same value in a dot_plot.
DATA_DISPLAY_DOT_PITCH = 0.22
#: X mark drawn at each line_plot value: a crossed pair of line segments of
#: this half-length. Kept small so a mark reads as a single glyph.
DATA_DISPLAY_MARK_HALF = 0.13
#: Stacking pitch between adjacent X marks at the same value in a line_plot.
DATA_DISPLAY_MARK_PITCH = 0.30
#: Vertical thickness of a box_plot's box.
DATA_DISPLAY_BOX_HEIGHT = 0.9


def _measure_data_display(*, spec, values, measurer):
    """Axis-based data display -- one of five styles selected by `display_style`.

    Every style plants an axis strip at the bottom of the visual and draws its
    marks above it. Bar-based styles (`bar_graph`, `histogram`) map categories
    to axis segments and derive a numeric extent from category counts. Number-
    line-based styles (`line_plot`, `dot_plot`, `box_plot`) place marks by
    projecting the value onto a fixed-width axis spanning [axis_min, axis_max].

    Refuses:
    - a numeric axis whose max is not strictly greater than its min (all
      number-line-based styles);
    - a `values` entry outside the declared axis range (line_plot / dot_plot);
    - a `box_plot` five-number summary that is not monotonic;
    - a `dot_plot` whose tallest stack overruns the plot height.
    """
    style = values["display_style"]
    if style in {"bar_graph", "histogram"}:
        return _measure_data_display_bars(
            spec=spec, values=values, measurer=measurer, contiguous=(style == "histogram"),
        )
    if style in {"line_plot", "dot_plot"}:
        return _measure_data_display_number_line_points(
            spec=spec, values=values, measurer=measurer, style=style,
        )
    if style == "box_plot":
        return _measure_data_display_box_plot(spec=spec, values=values, measurer=measurer)
    raise ValueError(f"unsupported data_display style {style!r}")


def _measure_data_display_bars(*, spec, values, measurer, contiguous: bool):
    categories = values["categories"]
    raw_counts = [category["count"] for category in categories]
    counts = [float(count) for count in raw_counts]
    if any(count < 0 for count in counts):
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected="non-negative category counts",
            observed=f"{spec.ref} carries a negative count",
            hint="use non-negative counts -- a bar cannot fall below the axis",
        ))
    peak = max(counts) if counts else 0.0
    if peak <= 0:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected="at least one category with a positive count",
            observed=f"{spec.ref} draws bars all at zero height",
            hint="raise at least one category count above zero, or use a different display",
        ))
    width = DATA_DISPLAY_AXIS_WIDTH
    gap = 0.0 if contiguous else 0.24
    n = len(categories)
    # Bar width chosen so N bars plus (N-1) gaps span `DATA_DISPLAY_AXIS_WIDTH`
    # exactly. Fixed axis width means downstream tickets reading this kind's
    # extent get the same layout regardless of category count.
    bar_width = (width - gap * (n - 1)) / n
    if bar_width <= 0:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=f"at most {int(width // (gap or 1))} categories",
            observed=f"{spec.ref} declares {n} categories that leave no room per bar",
            hint="reduce `categories` -- adjacent bars have no room at this density",
        ))
    left = -width / 2
    axis_y = 0.0
    parts = {}
    payload_bars = []
    label_widths = []
    for index, (category, count, raw_count) in enumerate(zip(categories, counts, raw_counts)):
        bar_left = left + index * (bar_width + gap)
        bar_right = bar_left + bar_width
        bar_height = (count / peak) * DATA_DISPLAY_PLOT_HEIGHT if peak > 0 else 0.0
        parts[("mark", index)] = SemanticPart(
            "mark", index,
            Bounds(bar_left, bar_right, axis_y, axis_y + bar_height),
        )
        label_w, _label_h = measurer.measure(category["label"], "label")
        count_text = format_number(raw_count)
        count_w, count_h = measurer.measure(count_text, "label")
        label_widths.append(label_w)
        payload_bars.append({
            "label": category["label"], "count": count,
            "count_text": count_text,
            "count_width": count_w,
            "count_height": count_h,
            "left": bar_left, "right": bar_right,
            "height": bar_height,
        })
    _require_data_display_labels_do_not_collide(spec, payload_bars, label_widths)
    label_h = max(
        (measurer.measure(bar["label"], "label")[1] for bar in payload_bars),
        default=0.0,
    )
    count_label_top = axis_y + max(bar["height"] for bar in payload_bars) + DATA_DISPLAY_COUNT_LABEL_GAP + label_h
    bottom = axis_y - DATA_DISPLAY_AXIS_LABEL_GAP - label_h - _axis_title_room(values, measurer)
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(-width / 2, width / 2, bottom, count_label_top),
        parts=parts,
        payload={
            "display_style": values["display_style"],
            "axis_label": values.get("axis_label", ""),
            "axis_y": axis_y,
            "axis_left": -width / 2,
            "axis_right": width / 2,
            "bars": tuple(payload_bars),
            "label_center_y": axis_y - DATA_DISPLAY_AXIS_LABEL_GAP - label_h / 2,
            "count_label_gap": DATA_DISPLAY_COUNT_LABEL_GAP,
        },
    )


def _measure_data_display_number_line_points(*, spec, values, measurer, style: str):
    axis_min, axis_max = values["axis_min"], values["axis_max"]
    if axis_max <= axis_min:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected="axis_max strictly greater than axis_min",
            observed=(
                f"{spec.ref} axis [{format_number(axis_min)}, "
                f"{format_number(axis_max)}] is empty or inverted"
            ),
            hint="raise axis_max above axis_min so the axis has a positive span",
        ))
    width = DATA_DISPLAY_AXIS_WIDTH
    left, right = -width / 2, width / 2
    axis_y = 0.0
    parts = {}
    payload_values = []
    from collections import Counter
    stack_index = Counter()
    for index, value in enumerate(values["values"]):
        if not (axis_min <= value <= axis_max):
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}.values[{index}]",
                expected=(
                    f"a value inside [{format_number(axis_min)}, "
                    f"{format_number(axis_max)}]"
                ),
                observed=f"{spec.ref} carries {format_number(value)} outside the axis span",
                hint="move the value inside the axis range, or widen the axis span",
            ))
        u = left + (right - left) * float((value - axis_min) / (axis_max - axis_min))
        stack_level = stack_index[value]
        stack_index[value] += 1
        if style == "dot_plot":
            cy = axis_y + DATA_DISPLAY_DOT_RADIUS + stack_level * DATA_DISPLAY_DOT_PITCH
            parts[("mark", index)] = SemanticPart(
                "mark", index,
                Bounds(u - DATA_DISPLAY_DOT_RADIUS, u + DATA_DISPLAY_DOT_RADIUS,
                       cy - DATA_DISPLAY_DOT_RADIUS, cy + DATA_DISPLAY_DOT_RADIUS),
            )
            payload_values.append({"value": value, "u": u, "cy": cy})
        else:  # line_plot -- stack repeated values so the same X mark does
               # not stamp on itself and hide the frequency the plot claims to
               # show. Height check below rejects a stack that overruns the
               # reserved plot band.
            cy = axis_y + DATA_DISPLAY_MARK_HALF + 0.05 + stack_level * DATA_DISPLAY_MARK_PITCH
            parts[("mark", index)] = SemanticPart(
                "mark", index,
                Bounds(u - DATA_DISPLAY_MARK_HALF, u + DATA_DISPLAY_MARK_HALF,
                       cy - DATA_DISPLAY_MARK_HALF, cy + DATA_DISPLAY_MARK_HALF),
            )
            payload_values.append({"value": value, "u": u, "cy": cy})
    top = axis_y
    for part in parts.values():
        if part.bounds.top > top:
            top = part.bounds.top
    if top - axis_y > DATA_DISPLAY_PLOT_HEIGHT:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=(
                f"a display whose tallest stack fits {DATA_DISPLAY_PLOT_HEIGHT:g} scene units"
            ),
            observed=(
                f"{spec.ref} stacks marks {top - axis_y:.2f} units tall"
            ),
            hint=(
                "drop values so no single number is repeated more than fits the "
                "plot height, or widen the axis so repeats spread across values"
            ),
        ))
    tick_ticks = _data_display_axis_ticks(axis_min, axis_max, measurer)
    tick_label_h = max((h for _v, _t, _w, h in tick_ticks), default=0.0)
    tick_label_top = axis_y - DATA_DISPLAY_AXIS_LABEL_GAP
    tick_label_bottom = tick_label_top - tick_label_h
    axis_title_h = _axis_title_room(values, measurer)
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left - 0.1, right + 0.1, tick_label_bottom - axis_title_h, top + 0.1),
        parts=parts,
        payload={
            "display_style": style,
            "axis_label": values.get("axis_label", ""),
            "axis_y": axis_y,
            "axis_left": left,
            "axis_right": right,
            "axis_min": axis_min,
            "axis_max": axis_max,
            "values": tuple(payload_values),
            "ticks": tuple(
                {"value": value, "text": text, "u": _project(value, axis_min, axis_max, left, right),
                 "label_width": w, "label_height": h}
                for value, text, w, h in tick_ticks
            ),
            "tick_label_gap": DATA_DISPLAY_AXIS_LABEL_GAP,
            "dot_radius": DATA_DISPLAY_DOT_RADIUS,
            "mark_half": DATA_DISPLAY_MARK_HALF,
        },
    )


def _measure_data_display_box_plot(*, spec, values, measurer):
    axis_min, axis_max = values["axis_min"], values["axis_max"]
    if axis_max <= axis_min:
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected="axis_max strictly greater than axis_min",
            observed=(
                f"{spec.ref} axis [{format_number(axis_min)}, "
                f"{format_number(axis_max)}] is empty or inverted"
            ),
            hint="raise axis_max above axis_min so the axis has a positive span",
        ))
    summary = values["summary"]
    ordered = [summary["minimum"], summary["q1"], summary["median"], summary["q3"], summary["maximum"]]
    for a, b in zip(ordered, ordered[1:]):
        if b < a:
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}.summary",
                expected="a monotonic five-number summary (min <= q1 <= median <= q3 <= max)",
                observed=(
                    f"{spec.ref} summary out of order: "
                    f"min={format_number(summary['minimum'])}, "
                    f"q1={format_number(summary['q1'])}, "
                    f"median={format_number(summary['median'])}, "
                    f"q3={format_number(summary['q3'])}, "
                    f"max={format_number(summary['maximum'])}"
                ),
                hint="reorder the summary so each value is at least the previous one",
            ))
    for name, value in summary.items():
        if not (axis_min <= value <= axis_max):
            raise V3ValidationError(V3Failure(
                code="visual_extent_unrenderable",
                path=f"visuals.{spec.ref}.summary.{name}",
                expected=(
                    f"a summary value inside [{format_number(axis_min)}, "
                    f"{format_number(axis_max)}]"
                ),
                observed=f"{spec.ref} summary.{name} = {format_number(value)} outside the axis span",
                hint=f"move summary.{name} inside the axis range, or widen the axis span",
            ))
    width = DATA_DISPLAY_AXIS_WIDTH
    left, right = -width / 2, width / 2
    axis_y = 0.0
    projected = {
        name: _project(value, axis_min, axis_max, left, right)
        for name, value in summary.items()
    }
    box_top = axis_y + DATA_DISPLAY_BOX_HEIGHT / 2 + 0.4
    box_bottom = axis_y + 0.4 - DATA_DISPLAY_BOX_HEIGHT / 2
    # `mark[0]` addresses the whole box; the plan can point at the box as one
    # semantic element instead of picking a specific whisker or quartile.
    parts = {
        ("mark", 0): SemanticPart(
            "mark", 0,
            Bounds(projected["q1"], projected["q3"], box_bottom, box_top),
        ),
    }
    tick_ticks = _data_display_axis_ticks(axis_min, axis_max, measurer)
    tick_label_h = max((h for _v, _t, _w, h in tick_ticks), default=0.0)
    tick_label_bottom = axis_y - DATA_DISPLAY_AXIS_LABEL_GAP - tick_label_h
    axis_title_h = _axis_title_room(values, measurer)
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left - 0.1, right + 0.1, tick_label_bottom - axis_title_h, box_top + 0.1),
        parts=parts,
        payload={
            "display_style": "box_plot",
            "axis_label": values.get("axis_label", ""),
            "axis_y": axis_y,
            "axis_left": left,
            "axis_right": right,
            "axis_min": axis_min,
            "axis_max": axis_max,
            "summary": {name: float(value) for name, value in summary.items()},
            "projected": projected,
            "box_top": box_top,
            "box_bottom": box_bottom,
            "ticks": tuple(
                {"value": value, "text": text, "u": _project(value, axis_min, axis_max, left, right),
                 "label_width": w, "label_height": h}
                for value, text, w, h in tick_ticks
            ),
            "tick_label_gap": DATA_DISPLAY_AXIS_LABEL_GAP,
        },
    )


def _project(value, axis_min, axis_max, left, right) -> float:
    return left + (right - left) * float((value - axis_min) / (axis_max - axis_min))


def _axis_title_room(values, measurer) -> float:
    """Vertical room the optional axis title needs below the tick labels."""
    title = values.get("axis_label", "")
    if not title:
        return 0.0
    _w, h = measurer.measure(title, "label")
    return h + DATA_DISPLAY_AXIS_LABEL_GAP


def _data_display_axis_ticks(axis_min, axis_max, measurer):
    """At most eight numeric ticks along a data_display's number line.

    The finest stride from a fixed set of fractional / integer candidates that
    keeps tick count within `max_ticks` AND whose measured labels leave at
    least `DATA_DISPLAY_LABEL_INTER_GAP` between adjacent labels. Fractional
    candidates (1/8, 1/4, 1/2) are what make 5.MD.B.2 line plots on a
    sub-unit axis (e.g. [1/4, 3/4]) render labelled ticks -- integer-only
    stride would skip the whole span. Width-based thinning stops wide integer
    labels (13-digit counts, long fractions) from stamping on their neighbours.
    """
    axis_min_f = Fraction(axis_min)
    axis_max_f = Fraction(axis_max)
    if axis_max_f <= axis_min_f:
        return []
    max_ticks = 8
    width = DATA_DISPLAY_AXIS_WIDTH
    left, right = -width / 2, width / 2
    candidates = [Fraction(1, 8), Fraction(1, 4), Fraction(1, 2)]
    span = axis_max_f - axis_min_f
    decade = Fraction(1)
    while True:
        candidates.extend([decade, 2 * decade, 5 * decade])
        if decade >= span:
            break
        decade *= 10
    fallback = None
    for step in candidates:
        first = int(ceil(axis_min_f / step))
        last = int(floor(axis_max_f / step))
        if last < first:
            continue
        if last - first + 1 > max_ticks:
            continue
        measured = []
        for k in range(first, last + 1):
            value = Fraction(k) * step
            text = format_number(value)
            w, h = measurer.measure(text, "label")
            u = _project(value, axis_min_f, axis_max_f, left, right)
            measured.append((value, text, w, h, u))
        if _tick_labels_do_not_overlap(measured, DATA_DISPLAY_LABEL_INTER_GAP):
            return [(v, t, w, h) for v, t, w, h, _u in measured]
        if fallback is None:
            fallback = measured
    if fallback is None:
        return []
    for skip in range(2, len(fallback) + 1):
        thinned = fallback[::skip]
        if _tick_labels_do_not_overlap(thinned, DATA_DISPLAY_LABEL_INTER_GAP):
            return [(v, t, w, h) for v, t, w, h, _u in thinned]
    endpoints = [fallback[0]] + ([fallback[-1]] if len(fallback) > 1 else [])
    if _tick_labels_do_not_overlap(endpoints, DATA_DISPLAY_LABEL_INTER_GAP):
        return [(v, t, w, h) for v, t, w, h, _u in endpoints]
    return [(fallback[0][0], fallback[0][1], fallback[0][2], fallback[0][3])]


def _tick_labels_do_not_overlap(measured, min_gap):
    for a, b in zip(measured, measured[1:]):
        _va, _ta, wa, _ha, ua = a
        _vb, _tb, wb, _hb, ub = b
        if (ub - wb / 2) - (ua + wa / 2) < min_gap:
            return False
    return True


def _require_data_display_labels_do_not_collide(spec, payload_bars, label_widths):
    """Reject a bar_graph / histogram whose category or count labels would overlap.

    Two symmetric checks: category labels below the axis, and numeric count
    labels above each bar. Wide counts (e.g. three 13-digit values) can collide
    even when short category names fit, so measuring both keeps the display
    honest instead of silently stamping labels on top of each other.
    """
    def bar_center(bar):
        return bar["left"] + (bar["right"] - bar["left"]) / 2

    for a, b in zip(range(len(payload_bars) - 1), range(1, len(payload_bars))):
        gap = (bar_center(payload_bars[b]) - label_widths[b] / 2) - (
            bar_center(payload_bars[a]) + label_widths[a] / 2
        )
        if gap >= DATA_DISPLAY_LABEL_INTER_GAP:
            continue
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=(
                f"category labels separated by at least "
                f"{DATA_DISPLAY_LABEL_INTER_GAP:g} units"
            ),
            observed=(
                f"labels {payload_bars[a]['label']!r} and "
                f"{payload_bars[b]['label']!r} overlap by "
                f"{DATA_DISPLAY_LABEL_INTER_GAP - gap:.2f} units"
            ),
            hint=(
                f"shorten {payload_bars[a]['label']!r} or "
                f"{payload_bars[b]['label']!r}, or reduce `categories`"
            ),
        ))

    for a, b in zip(range(len(payload_bars) - 1), range(1, len(payload_bars))):
        ba, bb = payload_bars[a], payload_bars[b]
        x_gap = (bar_center(bb) - bb["count_width"] / 2) - (
            bar_center(ba) + ba["count_width"] / 2
        )
        if x_gap >= DATA_DISPLAY_LABEL_INTER_GAP:
            continue
        ya_bot = ba["height"] + DATA_DISPLAY_COUNT_LABEL_GAP
        ya_top = ya_bot + ba["count_height"]
        yb_bot = bb["height"] + DATA_DISPLAY_COUNT_LABEL_GAP
        yb_top = yb_bot + bb["count_height"]
        y_gap = max(ya_bot, yb_bot) - min(ya_top, yb_top)
        if y_gap >= DATA_DISPLAY_LABEL_INTER_GAP:
            continue
        raise V3ValidationError(V3Failure(
            code="visual_extent_unrenderable",
            path=f"visuals.{spec.ref}",
            expected=(
                f"count labels separated by at least "
                f"{DATA_DISPLAY_LABEL_INTER_GAP:g} units"
            ),
            observed=(
                f"counts {ba['count_text']!r} and "
                f"{bb['count_text']!r} above adjacent bars overlap by "
                f"{DATA_DISPLAY_LABEL_INTER_GAP - min(x_gap, y_gap):.2f} units"
            ),
            hint=(
                "reduce `categories`, or use smaller counts -- adjacent count "
                "labels have no room at this density"
            ),
        ))


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
    registry.register("data_display", _measure_data_display)
    return registry
