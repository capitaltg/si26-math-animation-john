from manim import Text, config

from app.templates._shared.fit_to_frame import FRAME_MARGIN
from app.templates.fraction_of_whole.params import FractionOfWholeParams
from app.templates.fraction_of_whole.scene import draw_fraction_of_whole


class _StubScene:
    def __init__(self):
        self.labels = []

    def play(self, *animations):
        for animation in animations:
            target = getattr(animation, "target_mobject", None)
            mobject = target or getattr(animation, "mobject", None)
            if isinstance(mobject, Text):
                self.labels.append(mobject)

    def wait(self, _duration):
        pass


def test_label_fits_within_frame_at_max_denominator():
    params = FractionOfWholeParams(numerator=11, denominator=12)
    scene = _StubScene()

    draw_fraction_of_whole(scene, params)

    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    assert len(scene.labels) == 1
    assert scene.labels[0].get_left()[0] >= safe_left
    assert scene.labels[0].get_right()[0] <= safe_right
