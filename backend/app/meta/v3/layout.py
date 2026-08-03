from collections.abc import Sequence
from dataclasses import dataclass

from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.geometry import (
    Bounds, MeasuredVisual, PlacedVisual, Point, SemanticPart, translate_bounds,
)


SAFE_FRAME = Bounds(-6.6, 6.6, -3.6, 3.6)
MIN_TEXT_SCALE = 0.7
GAP = 0.45
CONCLUSION_BAND = Bounds(SAFE_FRAME.left, SAFE_FRAME.right, SAFE_FRAME.bottom, -2.4)
INSTRUCTIONAL_FRAME = Bounds(
    SAFE_FRAME.left, SAFE_FRAME.right, CONCLUSION_BAND.top, SAFE_FRAME.top,
)


def scale_measured_visual(item: MeasuredVisual, scale: float) -> MeasuredVisual:
    scale_point = lambda point: Point(point.x * scale, point.y * scale)
    scale_bounds = lambda bounds: Bounds(
        bounds.left * scale, bounds.right * scale,
        bounds.bottom * scale, bounds.top * scale,
    )
    parts = {
        key: SemanticPart(part.part, part.index, scale_bounds(part.bounds))
        for key, part in item.parts.items()
    }
    paths = {
        name: [scale_point(point) for point in points]
        for name, points in item.paths.items()
    }
    return MeasuredVisual(
        ref=item.ref,
        bounds=scale_bounds(item.bounds),
        parts=parts,
        paths=paths,
        payload=item.payload,
    )


@dataclass(frozen=True)
class _Arrangement:
    """Which supporting visuals sit beside the primary and which stack over it."""

    primary: MeasuredVisual
    left: list[MeasuredVisual]
    right: list[MeasuredVisual]
    above: list[MeasuredVisual]
    below: list[MeasuredVisual]


def place_vertical_lesson(measured_visuals: Sequence[MeasuredVisual]) -> list[PlacedVisual]:
    instructional = [item for item in measured_visuals if item.ref != "evaluated_answer"]
    conclusion = [item for item in measured_visuals if item.ref == "evaluated_answer"]
    arrangement = _arrange(instructional)
    scale = min(
        1.0,
        _fit_instructional_scale(arrangement, INSTRUCTIONAL_FRAME),
        _fit_scale(conclusion, CONCLUSION_BAND),
    )
    if scale < MIN_TEXT_SCALE:
        raise V3ValidationError(V3Failure(
            code="below_minimum_text_scale",
            path="visuals",
            expected=f"a uniform scale of at least {MIN_TEXT_SCALE:g}",
            observed=f"{scale:g}",
            hint="reduce visual content so the lesson remains readable",
        ))
    placed_by_ref = {
        item.measured.ref: item
        for item in [
            *_place_instructional(arrangement, INSTRUCTIONAL_FRAME, scale),
            *_place_centered_stack(conclusion, CONCLUSION_BAND, scale),
        ]
    }
    return [placed_by_ref[item.ref] for item in measured_visuals]


def _arrange(instructional: Sequence[MeasuredVisual]) -> _Arrangement:
    """Send each supporting visual beside the primary, or to a row of its own.

    A visual placed beside the primary has to fit in half the frame minus the
    primary's half-width -- roughly 3 units, against the 13.2 a full-width row
    offers. Forcing every supporting visual into that slot meant one ordinary
    label ("Perimeter = 2 x (length + width)", 6.6 units) shrank the whole
    lesson's uniform scale below MIN_TEXT_SCALE and failed the candidate
    outright, for want of using space the frame already had.

    The split is decided on unscaled measurements so it does not depend on the
    scale being solved for.
    """
    if not instructional:
        return _Arrangement(None, [], [], [], [])
    primary, *supporting = instructional
    budget = _side_budget(primary, INSTRUCTIONAL_FRAME)
    beside = [item for item in supporting if _width(item) <= budget]
    stacked = [item for item in supporting if _width(item) > budget]
    left, right = _balanced_pair(beside, _stack_width)
    above, below = _balanced_pair(stacked, lambda items: _stack_height(items, GAP))
    return _Arrangement(primary, left, right, above, below)


def _side_budget(primary: MeasuredVisual, frame: Bounds) -> float:
    half_width = (frame.right - frame.left) / 2
    return half_width - _width(primary) / 2 - GAP


def _width(item: MeasuredVisual) -> float:
    return item.bounds.right - item.bounds.left


def _height(item: MeasuredVisual) -> float:
    return item.bounds.top - item.bounds.bottom


def _fit_scale(items: Sequence[MeasuredVisual], frame: Bounds) -> float:
    height = _stack_height(items, GAP)
    return (frame.top - frame.bottom) / height if height else 1.0


def _stack_height(items: Sequence[MeasuredVisual], gap: float) -> float:
    if not items:
        return 0
    return sum(item.bounds.top - item.bounds.bottom for item in items) + gap * (len(items) - 1)


def _fit_instructional_scale(arrangement: _Arrangement, frame: Bounds) -> float:
    if arrangement.primary is None:
        return 1.0
    primary = arrangement.primary
    vertical_scale = _fit_extent(
        _column_height(arrangement, GAP), frame.top - frame.bottom,
    )
    half_width = (frame.right - frame.left) / 2
    horizontal_scale = min(
        _fit_extent(_horizontal_extent(primary, arrangement.left), half_width),
        _fit_extent(_horizontal_extent(primary, arrangement.right), half_width),
    )
    # A stacked row spans the whole frame, not half of it.
    stacked = arrangement.above + arrangement.below
    widest_row = max((_width(item) for item in stacked), default=0.0)
    row_scale = _fit_extent(widest_row, frame.right - frame.left)
    return min(horizontal_scale, vertical_scale, row_scale)


