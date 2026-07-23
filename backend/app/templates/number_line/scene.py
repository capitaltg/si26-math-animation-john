from manim import *


def draw_number_line(scene, params):
    total = params.start
    values = [total]
    for step in params.steps:
        total = total + step.amount if step.operation == "add" else total - step.amount
        values.append(total)

    low, high = min(values) - 2, max(values) + 2
    line = NumberLine(x_range=[low, high, 1], include_numbers=True)
    scene.play(Create(line))

    marker = Dot(line.number_to_point(params.start), color=RED)
    label = Text(str(params.start)).next_to(marker, UP)
    scene.play(FadeIn(marker), Write(label))

    running = params.start
    for step in params.steps:
        new_value = running + step.amount if step.operation == "add" else running - step.amount
        arrow = Arrow(
            line.number_to_point(running),
            line.number_to_point(new_value),
            buff=0,
            color=GREEN if step.operation == "add" else ORANGE,
        )
        scene.play(Create(arrow))
        new_marker = Dot(line.number_to_point(new_value), color=RED)
        new_label = Text(str(new_value)).next_to(new_marker, UP)
        scene.play(Transform(marker, new_marker), Transform(label, new_label))
        running = new_value

    scene.wait(1)


class NumberLineScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("NumberLineScene.params must be set before construct() runs")
        draw_number_line(self, self.params)
