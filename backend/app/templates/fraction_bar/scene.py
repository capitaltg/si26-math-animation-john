from manim import *

from app.templates._shared.chain_math import format_operation_caption, run_additive_chain
from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_width
from app.templates._shared.fraction_cells import build_fraction_cells


def build_fraction_caption(a_numerator, operation, b_numerator, result_numerator, denominator):
    caption_text = format_operation_caption(
        f"{a_numerator}/{denominator}",
        operation,
        f"{b_numerator}/{denominator}",
        f"{result_numerator}/{denominator}",
    )
    caption = Text(caption_text).scale(0.6)
    fit_width(caption)
    caption.to_edge(DOWN, buff=FRAME_MARGIN)
    return caption


def draw_fraction_bar(scene, params):
    denominator = params.denominator
    values = run_additive_chain(
        params.start_numerator, [(step.operation, step.numerator) for step in params.steps]
    )

    n_cells = max(max(values), denominator)
    cells = build_fraction_cells(n_cells)
    scene.play(Create(cells))

    label = Text(f"{values[0]}/{denominator}").scale(0.6).next_to(cells, UP)
    scene.play(Write(label))

    current = values[0]
    if current:
        scene.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current)])

    caption = None
    for step, value in zip(params.steps, values[1:]):
        new_label = Text(f"{value}/{denominator}").scale(0.6).next_to(cells, UP)
        new_caption = build_fraction_caption(current, step.operation, step.numerator, value, denominator)
        caption_animation = Write(new_caption) if caption is None else Transform(caption, new_caption)

        if value > current:
            scene.play(
                *[cells[i].animate.set_fill(GREEN, opacity=0.8) for i in range(current, value)],
                Transform(label, new_label),
                caption_animation,
            )
            scene.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current, value)])
        elif value < current:
            scene.play(
                *[cells[i].animate.set_fill(BLUE, opacity=0.0) for i in range(value, current)],
                Transform(label, new_label),
                caption_animation,
            )
        caption = new_caption
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
