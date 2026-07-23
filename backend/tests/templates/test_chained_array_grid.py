import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates.array_grid.params import ArrayGridParams, ChainedArrayGridParams
from app.templates.array_grid.scene import ChainedArrayGridScene


def _items():
    return [ArrayGridParams(rows=2, cols=3), ArrayGridParams(rows=3, cols=3)]


def test_rejects_fewer_than_two_items():
    with pytest.raises(ValidationError):
        ChainedArrayGridParams(items=_items()[:1])


def test_rejects_more_than_four_items():
    with pytest.raises(ValidationError):
        ChainedArrayGridParams(items=_items() * 3)


def test_surfaces_per_item_guard_failure_through_list_validation():
    with pytest.raises(ValidationError):
        ChainedArrayGridParams.model_validate({
            "items": [{"rows": 2, "cols": 3}, {"rows": 13, "cols": 3}]
        })


def test_chained_scene_renders_to_mp4(tmp_path):
    params = ChainedArrayGridParams(items=_items())
    media_dir = tmp_path / "media"
    with tempconfig({
        "media_dir": str(media_dir),
        "output_file": "chained",
        "quality": "low_quality",
        "disable_caching": True,
    }):
        scene = ChainedArrayGridScene()
        scene.params = params
        scene.render()

    assert any(media_dir.rglob("chained.mp4"))
