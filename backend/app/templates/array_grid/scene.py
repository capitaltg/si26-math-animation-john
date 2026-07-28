from manim import *

from app.templates._shared.chain_math import format_operation_caption, run_multiplicative_chain
from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_to_frame, fit_width
from app.templates.array_grid.layout import grid_dimensions

# Bumped by hand whenever a human changes this template's scene.py/params.py/guard.py.
# Included in its TemplateRef.artifact_hash (spec §8) so a contract change invalidates
# any previously-pinned Scene rather than silently reusing stale rendering behavior.
CONTRACT_VERSION = 1


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


def fit_grid_with_label(dots, label):
    group = VGroup(dots, label)
    fit_to_frame(group)

    safe_top = config.frame_height / 2 - FRAME_MARGIN
    safe_bottom = -config.frame_height / 2 + FRAME_MARGIN
    if group.get_top()[1] > safe_top:
        group.shift(DOWN * (group.get_top()[1] - safe_top))
    elif group.get_bottom()[1] < safe_bottom:
        group.shift(UP * (safe_bottom - group.get_bottom()[1]))


def draw_array_grid(scene, params):
    if not params.steps:
        dots = build_grid_dots(params.rows, params.cols)
        label = Text(f"{params.rows} x {params.cols}")
        fit_width(label)
        label.next_to(dots, UP)
        fit_grid_with_label(dots, label)

        scene.play(Write(label))
        scene.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))
        scene.wait(1)
        return

    totals = run_multiplicative_chain(
        params.starting_total(),
        [(step.operation, step.factor) for step in params.steps],
    )

    rows, cols = grid_dimensions(totals[0])
    dots = build_grid_dots(rows, cols)
    label = build_grid_total_label(rows, cols, totals[0])
    label.next_to(dots, UP)
    fit_grid_with_label(dots, label)
    scene.play(Write(label))
    scene.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))

    caption = None
    current_total = totals[0]
    for step, total in zip(params.steps, totals[1:]):
        new_rows, new_cols = grid_dimensions(total)
        new_dots = build_grid_dots(new_rows, new_cols)
        new_dots.move_to(dots.get_center())
        new_label = build_grid_total_label(new_rows, new_cols, total)
        new_label.next_to(new_dots, UP)
        fit_grid_with_label(new_dots, new_label)
        new_caption = build_operation_caption(current_total, step.operation, step.factor, total)
        if new_caption.original_text == new_label.original_text:
            caption_animation = FadeOut(caption) if caption is not None else None
            next_caption = None
        else:
            caption_animation = (
                Write(new_caption)
                if caption is None
                else ReplacementTransform(caption, new_caption)
            )
            next_caption = new_caption

        animations = [
            ReplacementTransform(dots, new_dots),
            ReplacementTransform(label, new_label),
        ]
        if caption_animation is not None:
            animations.append(caption_animation)
        scene.play(*animations)
        dots, label, caption = new_dots, new_label, next_caption
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
    show_problem_counter = False
