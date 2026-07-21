from manim import *


class TextCardScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("TextCardScene.params must be set before construct() runs")

        headline = Text(self.params.headline, weight=BOLD).scale(0.7).to_edge(UP)
        lines = VGroup(*[Text(line).scale(0.5) for line in self.params.lines])
        lines.arrange(DOWN, aligned_edge=LEFT, buff=0.3).next_to(headline, DOWN, buff=0.6)

        self.play(Write(headline))
        self.play(LaggedStart(*[FadeIn(line) for line in lines], lag_ratio=0.2))
        self.wait(1)
