from manim import Text


FONT_SIZES = {
    "math_value": 48,
    "label": 36,
    # Coordinate-plane vertex/pivot/tick labels sit on a grid where one unit
    # spans only ~0.4 scene units, so a full "label"-sized glyph swamps
    # neighbouring cells. A dedicated smaller role keeps A/B/C (with primes
    # after rotation) inside their own vertex's cell and keeps the tick
    # numbers on both axes from crowding the axis line.
    "polygon_label": 24,
}


class ManimTextMeasurer:
    def measure(self, text: str, font_role: str) -> tuple[float, float]:
        mobject = Text(text, font_size=FONT_SIZES[font_role])
        return float(mobject.width), float(mobject.height)
