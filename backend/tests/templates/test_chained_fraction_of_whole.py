import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates.fraction_of_whole.params import (
    ChainedFractionOfWholeParams,
    FractionOfWholeParams,
)
from app.templates.fraction_of_whole.scene import ChainedFractionOfWholeScene


def _items():
    return [
        FractionOfWholeParams(numerator=1, denominator=2),
        FractionOfWholeParams(numerator=3, denominator=4),
    ]


def test_rejects_fewer_than_two_items():
    with pytest.raises(ValidationError):
        ChainedFractionOfWholeParams(items=_items()[:1])


def test_rejects_more_than_four_items():
    with pytest.raises(ValidationError):
        ChainedFractionOfWholeParams(items=_items() * 3)


def test_surfaces_per_item_guard_failure_through_list_validation():
    with pytest.raises(ValidationError):
        ChainedFractionOfWholeParams.model_validate({
            "items": [{"numerator": 1, "denominator": 2}, {"numerator": 5, "denominator": 3}]
        })


def test_chained_scene_renders_to_mp4(tmp_path):
    params = ChainedFractionOfWholeParams(items=_items())
    media_dir = tmp_path / "media"
    with tempconfig({
        "media_dir": str(media_dir),
        "output_file": "chained",
        "quality": "low_quality",
        "disable_caching": True,
    }):
        scene = ChainedFractionOfWholeScene()
        scene.params = params
        scene.render()

    assert any(media_dir.rglob("chained.mp4"))
