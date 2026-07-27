from manim import config

from app.templates._shared.fit_to_frame import FRAME_MARGIN
from app.templates.balance_scale.params import BalanceScaleParams
from app.templates.balance_scale.scene import draw_balance_scale


class _StubScene:
    def __init__(self):
        self.mobjects = []

    def play(self, *animations):
        for animation in animations:
            target = getattr(animation, "target_mobject", None)
            mobject = target or getattr(animation, "mobject", None)
            if mobject is not None:
                self.mobjects.append(mobject)

    def wait(self, _duration):
        pass


def test_labels_fit_within_frame_at_max_allowed_total():
    params = BalanceScaleParams(left_terms=[19, 1], right_total=20)
    scene = _StubScene()

    draw_balance_scale(scene, params)

    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    for mobject in scene.mobjects:
        assert mobject.get_left()[0] >= safe_left
        assert mobject.get_right()[0] <= safe_right
