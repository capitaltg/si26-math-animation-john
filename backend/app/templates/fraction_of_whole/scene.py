from manim import BLUE, UP, Create, Scene, Text, Write

from app.templates._shared.fraction_cells import build_fraction_cells


class FractionOfWholeScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("FractionOfWholeScene.params must be set before construct() runs")

        numerator = self.params.numerator
        denominator = self.params.denominator

        cells = build_fraction_cells(denominator)
        self.play(Create(cells))

        label = Text(f"{numerator}/{denominator}").scale(0.6).next_to(cells, UP)
        self.play(Write(label))

        self.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(numerator)])
        self.wait(1)
