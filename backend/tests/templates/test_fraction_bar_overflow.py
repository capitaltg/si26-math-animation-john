from manim import Text, config, tempconfig

from app.templates._shared.fit_to_frame import FRAME_MARGIN
from app.templates.fraction_bar.params import FractionBarParams, FractionStep
from app.templates.fraction_bar.scene import draw_fraction_bar


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


def test_running_total_labels_fit_within_frame_at_max_renderable_units():
    params = FractionBarParams(
        denominator=4,
        start_numerator=0,
        steps=[
            FractionStep(operation="add", numerator=16),
            FractionStep(operation="subtract", numerator=8),
        ],
    )
    scene = _StubScene()

    with tempconfig({"frame_width": 1.2}):
        draw_fraction_bar(scene, params)

        safe_left = -config.frame_width / 2 + FRAME_MARGIN
        safe_right = config.frame_width / 2 - FRAME_MARGIN
        assert len(scene.labels) > 0
        for label in scene.labels:
            assert label.get_left()[0] >= safe_left - 1e-9
            assert label.get_right()[0] <= safe_right + 1e-9
