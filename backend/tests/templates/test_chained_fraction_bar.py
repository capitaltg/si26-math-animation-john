import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates.fraction_bar.params import (
    ChainedFractionBarParams,
    FractionBarParams,
    FractionStep,
)
from app.templates.fraction_bar.scene import ChainedFractionBarScene


def _items():
    return [
        FractionBarParams(
            denominator=4,
            start_numerator=0,
            steps=[
                FractionStep(operation="add", numerator=1),
                FractionStep(operation="add", numerator=1),
            ],
        ),
        FractionBarParams(
            denominator=3,
            start_numerator=1,
            steps=[
                FractionStep(operation="add", numerator=1),
                FractionStep(operation="subtract", numerator=1),
            ],
        ),
    ]


def test_rejects_fewer_than_two_items():
    with pytest.raises(ValidationError):
        ChainedFractionBarParams(items=_items()[:1])


def test_rejects_more_than_four_items():
    with pytest.raises(ValidationError):
        ChainedFractionBarParams(items=_items() * 3)


def test_surfaces_per_item_guard_failure_through_list_validation():
    with pytest.raises(ValidationError):
        ChainedFractionBarParams.model_validate({
            "items": [
                {
                    "denominator": 2,
                    "start_numerator": 0,
                    "steps": [
                        {"operation": "add", "numerator": 1},
                        {"operation": "add", "numerator": 1},
                    ],
                },
                {
                    "denominator": 2,
                    "start_numerator": 0,
                    "steps": [
                        {"operation": "subtract", "numerator": 1},
                        {"operation": "add", "numerator": 1},
                    ],
                },
            ]
        })


def test_chained_scene_renders_to_mp4(tmp_path):
    params = ChainedFractionBarParams(items=_items())
    media_dir = tmp_path / "media"
    with tempconfig({
        "media_dir": str(media_dir),
        "output_file": "chained",
        "quality": "low_quality",
        "disable_caching": True,
    }):
        scene = ChainedFractionBarScene()
        scene.params = params
        scene.render()

    assert any(media_dir.rglob("chained.mp4"))
