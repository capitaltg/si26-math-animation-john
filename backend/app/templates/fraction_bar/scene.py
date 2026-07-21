from manim import *


class FractionBarScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("FractionBarScene.params must be set before construct() runs")

        denominator = self.params.denominator
        total = self.params.start_numerator
        values = [total]
        for step in self.params.steps:
            total = total + step.numerator if step.operation == "add" else total - step.numerator
            values.append(total)

        n_cells = max(max(values), denominator)
        cell_width = min(0.6, 12.0 / n_cells)

        cells = VGroup()
        for _ in range(n_cells):
            cells.add(Rectangle(width=cell_width, height=0.8, stroke_color=WHITE))
        cells.arrange(RIGHT, buff=0).move_to(ORIGIN)
        self.play(Create(cells))

        label = Text(f"{values[0]}/{denominator}").scale(0.6).next_to(cells, UP)
        self.play(Write(label))

        current = values[0]
        self.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current)])

        for value in values[1:]:
            new_label = Text(f"{value}/{denominator}").scale(0.6).next_to(cells, UP)
            if value > current:
                self.play(
                    *[cells[i].animate.set_fill(GREEN, opacity=0.8) for i in range(current, value)],
                    Transform(label, new_label),
                )
                self.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current, value)])
            elif value < current:
                self.play(
                    *[cells[i].animate.set_fill(BLUE, opacity=0.0) for i in range(value, current)],
                    Transform(label, new_label),
                )
            current = value

        self.wait(1)
