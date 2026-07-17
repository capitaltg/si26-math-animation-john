from manim import *


class ArrayGridScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("ArrayGridScene.params must be set before construct() runs")

        dots = VGroup()
        for r in range(self.params.rows):
            for c in range(self.params.cols):
                dot = Dot(radius=0.15, color=BLUE)
                dot.move_to([c * 0.6, -r * 0.6, 0])
                dots.add(dot)
        dots.move_to(ORIGIN)

        label = Text(f"{self.params.rows} x {self.params.cols}").to_edge(UP)

        self.play(Write(label))
        self.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))
        self.wait(1)
