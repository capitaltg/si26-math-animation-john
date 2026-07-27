from manim import Text, VGroup

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
        "3 × 4 = 12",
        "3 × 4 = 12",
        "2 × 3 = 6",
        "12 ÷ 2 = 6",
    ]


def test_generic_chain_derives_a_new_layout_for_every_total():
    params = ArrayGridParams(
        start=24,
        steps=[
            ArrayGridStep(operation="divide", factor=3),
            ArrayGridStep(operation="multiply", factor=2),
        ],
    )
    scene = _StubScene()

    draw_array_grid(scene, params)

    assert [label.original_text for label in scene.labels] == [
        "4 × 6 = 24",
        "2 × 4 = 8",
        "24 ÷ 3 = 8",
        "4 × 4 = 16",
        "8 × 2 = 16",
    ]


class _MobjectTrackingScene:
    def __init__(self):
        self.mobjects = []

    def play(self, *animations):
        for animation in animations:
            mobject = getattr(animation, "mobject", None)
            target = getattr(animation, "target_mobject", None)
            is_replacement = getattr(animation, "replace_mobject_with_target_in_scene", False)
            if mobject is not None and mobject not in self.mobjects:
                self.mobjects.append(mobject)
            if is_replacement and mobject is not None and target is not None:
                self.mobjects.remove(mobject)
                self.mobjects.append(target)
            elif target is not None and mobject is None and target not in self.mobjects:
                # introducer animations (Write/FadeIn/Create) expose their content via .mobject; this branch is a safety net only
                self.mobjects.append(target)

    def wait(self, _duration):
        pass


def test_no_ghosted_mobjects_survive_a_three_step_chain():
    params = ArrayGridParams(
        rows=1,
        cols=3,
        steps=[
            ArrayGridStep(operation="multiply", factor=4),
            ArrayGridStep(operation="divide", factor=2),
            ArrayGridStep(operation="multiply", factor=5),
        ],
    )
    scene = _MobjectTrackingScene()

    draw_array_grid(scene, params)

    surviving_grids = [mobject for mobject in scene.mobjects if isinstance(mobject, VGroup)]
    surviving_texts = [mobject for mobject in scene.mobjects if isinstance(mobject, Text)]

    assert len(surviving_grids) == 1
    assert len(surviving_texts) == 2
    assert {text.original_text for text in surviving_texts} == {
        "6 × 5 = 30",  # the final operation caption
        "5 × 6 = 30",  # the final running-total label
    }


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
