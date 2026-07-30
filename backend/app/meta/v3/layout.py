from collections.abc import Sequence

from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.geometry import Bounds, MeasuredVisual, PlacedVisual, Point, SemanticPart


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
    scale = min(
        1.0,
        _fit_scale(instructional, INSTRUCTIONAL_FRAME),
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
            *_place_centered_stack(instructional, INSTRUCTIONAL_FRAME, scale),
            *_place_centered_stack(conclusion, CONCLUSION_BAND, scale),
        ]
    }
    return [placed_by_ref[item.ref] for item in measured_visuals]


def _fit_scale(items: Sequence[MeasuredVisual], frame: Bounds) -> float:
    height = _stack_height(items, GAP)
    return (frame.top - frame.bottom) / height if height else 1.0


def _stack_height(items: Sequence[MeasuredVisual], gap: float) -> float:
    return sum(item.bounds.top - item.bounds.bottom for item in items) + gap * (len(items) - 1)


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
        ))
        cursor -= height + GAP * scale
    return placed
