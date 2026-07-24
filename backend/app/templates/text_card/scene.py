from manim import *

from app.templates._shared.fit_to_frame import fit_width


def build_text_card_mobjects(params):
    headline = Text(params.headline, weight=BOLD).scale(0.7)
    fit_width(headline)
    headline.to_edge(UP)

    lines = VGroup(*[Text(line).scale(0.5) for line in params.lines])
    lines.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    fit_width(lines)
    lines.next_to(headline, DOWN, buff=0.6)

    return headline, lines


class TextCardScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("TextCardScene.params must be set before construct() runs")

        headline, lines = build_text_card_mobjects(self.params)

        self.play(Write(headline))
        self.play(LaggedStart(*[FadeIn(line) for line in lines], lag_ratio=0.2))
        self.wait(1)
