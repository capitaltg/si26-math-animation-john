from manim import MovingCameraScene

from app.meta.v3.manim_measurer import ManimTextMeasurer
from app.meta.v3.renderer import render_resolved_scene
from app.meta.v3.resolver import resolve_scene
from app.meta.v3.visual_registry import default_visual_registry


def resolve_dynamic_scene(scene_program, values: dict):
    """Resolve a v3 ``SceneProgramDocument`` against ``values`` using the same
    measurer and visual registry the runtime renderer uses.

    Shared by ``DynamicTemplateScene.construct()`` (the production render path)
    and tests that need to resolve the exact same scene program with different
    field values, so those tests exercise production resolution logic rather
    than a parallel reimplementation.
    """
    return resolve_scene(scene_program, values, ManimTextMeasurer(), default_visual_registry())


class DynamicTemplateScene(MovingCameraScene):
    scene_program = None
    field_values = None
    params = None

    def construct(self):
        if self.scene_program is None:
            raise ValueError(
                "DynamicTemplateScene.scene_program must be set before construct() runs"
            )
        if self.field_values is not None:
            values = self.field_values
        elif self.params is not None:
            values = self.params.model_dump()
        else:
            raise ValueError(
                "DynamicTemplateScene.field_values or .params must be set before construct() runs"
            )
        resolved = resolve_dynamic_scene(self.scene_program, values)
        render_resolved_scene(self, resolved)
