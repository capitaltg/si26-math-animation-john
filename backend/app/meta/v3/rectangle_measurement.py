from app.meta.v3.geometry import Bounds, MeasuredVisual, Point, SemanticPart

# Clear of the edge each label names, without crowding it.
LABEL_GAP = 0.28


def measure_rectangle(*, ref, length, width, unit, measurer) -> MeasuredVisual:
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
    # The measured dimensions have to be visible for a measurement lesson to
    # teach anything, so they are part of the visual rather than something a
    # plan has to remember to annotate -- and, unlike a callout's frozen text,
    # they re-resolve from `length`/`width` on every render, so a template reused
    # on another problem still labels that problem's numbers.
    length_text, width_text = f"{_format(length)} {unit}".strip(), f"{_format(width)} {unit}".strip()
    length_size = measurer.measure(length_text, "label")
    width_size = measurer.measure(width_text, "label")
    length_label_bounds = _label_below(length_text, length_size, bottom)
    width_label_bounds = _label_left_of(width_text, width_size, left)

    parts = {
        ("length_label", 0): SemanticPart("length_label", 0, length_label_bounds),
        ("width_label", 0): SemanticPart("width_label", 0, width_label_bounds),
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
        # Widened to contain the labels: layout reserves space from these bounds,
        # so a box covering only the shape would let the labels land wherever the
        # neighbouring visual already is.
        bounds=Bounds(
            min(left, width_label_bounds.left), right,
            min(bottom, length_label_bounds.bottom), top,
        ),
        parts=parts,
        paths={"perimeter": (*vertices, vertices[0])},
        payload={
            "length": length, "width": width, "unit": unit,
            "length_label": length_text, "width_label": width_text,
        },
    )


def _label_below(text: str, size, edge_bottom: float) -> Bounds:
    text_width, text_height = size
    top = edge_bottom - LABEL_GAP
    return Bounds(-text_width / 2, text_width / 2, top - text_height, top)


def _label_left_of(text: str, size, edge_left: float) -> Bounds:
    text_width, text_height = size
    right = edge_left - LABEL_GAP
    return Bounds(right - text_width, right, -text_height / 2, text_height / 2)


def _format(value) -> str:
    return str(value.numerator) if getattr(value, "denominator", 1) == 1 else str(value)
