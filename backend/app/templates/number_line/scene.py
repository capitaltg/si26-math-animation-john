from manim import *

from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_width


def build_number_line_label(marker, value):
    label = Text(str(value))
    fit_width(label)
    label.next_to(marker, UP)
    label.shift_onto_screen(buff=FRAME_MARGIN)
    return label


def _number_line_values(params):
    running = params.start
    values = [running]
    for step in params.steps:
        running = running + step.amount if step.operation == "add" else running - step.amount
        values.append(running)
    return values


def number_line_continues_from(previous, current):
    return _number_line_values(previous)[-1] == current.start


def number_line_chain_range(items):
    values = [value for item in items for value in _number_line_values(item)]
    return min(values) - 2, max(values) + 2


def _animate_number_line_steps(scene, params):
    running = scene.running_value
    for step in params.steps:
        new_value = running + step.amount if step.operation == "add" else running - step.amount
        arrow = Arrow(
            scene.number_line.number_to_point(running),
            scene.number_line.number_to_point(new_value),
            buff=0,
            color=GREEN if step.operation == "add" else ORANGE,
        )
        scene.play(Create(arrow))
        scene.current_problem_arrows.append(arrow)
        new_marker = Dot(scene.number_line.number_to_point(new_value), color=RED)
        new_label = build_number_line_label(new_marker, new_value)
        scene.play(Transform(scene.marker, new_marker), Transform(scene.label, new_label))
        running = new_value
        scene.running_value = running


def draw_number_line(scene, params, value_range=None):
    values = _number_line_values(params)

    low, high = value_range or (min(values) - 2, max(values) + 2)
    line = NumberLine(x_range=[low, high, 1], include_numbers=True)
    fit_width(line)
    line.shift_onto_screen(buff=FRAME_MARGIN)
    scene.play(Create(line))

    marker = Dot(line.number_to_point(params.start), color=RED)
    label = build_number_line_label(marker, params.start)
    scene.play(FadeIn(marker), Write(label))

    scene.number_line = line
    scene.marker = marker
    scene.label = label
    scene.running_value = params.start
    scene.current_problem_arrows = []
    _animate_number_line_steps(scene, params)

    scene.wait(1)


def continue_number_line(scene, params):
    scene.play(*[
        arrow.animate.set_color(GRAY)
        for arrow in scene.current_problem_arrows
    ])
    scene.current_problem_arrows = []
    _animate_number_line_steps(scene, params)
    scene.wait(1)


class NumberLineScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("NumberLineScene.params must be set before construct() runs")
        draw_number_line(self, self.params)


from app.templates._shared.chained_scene import ChainedScene


class ChainedNumberLineScene(ChainedScene):
    draw_fn = staticmethod(draw_number_line)
    continues_from = staticmethod(number_line_continues_from)
    continue_fn = staticmethod(continue_number_line)
    chain_range_fn = staticmethod(number_line_chain_range)
