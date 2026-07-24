from manim import *

from app.templates._shared.fraction_cells import build_fraction_cells


def draw_fraction_bar(scene, params):
    denominator = params.denominator
    total = params.start_numerator
    values = [total]
    for step in params.steps:
        total = total + step.numerator if step.operation == "add" else total - step.numerator
        values.append(total)

    n_cells = max(max(values), denominator)
    cells = build_fraction_cells(n_cells)
    scene.play(Create(cells))

    label = Text(f"{values[0]}/{denominator}").scale(0.6).next_to(cells, UP)
    scene.play(Write(label))

    current = values[0]
    if current:
        scene.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current)])

    for value in values[1:]:
        new_label = Text(f"{value}/{denominator}").scale(0.6).next_to(cells, UP)
        if value > current:
            scene.play(
                *[cells[i].animate.set_fill(GREEN, opacity=0.8) for i in range(current, value)],
                Transform(label, new_label),
            )
            scene.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current, value)])
        elif value < current:
            scene.play(
                *[cells[i].animate.set_fill(BLUE, opacity=0.0) for i in range(value, current)],
                Transform(label, new_label),
            )
        current = value

    scene.wait(1)


class FractionBarScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("FractionBarScene.params must be set before construct() runs")
        draw_fraction_bar(self, self.params)


from app.templates._shared.chained_scene import ChainedScene


class ChainedFractionBarScene(ChainedScene):
    draw_fn = staticmethod(draw_fraction_bar)
