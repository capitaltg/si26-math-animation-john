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
    assert len(scene.labels) == 3
    assert all(label.get_left()[0] >= safe_left for label in scene.labels)
    assert all(label.get_right()[0] <= safe_right for label in scene.labels)


def test_operation_captions_render_each_step_in_order():
    params = NumberLineParams(
        start=4,
        steps=[
            NumberLineStep(operation="add", amount=3),
            NumberLineStep(operation="subtract", amount=2),
        ],
    )
    scene = _StubScene()

    draw_number_line(scene, params)

    captions = [
        label.original_text for label in scene.labels if "=" in label.original_text
    ]
    assert captions == ["4 + 3 = 7", "7 - 2 = 5"]


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
    params = NumberLineParams(
        start=4,
        steps=[
            NumberLineStep(operation="add", amount=3),
            NumberLineStep(operation="subtract", amount=2),
            NumberLineStep(operation="add", amount=5),
        ],
    )
    scene = _MobjectTrackingScene()

    draw_number_line(scene, params)

    surviving_captions = [
        mobject
        for mobject in scene.mobjects
        if isinstance(mobject, Text) and "=" in mobject.original_text
    ]
    assert len(surviving_captions) == 1
    assert surviving_captions[0].original_text == "5 + 5 = 10"
