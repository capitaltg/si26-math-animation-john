from manim import *

from app.templates._shared.chain_math import format_operation_caption, run_multiplicative_chain
from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_width


def build_grid_dots(rows, cols):
    dots = VGroup()
    for r in range(rows):
        for c in range(cols):
            dot = Dot(radius=0.15, color=BLUE)
            dot.move_to([c * 0.6, -r * 0.6, 0])
            dots.add(dot)
    dots.move_to(ORIGIN)
    return dots


def build_grid_total_label(rows, cols, total):
    label = Text(f"{rows} × {cols} = {total}").scale(0.8)
    fit_width(label)
    return label


def build_operation_caption(a, operation, b, result):
    caption = Text(format_operation_caption(a, operation, b, result))
    fit_width(caption)
    caption.to_edge(DOWN, buff=FRAME_MARGIN)
    return caption


def draw_array_grid(scene, params):
    if not params.steps:
        dots = build_grid_dots(params.rows, params.cols)
        label = Text(f"{params.rows} x {params.cols}").to_edge(UP)

        scene.play(Write(label))
        scene.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))
        scene.wait(1)
        return

    cols = params.cols
    totals = run_multiplicative_chain(
        params.rows * cols, [(step.operation, step.factor) for step in params.steps]
    )

    dots = build_grid_dots(params.rows, cols)
    label = build_grid_total_label(params.rows, cols, totals[0])
    label.next_to(dots, UP)
    scene.play(Write(label))
    scene.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))

    caption = None
    current_total = totals[0]
    for step, total in zip(params.steps, totals[1:]):
        new_rows = total // cols
        new_dots = build_grid_dots(new_rows, cols)
        new_dots.move_to(dots.get_center())
        new_label = build_grid_total_label(new_rows, cols, total)
        new_label.next_to(new_dots, UP)
        new_caption = build_operation_caption(current_total, step.operation, step.factor, total)
        caption_animation = Write(new_caption) if caption is None else Transform(caption, new_caption)

        scene.play(
            Transform(dots, new_dots),
            Transform(label, new_label),
            caption_animation,
        )
        dots, label, caption = new_dots, new_label, new_caption
        current_total = total

    scene.wait(1)


class ArrayGridScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("ArrayGridScene.params must be set before construct() runs")
        draw_array_grid(self, self.params)


from app.templates._shared.chained_scene import ChainedScene


class ChainedArrayGridScene(ChainedScene):
    draw_fn = staticmethod(draw_array_grid)
