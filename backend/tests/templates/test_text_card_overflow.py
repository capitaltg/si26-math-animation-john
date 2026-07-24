import pytest
from manim import Text, config

from app.templates._shared.fit_to_frame import FRAME_MARGIN, fit_to_box
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

    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    assert headline.get_left()[0] >= safe_left
    assert headline.get_right()[0] <= safe_right
    assert lines.get_left()[0] >= safe_left
    assert lines.get_right()[0] <= safe_right


def test_many_short_lines_fit_within_vertical_frame():
    params = TextCardParams(
        headline="Practice",
        lines=[f"Problem {index}" for index in range(20)],
    )

    _, lines = build_text_card_mobjects(params)

    assert lines.get_top()[1] <= config.frame_height / 2 - FRAME_MARGIN
    assert lines.get_bottom()[1] >= -config.frame_height / 2 + FRAME_MARGIN


def test_multiline_headline_and_body_fit_within_safe_frame():
    params = TextCardParams(
        headline="\n".join(f"Headline {index}" for index in range(20)),
        lines=["Supporting body"],
    )

    headline, lines = build_text_card_mobjects(params)

    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    safe_bottom = -config.frame_height / 2 + FRAME_MARGIN
    safe_top = config.frame_height / 2 - FRAME_MARGIN
    for mobject in (headline, lines):
        assert mobject.width > 0
        assert mobject.height > 0
        assert mobject.get_left()[0] >= safe_left
        assert mobject.get_right()[0] <= safe_right
        assert mobject.get_bottom()[1] >= safe_bottom
        assert mobject.get_top()[1] <= safe_top


@pytest.mark.parametrize("dimension", ["max_width", "max_height"])
@pytest.mark.parametrize("value", [0, -1])
def test_fit_to_box_rejects_nonpositive_max_dimensions(dimension, value):
    with pytest.raises(ValueError, match=f"{dimension} must be positive"):
        fit_to_box(Text("content"), **{dimension: value})
