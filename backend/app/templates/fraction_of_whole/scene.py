from manim import BLUE, UP, Create, Scene, Text, Write

from app.templates._shared.fraction_cells import build_fraction_cells


def draw_fraction_of_whole(scene, params):
    numerator = params.numerator
    denominator = params.denominator

    cells = build_fraction_cells(denominator)
    scene.play(Create(cells))

    label = Text(f"{numerator}/{denominator}").scale(0.6).next_to(cells, UP)
    scene.play(Write(label))

    scene.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(numerator)])
    scene.wait(1)


class FractionOfWholeScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("FractionOfWholeScene.params must be set before construct() runs")
        draw_fraction_of_whole(self, self.params)


from app.templates._shared.chained_scene import ChainedScene


class ChainedFractionOfWholeScene(ChainedScene):
    draw_fn = staticmethod(draw_fraction_of_whole)
