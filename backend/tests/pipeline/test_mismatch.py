from fractions import Fraction

from app.models.scene import Scene
from app.pipeline.mismatch import (
    _format_answer,
    compute_answer_for,
    scene_mismatch,
)
from app.templates.registry import static_ref


def _number_line_scene(
    *,
    stated: Fraction | None = None,
    source: str | None = None,
    params: dict | None = None,
) -> Scene:
    return Scene(
        scene_id="s1",
        candidate_id="c1",
        template=static_ref("number_line"),
        grade_level=2,
        params=params if params is not None else {
            "start": 3,
            "steps": [{"operation": "add", "amount": 5}],
        },
        stated_answer=stated,
        stated_answer_source=source,
    )


def test_format_answer_integer_valued():
    assert _format_answer(Fraction(9)) == "9"
    assert _format_answer(Fraction(-3)) == "-3"


def test_format_answer_proper_fraction():
    assert _format_answer(Fraction(1, 2)) == "1/2"
    assert _format_answer(Fraction(2, 4)) == "1/2"  # reduced


def test_compute_answer_for_number_line():
    scene = _number_line_scene()
    assert compute_answer_for(scene) == Fraction(8)


def test_mismatch_when_stated_wrong():
    scene = _number_line_scene(stated=Fraction(9), source="= 9")
    result = scene_mismatch(scene)
    assert result == {"stated": "9", "computed": "8"}


def test_no_mismatch_when_stated_correct():
    scene = _number_line_scene(stated=Fraction(8), source="= 8")
    assert scene_mismatch(scene) is None


def test_no_mismatch_when_no_stated_answer():
    scene = _number_line_scene()
    assert scene_mismatch(scene) is None


def test_no_mismatch_when_computed_is_none_text_card():
    scene = Scene(
        scene_id="s1",
        candidate_id="c1",
        template=static_ref("text_card"),
        grade_level=2,
        params={"headline": "Hi", "lines": ["Hello"]},
        stated_answer=Fraction(9),
        stated_answer_source="= 9",
    )
    assert scene_mismatch(scene) is None
