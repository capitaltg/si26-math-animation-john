from manim import Text

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

    draw_balance_scale(scene, params)

    labels = [mobject for mobject in scene.mobjects if isinstance(mobject, Text)]
    assert [label.original_text for label in labels] == ["10 + 10", "20"]
    assert all(label.width <= 1.0 for label in labels)
