# backend/tests/templates/test_fraction_bar_scene.py
from manim import Text

from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
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


def test_operation_captions_render_each_step_in_order():
    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="subtract", numerator=1),
        ],
    )
    scene = _StubScene()

    draw_fraction_bar(scene, params)

    captions = [
        label.original_text for label in scene.labels if "=" in label.original_text
    ]
    assert captions == ["1/4 + 2/4 = 3/4", "3/4 - 1/4 = 2/4"]


def test_fraction_bar_renders_to_mp4(tmp_path):
    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="subtract", numerator=1),
        ],
    )
    output_path = tmp_path / "fraction_bar.mp4"

    result_path = render_scene_to_mp4(TemplateName.FRACTION_BAR, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
