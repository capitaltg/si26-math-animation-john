from math import ceil, cos, sin, tau
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
        _require_renderable_extent(measured, values)
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
}


#: Fields whose value sets a visual's size, so a failure can name the number to
#: change rather than telling a reviewer to "reduce visual content".
_SIZE_DRIVING_FIELDS = ("maximum", "columns", "rows", "count", "parts", "values")

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

#: The largest part count any kind could ever need. The tightest pitch is a bar
#: segment at 0.65 units, so the 18.9-unit width limit admits ~29; `object_set`
#: packs five per row, so the 8.6-unit height limit admits ~65. This is a
#: deliberately loose over-approximation -- its only job is to keep a factory from
#: looping past what fits, leaving `_require_renderable_extent` to decide
#: precisely.
MAX_PART_CARDINALITY = 128


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


def _is_whole(value) -> bool:
    return getattr(value, "denominator", 1) == 1


def _require_renderable_extent(measured, values) -> None:
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
    drivers = ", ".join(
        f"{name}={_describe(values[name])}"
        for name in _SIZE_DRIVING_FIELDS if name in values
    )
    raise V3ValidationError(V3Failure(
        code="visual_extent_unrenderable",
        path=f"visuals.{measured.ref}",
        expected=f"a visual within {width_limit:.1f} x {height_limit:.1f} units",
        observed=f"{measured.ref} spans {width:.1f} x {height:.1f} units ({drivers})",
        hint=f"reduce the value driving this visual's size ({drivers or 'its size field'})",
    ))


def _describe(value):
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


def _measure_number_line(*, spec, values, measurer):
    minimum, maximum = values["minimum"], values["maximum"]
    if maximum <= minimum:
        raise ValueError("number_line maximum must exceed minimum")
    left, right = -2.75, 2.75
    markers = values["markers"]
    parts = {}
    labels = []
    for index, marker in enumerate(markers):
        if not minimum <= marker <= maximum:
            raise ValueError(f"marker {marker} outside [{minimum}, {maximum}]")
        x = left + (right - left) * float((marker - minimum) / (maximum - minimum))
        parts[("marker", index)] = SemanticPart("marker", index, Bounds(x, x, 0, 0))
        labels.append(format_number(marker))
    # Reserve the strip the labels occupy, so layout does not place the next
    # visual on top of them. Horizontal bounds stay at +/-2.75: `_line_visual`
    # draws the line across the full bounds, so padding them lengthens the line.
    label_height = max(
        (measurer.measure(text, "label")[1] for text in labels), default=0.0,
    )
    bottom = -0.2 - MARKER_LABEL_GAP - label_height
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, right, bottom, 0.2),
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
    registry.register("object_set", _measure_object_set)
    registry.register("label", _measure_label)
    registry.register("answer_expression", _measure_answer)
    return registry
