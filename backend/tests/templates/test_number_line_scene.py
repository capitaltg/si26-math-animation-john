from manim import config

from app.templates.number_line.params import NumberLineParams, NumberLineStep
from app.templates.number_line.scene import draw_number_line


class _StubScene:
    def play(self, *animations):
        pass

    def wait(self, _duration):
        pass


def test_number_line_width_fits_within_frame_at_max_allowed_span():
    params = NumberLineParams(
        start=0,
        steps=[
            NumberLineStep(operation="add", amount=20),
            NumberLineStep(operation="subtract", amount=1),
        ],
    )
    scene = _StubScene()

    draw_number_line(scene, params)

    assert scene.number_line.width <= config.frame_width
