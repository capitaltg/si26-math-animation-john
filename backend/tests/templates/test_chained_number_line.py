from types import SimpleNamespace

import pytest
from manim import tempconfig
from pydantic import ValidationError

from app.templates._shared import chained_scene as chained_scene_module
from app.templates.number_line import scene as number_line_scene_module
from app.templates.number_line.params import (
    ChainedNumberLineParams,
    NumberLineParams,
    NumberLineStep,
)
from app.templates.number_line.scene import (
    ChainedNumberLineScene,
    continue_number_line,
    number_line_chain_range,
    number_line_continues_from,
)


def _items():
    return [
        NumberLineParams(start=1, steps=[NumberLineStep(operation="add", amount=2)]),
        NumberLineParams(start=5, steps=[NumberLineStep(operation="subtract", amount=1)]),
    ]


def _continuous_items():
    return [
        NumberLineParams(start=3, steps=[NumberLineStep(operation="add", amount=4)]),
        NumberLineParams(start=7, steps=[NumberLineStep(operation="subtract", amount=5)]),
        NumberLineParams(start=2, steps=[NumberLineStep(operation="add", amount=6)]),
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


def test_number_line_continues_when_previous_result_matches_next_start():
    first, second, third = _continuous_items()

    assert number_line_continues_from(first, second) is True
    assert number_line_continues_from(second, third) is True


def test_number_line_does_not_continue_when_values_do_not_match():
    first, second = _items()

    assert number_line_continues_from(first, second) is False


def test_number_line_chain_range_includes_every_value_in_continuous_run():
    assert number_line_chain_range(_continuous_items()) == (0, 10)


def _record_chained_construct(monkeypatch, items):
    class FakeCaption:
        def __init__(self, text):
            self.text = text

        def to_edge(self, _direction):
            return self

    monkeypatch.setattr(chained_scene_module, "Text", FakeCaption)
    monkeypatch.setattr(chained_scene_module, "Write", lambda caption: ("write", caption.text))
    monkeypatch.setattr(
        chained_scene_module,
        "Transform",
        lambda caption, replacement: ("transform", caption.text, replacement.text),
        raising=False,
    )
    monkeypatch.setattr(
        chained_scene_module,
        "Group",
        lambda *mobjects: ("group", tuple(mobjects)),
    )
    monkeypatch.setattr(
        chained_scene_module,
        "FadeOut",
        lambda mobject: ("fade_out", mobject),
    )

    scene = ChainedNumberLineScene()
    scene.params = ChainedNumberLineParams(items=items)
    scene.mobjects = []
    events = []
    initial_draws = []
    continuations = []

    def draw_initial(_scene, item, value_range=None):
        initial_draws.append((item.start, value_range))
        scene.mobjects.append(f"line-{item.start}")

    def continue_item(_scene, item):
        continuations.append(item.start)

    scene.draw_fn = draw_initial
    scene.continues_from = number_line_continues_from
    scene.continue_fn = continue_item
    scene.chain_range_fn = number_line_chain_range
    scene.play = lambda *animations: events.extend(animations)
    scene.wait = lambda _duration: None

    scene.construct()
    full_scene_fades = [
        event
        for event in events
        if event[0] == "fade_out"
        and isinstance(event[1], tuple)
        and event[1][0] == "group"
    ]
    return initial_draws, continuations, events, full_scene_fades


def test_continuous_number_line_run_draws_once_without_full_scene_fade(monkeypatch):
    initial_draws, continuations, events, full_scene_fades = _record_chained_construct(
        monkeypatch, _continuous_items()
    )

    assert initial_draws == [(3, (0, 10))]
    assert continuations == [7, 2]
    assert [event[0] for event in events].count("transform") == 2
    assert full_scene_fades == []


def test_non_continuing_number_line_items_keep_full_redraw(monkeypatch):
    initial_draws, continuations, _events, full_scene_fades = _record_chained_construct(
        monkeypatch, _items()
    )

    assert initial_draws == [(1, None), (5, None)]
    assert continuations == []
    assert len(full_scene_fades) == 1


def test_mixed_number_line_chain_only_redraws_at_run_boundary(monkeypatch):
    items = [
        NumberLineParams(start=3, steps=[NumberLineStep(operation="add", amount=4)]),
        NumberLineParams(start=7, steps=[NumberLineStep(operation="subtract", amount=5)]),
        NumberLineParams(start=10, steps=[NumberLineStep(operation="add", amount=1)]),
    ]

    initial_draws, continuations, _events, full_scene_fades = _record_chained_construct(
        monkeypatch, items
    )

    assert initial_draws == [(3, (0, 9)), (10, None)]
    assert continuations == [7]
    assert len(full_scene_fades) == 1


def test_continuation_greys_completed_arrows_and_tracks_new_arrows(monkeypatch):
    class FakeArrow:
        def __init__(self):
            self.colors = []

        @property
        def animate(self):
            return self

        def set_color(self, color):
            self.colors.append(color)
            return ("set_color", color)

    class FakeLine:
        def number_to_point(self, value):
            return value

    class FakeText:
        width = 1

        def scale(self, _factor):
            return self

        def next_to(self, _mobject, _direction):
            return self

        def shift_onto_screen(self, *, buff):
            return self

    completed_arrow = FakeArrow()
    new_arrow = FakeArrow()
    marker = object()
    label = object()
    line = FakeLine()
    plays = []
    scene = SimpleNamespace(
        number_line=line,
        marker=marker,
        label=label,
        running_value=7,
        current_problem_arrows=[completed_arrow],
        play=lambda *animations: plays.append(animations),
        wait=lambda _duration: None,
    )
    params = NumberLineParams(
        start=7,
        steps=[NumberLineStep(operation="subtract", amount=5)],
    )

    monkeypatch.setattr(number_line_scene_module, "Arrow", lambda *args, **kwargs: new_arrow)
    monkeypatch.setattr(number_line_scene_module, "Dot", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        number_line_scene_module,
        "Text",
        lambda *_args, **_kwargs: FakeText(),
    )
    monkeypatch.setattr(
        number_line_scene_module,
        "Create",
        lambda mobject: ("create", mobject),
    )
    monkeypatch.setattr(
        number_line_scene_module,
        "Transform",
        lambda source, target: ("transform", source, target),
    )

    continue_number_line(scene, params)

    assert completed_arrow.colors == [number_line_scene_module.GRAY]
    assert scene.current_problem_arrows == [new_arrow]
    assert scene.number_line is line
    assert scene.marker is marker
    assert scene.label is label


def test_chained_scene_renders_to_mp4(tmp_path):
    params = ChainedNumberLineParams(items=_continuous_items())
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
