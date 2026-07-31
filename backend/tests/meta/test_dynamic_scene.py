import pytest

from app.meta.dynamic_scene import DynamicTemplateScene

# The nine v1 tests that used to live here exercised `render_animation_node`,
# which lost its last production caller when this branch rewrote
# `DynamicTemplateScene.construct()` to resolve and render a v3
# `SceneProgramDocument`. Both the function and those tests are gone; the v3
# render path is covered by `tests/meta/v3/test_renderer.py` (semantic actions),
# `tests/render/test_dynamic_render_worker.py` (real subprocess renders) and
# `tests/meta/test_demo_end_to_end.py` (a real MP4).


def test_scene_requires_scene_program_and_values():
    scene = DynamicTemplateScene()
    with pytest.raises(ValueError):
        scene.construct()
