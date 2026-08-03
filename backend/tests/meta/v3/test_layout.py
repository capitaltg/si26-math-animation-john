from fractions import Fraction

import pytest

from app.meta.v3.geometry import Bounds
from app.meta.v3.layout import SAFE_FRAME, place_vertical_lesson
from app.meta.v3.rectangle_measurement import measure_rectangle
from app.meta.v3.visual_registry import default_visual_registry


class _WidthPerCharacterMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.2, 0.4


def _label(ref, text, measurer):
    spec = type("Spec", (), {"kind": "label", "ref": ref})()
    return default_visual_registry().measure(spec, {"text": text}, measurer)


def _answer(text, measurer):
    spec = type("Spec", (), {"kind": "label", "ref": "evaluated_answer"})()
    return default_visual_registry().measure(spec, {"text": text}, measurer)


def _overlaps(first: Bounds, second: Bounds) -> bool:
    return (
        max(first.left, second.left) < min(first.right, second.right)
        and max(first.bottom, second.bottom) < min(first.top, second.top)
    )


@pytest.fixture
def asymmetric_lesson():
    """A rectangle whose measured box is not centred on its own shape.

    `measure_rectangle` puts the width label outside the left edge and the length
    label below the bottom edge, so the measured bounds extend further left and
    down than right and up. Placement has to cope with a primary visual whose
    bounding box centre is not its geometric centre -- which every earlier
    primary visual happened to be.
    """
    measurer = _WidthPerCharacterMeasurer()
    rectangle = measure_rectangle(
        ref="rect", length=Fraction(8), width=Fraction(3), unit="cm", measurer=measurer,
    )
    assert rectangle.bounds.center.x != pytest.approx(0.0), (
        "this fixture is only meaningful for an off-centre measured box"
    )
    return [
        rectangle,
        _label("formula_label", "P = 2 x (length + width)", measurer),
        _label("answer_label", "Perimeter = 2 x (l + w)", measurer),
        _answer("22", measurer),
    ]


def test_side_labels_sit_clear_of_where_the_primary_visual_actually_lands(
    asymmetric_lesson,
):
    """Supporting labels must clear the primary's PLACED bounds.

    `_place_supporting_side` measured its cursor from the primary's untranslated
    measured bounds, ignoring the offset that centres it. While every primary
    visual was symmetric that offset was zero and the bug was invisible; with an
    off-centre box each side label lands wrong by exactly that offset -- pushed
    off the frame on one side and into the shape on the other.
    """
    placed = place_vertical_lesson(asymmetric_lesson)

    by_ref = {item.measured.ref: item.bounds for item in placed}
    for ref, bounds in by_ref.items():
        for other_ref, other_bounds in by_ref.items():
            if ref < other_ref:
                assert not _overlaps(bounds, other_bounds), f"{ref} overlaps {other_ref}"


def test_every_placed_visual_stays_inside_the_safe_frame(asymmetric_lesson):
    placed = place_vertical_lesson(asymmetric_lesson)

    for item in placed:
        bounds = item.bounds
        assert bounds.left >= SAFE_FRAME.left - 1e-9, f"{item.measured.ref} escapes left"
        assert bounds.right <= SAFE_FRAME.right + 1e-9, f"{item.measured.ref} escapes right"
        assert bounds.bottom >= SAFE_FRAME.bottom - 1e-9, f"{item.measured.ref} escapes bottom"
        assert bounds.top <= SAFE_FRAME.top + 1e-9, f"{item.measured.ref} escapes top"
