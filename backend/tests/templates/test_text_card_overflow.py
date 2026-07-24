from manim import config

from app.templates.text_card.params import TextCardParams
from app.templates.text_card.scene import build_text_card_mobjects


def test_long_headline_and_lines_fit_within_frame():
    params = TextCardParams(
        headline="This headline is deliberately long enough that it used to run off the edges of the screen",
        lines=[
            "This supporting line is also long enough on its own to overflow the frame width previously",
        ],
    )

    headline, lines = build_text_card_mobjects(params)

    assert headline.width <= config.frame_width
    assert lines.width <= config.frame_width
