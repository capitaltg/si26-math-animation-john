from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.geometry import Bounds, MeasuredVisual, PlacedVisual, Point, SemanticPart


SAFE_FRAME = Bounds(-6.6, 6.6, -3.6, 3.6)
MIN_TEXT_SCALE = 0.7


def scale_measured_visual(item, scale):
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


def place_vertical_lesson(measured_visuals):
    gap = 0.45
    content_height = sum(item.bounds.top - item.bounds.bottom for item in measured_visuals)
    content_height += gap * (len(measured_visuals) - 1)
    scale = min(1.0, (SAFE_FRAME.top - SAFE_FRAME.bottom) / content_height) if content_height else 1.0
    if scale < MIN_TEXT_SCALE:
        raise V3ValidationError(V3Failure(
            code="below_minimum_text_scale",
            path="visuals",
            expected=f"a uniform scale of at least {MIN_TEXT_SCALE:g}",
            observed=f"{scale:g}",
            hint="reduce visual content so the lesson remains readable",
        ))
    scaled = [scale_measured_visual(item, scale) for item in measured_visuals]
    cursor = SAFE_FRAME.top
    placed = []
    for item in scaled:
        height = item.bounds.top - item.bounds.bottom
        center_y = cursor - height / 2
        placed.append(PlacedVisual(item, Point(-item.bounds.center.x, center_y)))
        cursor -= height + gap
    return placed
