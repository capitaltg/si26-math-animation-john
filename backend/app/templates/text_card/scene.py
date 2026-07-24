from manim import *

from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_to_box, fit_width

BODY_GAP = 0.6


def build_text_card_mobjects(params):
    headline = Text(params.headline, weight=BOLD).scale(0.7)
    fit_width(headline)
    headline.to_edge(UP)

    lines = VGroup(*[Text(line).scale(0.5) for line in params.lines])
    lines.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    safe_bottom = -config.frame_height / 2 + FRAME_MARGIN
    available_height = headline.get_bottom()[1] - BODY_GAP - safe_bottom
    fit_to_box(
        lines,
        max_width=config.frame_width - 2 * FRAME_MARGIN,
        max_height=available_height,
    )
    lines.next_to(headline, DOWN, buff=BODY_GAP)
    if lines.get_bottom()[1] < safe_bottom:
        lines.shift(UP * (safe_bottom - lines.get_bottom()[1]))

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