def _band_height(arrangement: _Arrangement) -> float:
    """Height of the row holding the primary visual and anything beside it."""
    beside = arrangement.left + arrangement.right
    return max([_height(arrangement.primary), *(_height(item) for item in beside)])


def _column_height(arrangement: _Arrangement, gap: float) -> float:
    height = _band_height(arrangement)
    for stack in (arrangement.above, arrangement.below):
        if stack:
            height += _stack_height(stack, gap) + gap
    return height


def _fit_extent(extent: float, available: float) -> float:
    return available / extent if extent else 1.0


def _horizontal_extent(primary: MeasuredVisual, supporting: Sequence[MeasuredVisual]) -> float:
    primary_half_width = (primary.bounds.right - primary.bounds.left) / 2
    if not supporting:
        return primary_half_width
    return primary_half_width + GAP + _stack_width(supporting)


def _stack_width(items: Sequence[MeasuredVisual]) -> float:
    if not items:
        return 0
    return sum(item.bounds.right - item.bounds.left for item in items) + GAP * (len(items) - 1)


def _balanced_pair(items, extent_of):
    """Split items into two groups of comparable extent, filling the first."""
    first, second = [], []
    for item in items:
        destination = first if extent_of(first) <= extent_of(second) else second
        destination.append(item)
    return first, second


def _place_instructional(
    arrangement: _Arrangement, frame: Bounds, scale: float,
) -> list[PlacedVisual]:
    if arrangement.primary is None:
        return []
    scaled = _Arrangement(
        scale_measured_visual(arrangement.primary, scale),
        *([scale_measured_visual(item, scale) for item in stack]
          for stack in (arrangement.left, arrangement.right, arrangement.above, arrangement.below)),
    )
    gap = GAP * scale
    primary, left, right = scaled.primary, scaled.left, scaled.right
    band_height = _band_height(scaled)

    # Lay the column out from its top edge so the whole thing -- rows above, the
    # primary's band, rows below -- ends up centred in the frame.
    column_top = frame.center.y + _column_height(scaled, gap) / 2
    placed = _stack_rows(scaled.above, column_top, gap, scale)
    band_top = column_top - (_stack_height(scaled.above, gap) + gap if scaled.above else 0.0)
    center_y = band_top - band_height / 2
    primary_offset = Point(-primary.bounds.center.x, center_y - primary.bounds.center.y)
    # The side cursors start from where the primary visual ACTUALLY lands, not
    # from its untranslated measured box. The two coincide only when the box is
    # centred on its own origin, which was true of every primary visual until
    # `measure_rectangle` began reserving space for dimension labels outside the
    # shape. For an off-centre box, untranslated bounds put each side stack wrong
    # by exactly `primary_offset.x` -- off the frame on one side, over the
    # primary visual on the other.
    primary_bounds = translate_bounds(primary.bounds, primary_offset)
    placed.append(PlacedVisual(primary, primary_offset, scale))
    placed.extend(_place_supporting_side(left, primary_bounds, center_y, -1, scale))
    placed.extend(_place_supporting_side(right, primary_bounds, center_y, 1, scale))
    band_bottom = center_y - band_height / 2
    placed.extend(_stack_rows(scaled.below, band_bottom - gap, gap, scale))
    return placed


def _stack_rows(
    items: Sequence[MeasuredVisual], top: float, gap: float, scale: float,
) -> list[PlacedVisual]:
    """Centre each item horizontally and stack them downward from `top`."""
    placed, cursor = [], top
    for item in items:
        center_y = cursor - _height(item) / 2
        placed.append(PlacedVisual(
            item,
            Point(-item.bounds.center.x, center_y - item.bounds.center.y),
            scale,
        ))
        cursor -= _height(item) + gap
    return placed


def _place_supporting_side(
    items: Sequence[MeasuredVisual],
    primary_bounds: Bounds,
    center_y: float,
    direction: int,
    scale: float,
) -> list[PlacedVisual]:
    cursor = (primary_bounds.left if direction < 0 else primary_bounds.right) + direction * GAP * scale
    placed = []
    for item in items:
        width = item.bounds.right - item.bounds.left
        center_x = cursor + direction * width / 2
        placed.append(PlacedVisual(
            item,
            Point(center_x - item.bounds.center.x, center_y - item.bounds.center.y),
            scale,
        ))
        cursor += direction * (width + GAP * scale)
    return placed


def _place_centered_stack(
    items: Sequence[MeasuredVisual], frame: Bounds, scale: float,
) -> list[PlacedVisual]:
    scaled = [scale_measured_visual(item, scale) for item in items]
    cursor = frame.center.y + _stack_height(scaled, GAP * scale) / 2
    placed = []
    for item in scaled:
        height = item.bounds.top - item.bounds.bottom
        center_y = cursor - height / 2
        placed.append(PlacedVisual(
            item,
            Point(-item.bounds.center.x, center_y - item.bounds.center.y),
            scale,
        ))
        cursor -= height + GAP * scale
    return placed
