from manim import Text


FONT_SIZES = {
    "math_value": 48,
    "label": 36,
}


class ManimTextMeasurer:
    def measure(self, text: str, font_role: str) -> tuple[float, float]:
        mobject = Text(text, font_size=FONT_SIZES[font_role])
        return float(mobject.width), float(mobject.height)
