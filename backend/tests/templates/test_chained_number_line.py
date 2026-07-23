import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates.number_line.params import (
    ChainedNumberLineParams,
    NumberLineParams,
    NumberLineStep,
)
from app.templates.number_line.scene import ChainedNumberLineScene


def _items():
    return [
        NumberLineParams(start=1, steps=[NumberLineStep(operation="add", amount=2)]),
        NumberLineParams(start=5, steps=[NumberLineStep(operation="subtract", amount=1)]),
    ]


def test_rejects_fewer_than_two_items():
    with pytest.raises(ValidationError):
        ChainedNumberLineParams(items=_items()[:1])


def test_rejects_more_than_four_items():
    with pytest.raises(ValidationError):
        ChainedNumberLineParams(items=_items() * 3)


def test_surfaces_per_item_guard_failure_through_list_validation():
    with pytest.raises(ValidationError):
        ChainedNumberLineParams.model_validate({
            "items": [
                {"start": 1, "steps": [{"operation": "add", "amount": 2}]},
                {"start": 1, "steps": [{"operation": "subtract", "amount": 5}]},
            ]
        })


def test_chained_scene_renders_to_mp4(tmp_path):
    params = ChainedNumberLineParams(items=_items())
    media_dir = tmp_path / "media"
    with tempconfig({
        "media_dir": str(media_dir),
        "output_file": "chained",
        "quality": "low_quality",
        "disable_caching": True,
    }):
        scene = ChainedNumberLineScene()
        scene.params = params
        scene.render()

    assert any(media_dir.rglob("chained.mp4"))
