import pytest

from app.meta.dynamic_scene import DynamicTemplateScene

def test_scene_requires_scene_program_and_values():
    scene = DynamicTemplateScene()
    with pytest.raises(ValueError):
        scene.construct()
