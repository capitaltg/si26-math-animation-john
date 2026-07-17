from manim import *


class NumberLineScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("NumberLineScene.params must be set before construct() runs")

        total = self.params.start
        values = [total]
        for step in self.params.steps:
            total = total + step.amount if step.operation == "add" else total - step.amount
            values.append(total)

        low, high = min(values) - 2, max(values) + 2
        line = NumberLine(x_range=[low, high, 1], include_numbers=True)
        self.play(Create(line))

        marker = Dot(line.number_to_point(self.params.start), color=RED)
        label = Text(str(self.params.start)).next_to(marker, UP)
        self.play(FadeIn(marker), Write(label))

        running = self.params.start
        for step in self.params.steps:
            new_value = running + step.amount if step.operation == "add" else running - step.amount
            arrow = Arrow(
                line.number_to_point(running),
                line.number_to_point(new_value),
                buff=0,
                color=GREEN if step.operation == "add" else ORANGE,
            )
            self.play(Create(arrow))
            new_marker = Dot(line.number_to_point(new_value), color=RED)
            new_label = Text(str(new_value)).next_to(new_marker, UP)
            self.play(Transform(marker, new_marker), Transform(label, new_label))
            running = new_value

        self.wait(1)
