from app.meta.v3.geometry import Bounds, MeasuredVisual, SemanticPart


def measure_ordered_values(*, ref, values, measurer, gap) -> MeasuredVisual:
    sizes = [measurer.measure(value, "math_value") for value in values]
    total_width = sum(width for width, _ in sizes) + gap * (len(sizes) - 1)
    cursor = -total_width / 2
    parts = {}
    for index, (value, (width, height)) in enumerate(zip(values, sizes)):
        bounds = Bounds(cursor, cursor + width, -height / 2, height / 2)
        parts[("item", index)] = SemanticPart("item", index, bounds)
        cursor += width + gap
    max_height = max(height for _, height in sizes)
    return MeasuredVisual(
        ref=ref,
        bounds=Bounds(-total_width / 2, total_width / 2, -max_height / 2, max_height / 2),
        parts=parts,
        paths={},
        payload={"values": tuple(values)},
    )
