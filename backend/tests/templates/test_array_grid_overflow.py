from manim import Dot, config, tempconfig

from app.templates._shared.fit_to_frame import FRAME_MARGIN
from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep
from app.templates.array_grid.scene import draw_array_grid


class _StubScene:
    def __init__(self):
        self.labels = []

    def play(self, *animations):
        for animation in animations:
            self._record(animation)

    def _record(self, animation):
        nested = getattr(animation, "animations", None)
        if nested:
            for child in nested:
                self._record(child)
            return
        target = getattr(animation, "target_mobject", None)
        mobject = target or getattr(animation, "mobject", None)
        if mobject is not None:
            self.labels.append(mobject)

    def wait(self, _duration):
        pass


def _assert_within_safe_frame(mobject):
    safe_left = -config.frame_width / 2 + FRAME_MARGIN
    safe_right = config.frame_width / 2 - FRAME_MARGIN
    safe_bottom = -config.frame_height / 2 + FRAME_MARGIN
    safe_top = config.frame_height / 2 - FRAME_MARGIN
    assert mobject.get_left()[0] >= safe_left
    assert mobject.get_right()[0] <= safe_right
    assert mobject.get_bottom()[1] >= safe_bottom
    assert mobject.get_top()[1] <= safe_top


def test_static_grid_at_max_dimensions_label_fits_within_frame():
    params = ArrayGridParams(rows=12, cols=12)
    scene = _StubScene()

    with tempconfig({"frame_width": 2.0}):
        draw_array_grid(scene, params)

        assert scene.labels[0].original_text == "12 x 12"
        _assert_within_safe_frame(scene.labels[0])


def test_static_grid_label_does_not_overlap_max_grid():
    scene = _StubScene()

    draw_array_grid(scene, ArrayGridParams(rows=12, cols=12))

    label = scene.labels[0]
    dots = [mobject for mobject in scene.labels if isinstance(mobject, Dot)]
    assert len(dots) == 144
    assert label.get_bottom()[1] >= max(dot.get_top()[1] for dot in dots)


def test_chain_at_max_total_labels_fit_within_frame():
    params = ArrayGridParams(
        start=144,
        steps=[
            ArrayGridStep(operation="divide", factor=12),
            ArrayGridStep(operation="multiply", factor=12),
        ],
    )
    scene = _StubScene()

    draw_array_grid(scene, params)

    for label in scene.labels:
        _assert_within_safe_frame(label)
