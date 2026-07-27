from manim import Text, config, tempconfig

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
    params = BalanceScaleParams(left_terms=[10, 10], right_total=20)
    scene = _StubScene()

    with tempconfig({"frame_width": 3.0}):
        draw_balance_scale(scene, params)

        labels = [mobject for mobject in scene.mobjects if isinstance(mobject, Text)]
        pan_labels = [label for label in labels if "=" not in label.original_text]
        equation = next(label for label in labels if "=" in label.original_text)

        assert all(label.width <= 1.0 for label in pan_labels)
        assert equation.width <= config.frame_width - 2 * FRAME_MARGIN
