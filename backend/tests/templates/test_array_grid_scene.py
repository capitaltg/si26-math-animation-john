from manim import Text

from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep
from app.templates.array_grid.scene import draw_array_grid


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


def test_single_fact_grid_still_shows_plain_dimension_label():
    params = ArrayGridParams(rows=2, cols=3)
    scene = _StubScene()

    draw_array_grid(scene, params)

    assert scene.labels[0].original_text == "2 x 3"


def test_multiplicative_chain_shows_running_total_and_operation_captions():
    params = ArrayGridParams(
        rows=1,
        cols=3,
        steps=[
            ArrayGridStep(operation="multiply", factor=4),
            ArrayGridStep(operation="divide", factor=2),
        ],
    )
    scene = _StubScene()

    draw_array_grid(scene, params)

    assert [label.original_text for label in scene.labels] == [
        "1 × 3 = 3",
        "4 × 3 = 12",
        "3 × 4 = 12",
        "2 × 3 = 6",
        "12 ÷ 2 = 6",
    ]


def test_array_grid_chain_renders_to_mp4(tmp_path):
    params = ArrayGridParams(
        rows=1,
        cols=3,
        steps=[
            ArrayGridStep(operation="multiply", factor=4),
            ArrayGridStep(operation="divide", factor=2),
        ],
    )
    output_path = tmp_path / "array_grid.mp4"

    result_path = render_scene_to_mp4(TemplateName.ARRAY_GRID, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
