import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates._shared import chained_scene as chained_scene_module
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


def test_chained_array_grid_omits_problem_counter(monkeypatch):
    class FakeCaption:
        def __init__(self, text):
            self.text = text

        def to_edge(self, _direction):
            return self

    monkeypatch.setattr(chained_scene_module, "Text", FakeCaption)
    monkeypatch.setattr(
        chained_scene_module,
        "Write",
        lambda caption: ("write", caption.text),
    )
    monkeypatch.setattr(
        chained_scene_module,
        "FadeOut",
        lambda mobject: ("fade_out", mobject),
    )
    monkeypatch.setattr(
        chained_scene_module,
        "Group",
        lambda *mobjects: ("group", tuple(mobjects)),
    )

    scene = ChainedArrayGridScene()
    scene.params = ChainedArrayGridParams(items=_items())
    scene.mobjects = []
    events = []
    scene.draw_fn = lambda _scene, _item: None
    scene.play = lambda *animations: events.extend(animations)
    scene.wait = lambda _duration: None

    scene.construct()

    assert not any(
        event[0] == "write" and event[1].startswith("Problem ")
        for event in events
    )


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
