from manim import config

from app.templates._shared.fit_to_frame import FRAME_MARGIN
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


def test_many_short_lines_fit_within_vertical_frame():
    params = TextCardParams(
        headline="Practice",
        lines=[f"Problem {index}" for index in range(20)],
    )

    _, lines = build_text_card_mobjects(params)

    assert lines.get_top()[1] <= config.frame_height / 2 - FRAME_MARGIN
    assert lines.get_bottom()[1] >= -config.frame_height / 2 + FRAME_MARGIN
