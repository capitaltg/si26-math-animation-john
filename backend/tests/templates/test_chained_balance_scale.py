import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates.balance_scale.params import BalanceScaleParams, ChainedBalanceScaleParams
from app.templates.balance_scale.scene import ChainedBalanceScaleScene


def _items():
    return [
        BalanceScaleParams(left_terms=[2, 3], right_total=5),
        BalanceScaleParams(left_terms=[4, 1], right_total=5),
    ]


def test_rejects_fewer_than_two_items():
    with pytest.raises(ValidationError):
        ChainedBalanceScaleParams(items=_items()[:1])


def test_rejects_more_than_four_items():
    with pytest.raises(ValidationError):
        ChainedBalanceScaleParams(items=_items() * 3)


def test_surfaces_per_item_guard_failure_through_list_validation():
    with pytest.raises(ValidationError):
        ChainedBalanceScaleParams.model_validate({
            "items": [
                {"left_terms": [2, 3], "right_total": 5},
                {"left_terms": [2, 3], "right_total": 10},
            ]
        })


def test_chained_scene_renders_to_mp4(tmp_path):
    params = ChainedBalanceScaleParams(items=_items())
    media_dir = tmp_path / "media"
    with tempconfig({
        "media_dir": str(media_dir),
        "output_file": "chained",
        "quality": "low_quality",
        "disable_caching": True,
    }):
        scene = ChainedBalanceScaleScene()
        scene.params = params
        scene.render()

    assert any(media_dir.rglob("chained.mp4"))
