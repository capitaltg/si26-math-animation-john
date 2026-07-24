from manim import *

from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_to_frame

BODY_GAP = 0.6


def build_text_card_mobjects(params):
    headline = Text(params.headline, weight=BOLD).scale(0.7)

    lines = VGroup(*[Text(line).scale(0.5) for line in params.lines])
    lines.arrange(DOWN, aligned_edge=LEFT, buff=0.3)

    card = VGroup(headline, lines)
    card.arrange(DOWN, buff=BODY_GAP)
    fit_to_frame(card)
    card.to_edge(UP, buff=FRAME_MARGIN)

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
