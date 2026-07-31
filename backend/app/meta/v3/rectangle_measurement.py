from app.meta.v3.geometry import Bounds, MeasuredVisual, Point, SemanticPart


def measure_rectangle(*, ref, length, width, unit) -> MeasuredVisual:
    if length <= 0 or width <= 0:
        raise ValueError("rectangle dimensions must be positive")
    ratio = max(0.25, min(4.0, float(length / width)))
    height = min(3.0, 5.5 / ratio)
    display_width = height * ratio
    left, right = -display_width / 2, display_width / 2
    bottom, top = -height / 2, height / 2
    vertices = (
        Point(left, bottom),
        Point(right, bottom),
        Point(right, top),
        Point(left, top),
    )
    edge_bounds = (
        Bounds(left, right, bottom, bottom),
        Bounds(right, right, bottom, top),
        Bounds(left, right, top, top),
        Bounds(left, left, bottom, top),
    )
    parts = {
        **{
            ("edge", index): SemanticPart("edge", index, bounds)
            for index, bounds in enumerate(edge_bounds)
        },
        ("length_edge", 0): SemanticPart("length_edge", 0, edge_bounds[0]),
        ("length_edge", 1): SemanticPart("length_edge", 1, edge_bounds[2]),
        ("width_edge", 0): SemanticPart("width_edge", 0, edge_bounds[3]),
        ("width_edge", 1): SemanticPart("width_edge", 1, edge_bounds[1]),
        **{
            ("vertex", index): SemanticPart(
                "vertex", index, Bounds(vertex.x, vertex.x, vertex.y, vertex.y)
            )
            for index, vertex in enumerate(vertices)
        },
    }
    return MeasuredVisual(
        ref=ref,
        bounds=Bounds(left, right, bottom, top),
        parts=parts,
        paths={"perimeter": (*vertices, vertices[0])},
        payload={"length": length, "width": width, "unit": unit},
    )
