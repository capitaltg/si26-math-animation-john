from manim import Text

from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.balance_scale.params import BalanceScaleParams
from app.templates.balance_scale.scene import draw_balance_scale


class _StubScene:
    def __init__(self):
        self.labels = []

    def play(self, *animations):
        for animation in animations:
            mobject = getattr(animation, "mobject", None)
            if isinstance(mobject, Text):
                self.labels.append(mobject)

    def wait(self, _duration):
        pass


def test_balance_scale_does_not_repeat_pan_values_as_bottom_equation():
    scene = _StubScene()

    draw_balance_scale(
        scene,
        BalanceScaleParams(left_terms=[10, 10], right_total=20),
    )

    assert [label.original_text for label in scene.labels] == ["10 + 10", "20"]


def test_balance_scale_renders_to_mp4(tmp_path):
    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)
    output_path = tmp_path / "balance_scale.mp4"

    result_path = render_scene_to_mp4(TemplateName.BALANCE_SCALE, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
