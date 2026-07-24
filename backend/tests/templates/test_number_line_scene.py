from manim import Text, config

from app.templates._shared.fit_to_frame import FRAME_MARGIN
from app.templates.number_line.params import NumberLineParams, NumberLineStep
from app.templates.number_line.scene import draw_number_line


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

    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    assert scene.number_line.get_left()[0] >= safe_left
    assert scene.number_line.get_right()[0] <= safe_right


def test_large_value_labels_fit_inside_horizontal_frame():
    params = NumberLineParams(
        start=10**12,
        steps=[NumberLineStep(operation="add", amount=20)],
    )
    scene = _StubScene()

    draw_number_line(scene, params)

    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    assert len(scene.labels) == 2
    assert all(label.get_left()[0] >= safe_left for label in scene.labels)
    assert all(label.get_right()[0] <= safe_right for label in scene.labels)
