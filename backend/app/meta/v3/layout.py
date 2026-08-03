from collections.abc import Sequence

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


def place_vertical_lesson(measured_visuals: Sequence[MeasuredVisual]) -> list[PlacedVisual]:
    instructional = [item for item in measured_visuals if item.ref != "evaluated_answer"]
    conclusion = [item for item in measured_visuals if item.ref == "evaluated_answer"]
    supporting_sides = _supporting_sides(instructional[1:])
    scale = min(
        1.0,
        _fit_instructional_scale(instructional, INSTRUCTIONAL_FRAME, supporting_sides),
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
            *_place_instructional(instructional, supporting_sides, INSTRUCTIONAL_FRAME, scale),
            *_place_centered_stack(conclusion, CONCLUSION_BAND, scale),
        ]
    }
    return [placed_by_ref[item.ref] for item in measured_visuals]


def _fit_scale(items: Sequence[MeasuredVisual], frame: Bounds) -> float:
    height = _stack_height(items, GAP)
    return (frame.top - frame.bottom) / height if height else 1.0


def _stack_height(items: Sequence[MeasuredVisual], gap: float) -> float:
    if not items:
        return 0
    return sum(item.bounds.top - item.bounds.bottom for item in items) + gap * (len(items) - 1)


def _fit_instructional_scale(
    items: Sequence[MeasuredVisual],
    frame: Bounds,
    supporting_sides: tuple[Sequence[MeasuredVisual], Sequence[MeasuredVisual]],
) -> float:
    if not items:
        return 1.0
    primary, *supporting = items
    tallest = max(item.bounds.top - item.bounds.bottom for item in items)
    vertical_scale = _fit_extent(tallest, frame.top - frame.bottom)
    if not supporting:
        return vertical_scale
    left, right = supporting_sides
    half_width = (frame.right - frame.left) / 2
    horizontal_scale = min(
        _fit_extent(_horizontal_extent(primary, left), half_width),
        _fit_extent(_horizontal_extent(primary, right), half_width),
    )
    return min(horizontal_scale, vertical_scale)


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


def _supporting_sides(
    supporting: Sequence[MeasuredVisual],
) -> tuple[list[MeasuredVisual], list[MeasuredVisual]]:
    left, right = [], []
    for item in supporting:
        destination = left if _stack_width(left) <= _stack_width(right) else right
        destination.append(item)
    return left, right


def _place_instructional(
    items: Sequence[MeasuredVisual],
    supporting_sides: tuple[Sequence[MeasuredVisual], Sequence[MeasuredVisual]],
    frame: Bounds,
    scale: float,
) -> list[PlacedVisual]:
    if not items:
        return []
    primary = scale_measured_visual(items[0], scale)
    left = [scale_measured_visual(item, scale) for item in supporting_sides[0]]
    right = [scale_measured_visual(item, scale) for item in supporting_sides[1]]
    center_y = frame.center.y
    primary_offset = Point(-primary.bounds.center.x, center_y - primary.bounds.center.y)
    # The side cursors start from where the primary visual ACTUALLY lands, not
    # from its untranslated measured box. The two coincide only when the box is
    # centred on its own origin, which was true of every primary visual until
    # `measure_rectangle` began reserving space for dimension labels outside the
    # shape. For an off-centre box, untranslated bounds put each side stack wrong
    # by exactly `primary_offset.x` -- off the frame on one side, over the
    # primary visual on the other.
    primary_bounds = translate_bounds(primary.bounds, primary_offset)
    placed = [PlacedVisual(primary, primary_offset, scale)]
    placed.extend(_place_supporting_side(left, primary_bounds, center_y, -1, scale))
    placed.extend(_place_supporting_side(right, primary_bounds, center_y, 1, scale))
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
