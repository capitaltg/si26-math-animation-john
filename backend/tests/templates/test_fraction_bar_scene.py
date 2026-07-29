# backend/tests/templates/test_fraction_bar_scene.py
from manim import Text

from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.fraction_bar.params import FractionBarParams, FractionStep
from app.templates.fraction_bar.scene import draw_fraction_bar
from app.templates.registry import static_ref


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


def test_no_ghosted_captions_survive_a_three_step_chain():
    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="subtract", numerator=1),
            FractionStep(operation="add", numerator=1),
        ],
    )
    scene = _MobjectTrackingScene()

    draw_fraction_bar(scene, params)

    surviving_captions = [
        mobject
        for mobject in scene.mobjects
        if isinstance(mobject, Text) and "=" in mobject.original_text
    ]
    assert len(surviving_captions) == 1
    assert surviving_captions[0].original_text == "2/4 + 1/4 = 3/4"


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

    result_path = render_scene_to_mp4(static_ref(TemplateName.FRACTION_BAR), params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
