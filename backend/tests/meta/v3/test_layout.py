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


def _rectangle_and_labels(*texts):
    measurer = _WidthPerCharacterMeasurer()
    return [
        measure_rectangle(
            ref="rect", length=Fraction(8), width=Fraction(3), unit="cm", measurer=measurer,
        ),
        *(_label(f"support{index}", text, measurer) for index, text in enumerate(texts)),
        _answer("22", measurer),
    ]


# At 0.2 units per character against a rectangle whose measured box (shape plus
# dimension labels) is 6.58 wide, the side budget is 6.6 - 3.29 - 0.45 = 2.86
# units: 14 characters. `_WIDE` is far past that and well inside the 13.2 units a
# stacked row offers; `_NARROW` fits beside.
_WIDE = "Perimeter = 2 x (length + width)"
_NARROW = "P = 2(l+w)"


def test_a_label_too_wide_to_sit_beside_the_primary_is_stacked_instead():
    """A supporting label wider than the side budget must not shrink the lesson.

    `_place_supporting_side` put every supporting visual entirely to one side of
    the primary, so a label had to fit in half the frame minus the primary's
    half-width -- about 3.4 units. A longer one dragged the whole lesson's
    uniform scale down and, past roughly 4.3 units, below MIN_TEXT_SCALE, so a
    perfectly reasonable label made the candidate unrenderable. Stacked, the same
    label has the full 13.2-unit frame width.
    """
    placed = place_vertical_lesson(_rectangle_and_labels(_WIDE))

    by_ref = {item.measured.ref: item for item in placed}
    assert by_ref["rect"].scale >= 0.9, "a stacked wide label should not shrink the lesson"
    label_bounds = by_ref["support0"].bounds
    rect_bounds = by_ref["rect"].bounds
    # Stacked means vertically separated, not horizontally offset.
    assert not (
        max(label_bounds.bottom, rect_bounds.bottom) < min(label_bounds.top, rect_bounds.top)
    ), "a stacked label must not share the primary visual's vertical band"
    assert label_bounds.left >= SAFE_FRAME.left
    assert label_bounds.right <= SAFE_FRAME.right


def test_a_label_narrow_enough_still_sits_beside_the_primary():
    """Regression guard: stacking must not swallow the side placement."""
    placed = place_vertical_lesson(_rectangle_and_labels(_NARROW))

    by_ref = {item.measured.ref: item for item in placed}
    label_bounds = by_ref["support0"].bounds
    rect_bounds = by_ref["rect"].bounds
    assert max(label_bounds.bottom, rect_bounds.bottom) < min(label_bounds.top, rect_bounds.top), (
        "a narrow label should still share the primary visual's vertical band"
    )
    assert label_bounds.right <= rect_bounds.left or label_bounds.left >= rect_bounds.right


def test_stacked_and_beside_labels_never_overlap_anything():
    placed = place_vertical_lesson(_rectangle_and_labels(_WIDE, _NARROW, _WIDE))

    bounds = {item.measured.ref: item.bounds for item in placed}
    for ref, first in bounds.items():
        for other_ref, second in bounds.items():
            if ref < other_ref:
                assert not _overlaps(first, second), f"{ref} overlaps {other_ref}"
    for ref, box in bounds.items():
        assert box.left >= SAFE_FRAME.left - 1e-9, f"{ref} escapes left"
        assert box.right <= SAFE_FRAME.right + 1e-9, f"{ref} escapes right"
        assert box.top <= SAFE_FRAME.top + 1e-9, f"{ref} escapes top"
        assert box.bottom >= SAFE_FRAME.bottom - 1e-9, f"{ref} escapes bottom"


def test_every_placed_visual_stays_inside_the_safe_frame(asymmetric_lesson):
    placed = place_vertical_lesson(asymmetric_lesson)

    for item in placed:
        bounds = item.bounds
        assert bounds.left >= SAFE_FRAME.left - 1e-9, f"{item.measured.ref} escapes left"
        assert bounds.right <= SAFE_FRAME.right + 1e-9, f"{item.measured.ref} escapes right"
        assert bounds.bottom >= SAFE_FRAME.bottom - 1e-9, f"{item.measured.ref} escapes bottom"
        assert bounds.top <= SAFE_FRAME.top + 1e-9, f"{item.measured.ref} escapes top"
