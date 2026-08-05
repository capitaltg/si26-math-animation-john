from fractions import Fraction
from types import SimpleNamespace

import pytest

from app.meta.v3.errors import V3ValidationError
from app.meta.v3.geometry import Bounds, MeasuredVisual, SemanticPart
from app.meta.v3.layout import CALLOUT_ENVELOPE, SAFE_FRAME, place_vertical_lesson
from app.meta.v3.rectangle_measurement import measure_rectangle
from app.meta.v3.visual_registry import default_visual_registry


class _WidthPerCharacterMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.2, 0.4


def _label(ref, text, measurer):
    spec = type("Spec", (), {"kind": "label", "ref": ref})()
    return default_visual_registry().measure(spec, {"text": text}, measurer)


def _answer(text, measurer):
    spec = type("Spec", (), {"kind": "answer_expression", "ref": "evaluated_answer"})()
    return default_visual_registry().measure(
        spec, {"stages": {"unknown": "?", "value": text}}, measurer,
    )


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


def test_the_answer_is_the_last_row_of_the_lesson_column():
    measurer = _WidthPerCharacterMeasurer()
    placed = place_vertical_lesson([
        _label("primary", "bar", measurer),
        _label("conversion", "1 km = 1000 m", measurer),
        _answer("2.75 x 1000 = 2750 meters", measurer),
    ])
    by_ref = {item.measured.ref: item for item in placed}

    answer = by_ref["evaluated_answer"]
    assert answer.bounds.top <= by_ref["primary"].bounds.bottom + 1e-9
    for item in placed:
        assert item.bounds.bottom >= SAFE_FRAME.bottom - 1e-9
        assert item.bounds.top <= SAFE_FRAME.top + 1e-9


def test_the_answer_is_not_confined_to_a_bottom_band():
    """The lesson column is centred as a unit, so a short lesson's answer sits
    near the middle rather than being pinned to the frame's bottom edge."""
    measurer = _WidthPerCharacterMeasurer()
    primary, answer = place_vertical_lesson([
        _label("primary", "bar", measurer),
        _answer("7", measurer),
    ])

    column_center = (primary.bounds.top + answer.bounds.bottom) / 2
    assert column_center == pytest.approx(0.0, abs=1e-9)
    assert answer.bounds.bottom > -2.4


def test_a_wide_answer_does_not_get_sorted_above_the_primary_visual():
    """`_balanced_pair` splits wide rows between above and below by extent, so
    without an explicit rule the answer could land over the lesson."""
    measurer = _WidthPerCharacterMeasurer()
    placed = place_vertical_lesson([
        _label("primary", "bar", measurer),
        _label("wide_support", "a" * 40, measurer),
        _answer("b" * 40, measurer),
    ])
    by_ref = {item.measured.ref: item for item in placed}

    assert by_ref["evaluated_answer"].bounds.top <= by_ref["primary"].bounds.bottom + 1e-9


def test_an_answer_only_scene_is_centred_rather_than_failing_to_place():
    measurer = _WidthPerCharacterMeasurer()
    answer, = place_vertical_lesson([_answer("2750 meters", measurer)])

    assert answer.bounds.center.y == pytest.approx(0.0)


def _tape_like_primary(ref="tape", height=0.6, width=4.0):
    """A primary whose parts sit flush with its outer bottom edge (unit_tape).

    Isolates the property that unit_tape.box[0].bottom coincides with the
    visual's bounds.bottom -- the geometry that leaves a bottom-anchored
    callout no interior room to render into.
    """
    bounds = Bounds(-width / 2, width / 2, -height / 2, height / 2)
    box = Bounds(-width / 2, -width / 2 + 1.0, -height / 2, height / 2)
    return MeasuredVisual(
        ref=ref, bounds=bounds,
        parts={("box", 0): SemanticPart("box", 0, box)},
        paths={}, payload={},
    )


def _interior_bottom_anchor_primary(ref="tape", height=2.0, width=4.0):
    """A primary whose `box[0]` occupies the upper half, so
    `box[0].bottom` sits at the primary's center Y -- not at
    `primary.bounds.bottom`. A stand-in for any visual anchored on an
    interior part (a two-row grid anchored on the upper row's bottom, for
    example) rather than on its outer edge.
    """
    bounds = Bounds(-width / 2, width / 2, -height / 2, height / 2)
    box = Bounds(-width / 2, -width / 2 + 1.0, 0.0, height / 2)
    return MeasuredVisual(
        ref=ref, bounds=bounds,
        parts={("box", 0): SemanticPart("box", 0, box)},
        paths={}, payload={},
    )


def _callout(visual_ref, part, index, anchor, text=""):
    return SimpleNamespace(
        target=SimpleNamespace(
            visual_ref=visual_ref, part=part, index=index, anchor=anchor,
        ),
        text=text,
    )


def test_bottom_anchored_callout_on_primary_reserves_room_below_it():
    """The reported #82 scenario: a callout anchored to `box[0].bottom` on a
    unit_tape-like primary must not overrun the answer stacked below it. The
    layout has to reserve enough clearance below the primary that the
    callout's fixed downward envelope fits."""
    measurer = _WidthPerCharacterMeasurer()
    measured = [_tape_like_primary(), _answer("2750 meters", measurer)]
    relations = [_callout("tape", part="box", index=0, anchor="bottom")]

    placed = place_vertical_lesson(measured, relations)
    by_ref = {item.measured.ref: item for item in placed}

    primary_bottom = by_ref["tape"].bounds.bottom
    answer_top = by_ref["evaluated_answer"].bounds.top
    clearance = primary_bottom - answer_top
    # Without the reservation the two are separated only by `GAP`; with the
    # reservation the callout's downward envelope also fits, so a callout tip
    # at the primary's own bottom edge lands well above the answer.
    assert clearance >= CALLOUT_ENVELOPE - 1e-9, (
        f"answer clearance {clearance:g} < callout envelope {CALLOUT_ENVELOPE:g}"
    )


def test_bottom_anchored_callout_on_a_part_with_room_below_it_reserves_nothing_extra():
    """If the anchor already sits far enough above the primary's outer bottom
    that the envelope fits inside the visual's own bounds, the layout must
    not push the answer further away for it -- otherwise every measurement
    lesson with a labelled edge would pay for space it doesn't need."""
    measurer = _WidthPerCharacterMeasurer()
    # A primary whose bottom bounds sit `CALLOUT_ENVELOPE` below its box.
    height = 0.6
    interior = CALLOUT_ENVELOPE + 0.1
    box = Bounds(-2.0, 2.0, -height / 2, height / 2)
    bounds = Bounds(-2.0, 2.0, box.bottom - interior, box.top)
    primary = MeasuredVisual(
        ref="rect", bounds=bounds,
        parts={("edge", 0): SemanticPart("edge", 0, box)},
        paths={}, payload={},
    )
    relations = [_callout("rect", part="edge", index=0, anchor="bottom")]

    with_relation = place_vertical_lesson(
        [primary, _answer("22", measurer)], relations,
    )
    without_relation = place_vertical_lesson([primary, _answer("22", measurer)])

    def _by_ref(placed):
        return {item.measured.ref: item.bounds for item in placed}
    assert _by_ref(with_relation) == _by_ref(without_relation)


def test_multiline_callout_descent_exceeds_the_fixed_envelope():
    """Renderer-backed rationale for the schema rejecting newlines: a
    two-line label plus its arrow and buff renders more than
    `CALLOUT_ENVELOPE` below the anchor, so the layout's fixed
    single-line reservation would let a multi-line callout overrun into
    the row below. Schema validation catches it earlier."""
    import numpy as np
    from manim import Arrow, Text, VGroup

    from app.meta.v3.manim_measurer import FONT_SIZES

    anchor = np.array([0.0, 0.0, 0.0])
    label = Text("first line\nsecond line", font_size=FONT_SIZES["label"])
    label.next_to(anchor, direction=np.array([0, -1, 0]))
    arrow = Arrow(label.get_top(), anchor, buff=0.08)
    rendered = VGroup(arrow, label)
    descent = float(anchor[1] - rendered.get_bottom()[1])
    assert descent > CALLOUT_ENVELOPE, (
        f"two-line callout descent {descent:g} does not exceed the "
        f"reserved envelope {CALLOUT_ENVELOPE:g}; the schema newline "
        f"reject would then be over-cautious"
    )


def test_rendered_callout_stays_clear_of_the_answer_at_the_layout_fitted_scale():
    """Renderer-backed regression: build the callout with Manim exactly the
    way `renderer._build_relation` does (`Text` at `FONT_SIZES["label"]`
    plus an `Arrow`), position it at the layout's placed anchor, and
    verify its rendered bottom sits above the answer's top. A fixed
    per-character estimate understates wide-glyph widths, so the check
    reads actual Manim bounds rather than trusting an estimator."""
    import numpy as np
    from manim import Arrow, Text, VGroup

    from app.meta.v3.manim_measurer import FONT_SIZES

    measurer = _WidthPerCharacterMeasurer()
    primary = _tape_like_primary(height=1.0, width=4.0)
    answer = _answer("2750 meters", measurer)
    callout_text = "1 km = 1000 m"
    relations = [_callout(
        "tape", part="box", index=0, anchor="bottom", text=callout_text,
    )]

    placed = place_vertical_lesson([primary, answer], relations)

    by_ref = {item.measured.ref: item for item in placed}
    anchor = by_ref["tape"].anchor(part="box", index=0, name="bottom")
    target = np.array([anchor.x, anchor.y, 0.0])
    label = Text(callout_text, font_size=FONT_SIZES["label"])
    label.next_to(target, direction=np.array([0, -1, 0]))
    arrow = Arrow(label.get_top(), target, buff=0.08)
    rendered = VGroup(arrow, label)

    rendered_bottom = float(rendered.get_bottom()[1])
    answer_top = by_ref["evaluated_answer"].bounds.top
    assert rendered_bottom >= answer_top - 1e-6, (
        f"rendered callout bottom {rendered_bottom:g} overruns "
        f"answer top {answer_top:g}"
    )
    assert rendered_bottom >= SAFE_FRAME.bottom - 1e-6, (
        f"rendered callout bottom {rendered_bottom:g} escapes safe frame"
    )


def test_bottom_callout_on_an_interior_anchor_forces_same_height_sides_to_stack():
    """The stack rule is per-anchor, not primary-height-vs-side-height. A
    2.0-high primary whose `box[0].bottom` sits at its own center Y drops
    the callout into (-0.9, 0) around center Y; a 2.0-high side beside it
    would span (-1.0, 1.0) around the same center Y and overlap. The side
    has to stack even though it is the same height as the primary."""
    import numpy as np
    from manim import Arrow, Text, VGroup

    from app.meta.v3.manim_measurer import FONT_SIZES

    primary = _interior_bottom_anchor_primary(height=2.0, width=4.0)
    same_height_side = MeasuredVisual(
        ref="side", bounds=Bounds(-1.0, 1.0, -1.0, 1.0),
        parts={}, paths={}, payload={},
    )
    answer = MeasuredVisual(
        ref="evaluated_answer", bounds=Bounds(-1.0, 1.0, -0.275, 0.275),
        parts={}, paths={}, payload={},
    )
    callout_text = "1 km = 1000 m"
    relations = [_callout(
        "tape", part="box", index=0, anchor="bottom", text=callout_text,
    )]

    placed = place_vertical_lesson(
        [primary, same_height_side, answer], relations,
    )

    by_ref = {item.measured.ref: item for item in placed}
    tape, side = by_ref["tape"], by_ref["side"]
    assert not _vertical_overlap(tape.bounds, side.bounds), (
        "side must not sit alongside the primary when its y-interval "
        "would overlap the callout's y-interval"
    )
    anchor = tape.anchor(part="box", index=0, name="bottom")
    target = np.array([anchor.x, anchor.y, 0.0])
    label = Text(callout_text, font_size=FONT_SIZES["label"])
    label.next_to(target, direction=np.array([0, -1, 0]))
    arrow = Arrow(label.get_top(), target, buff=0.08)
    rendered = VGroup(arrow, label)
    rendered_bounds = Bounds(
        left=float(rendered.get_left()[0]), right=float(rendered.get_right()[0]),
        bottom=float(rendered.get_bottom()[1]), top=float(rendered.get_top()[1]),
    )
    assert not (
        _horizontal_overlap(rendered_bounds, side.bounds)
        and _vertical_overlap(rendered_bounds, side.bounds)
    ), "rendered callout bounds overlap the side visual"


def test_bottom_callout_forces_a_taller_side_visual_out_of_the_beside_slot():
    """Rendered side-collision regression: a 1.0-high primary beside a
    3.0-high side visual placed adjacent to the primary would give a
    fixed-envelope callout on the primary a side visual to render into.
    `_arrange` sees the bottom-anchored callout and puts every side visual
    taller than the primary into a stacked row instead, so no side visual
    shares the callout's vertical band."""
    import numpy as np
    from manim import Arrow, Text, VGroup

    from app.meta.v3.manim_measurer import FONT_SIZES

    primary = _tape_like_primary(height=1.0, width=4.0)
    tall_side = MeasuredVisual(
        ref="tall", bounds=Bounds(-1.0, 1.0, -1.5, 1.5),
        parts={}, paths={}, payload={},
    )
    answer = MeasuredVisual(
        ref="evaluated_answer", bounds=Bounds(-1.0, 1.0, -0.275, 0.275),
        parts={}, paths={}, payload={},
    )
    callout_text = "1 km = 1000 m"
    relations = [_callout(
        "tape", part="box", index=0, anchor="bottom", text=callout_text,
    )]

    placed = place_vertical_lesson([primary, tall_side, answer], relations)

    by_ref = {item.measured.ref: item for item in placed}
    tape, side = by_ref["tape"], by_ref["tall"]
    # Side must not sit alongside the primary -- its y-band would overlap
    # the callout's y-band otherwise.
    assert not _vertical_overlap(tape.bounds, side.bounds), (
        "a taller side visual must be stacked above or below the primary "
        "when the primary has a bottom-anchored callout"
    )
    # And, rendered end-to-end, the actual callout mobject shares no pixels
    # with the side visual either.
    anchor = tape.anchor(part="box", index=0, name="bottom")
    target = np.array([anchor.x, anchor.y, 0.0])
    label = Text(callout_text, font_size=FONT_SIZES["label"])
    label.next_to(target, direction=np.array([0, -1, 0]))
    arrow = Arrow(label.get_top(), target, buff=0.08)
    rendered = VGroup(arrow, label)
    rendered_bounds = Bounds(
        left=float(rendered.get_left()[0]), right=float(rendered.get_right()[0]),
        bottom=float(rendered.get_bottom()[1]), top=float(rendered.get_top()[1]),
    )
    assert not (
        _horizontal_overlap(rendered_bounds, side.bounds)
        and _vertical_overlap(rendered_bounds, side.bounds)
    ), "rendered callout bounds overlap the side visual"


def _horizontal_overlap(first, second):
    return max(first.left, second.left) < min(first.right, second.right)


def _vertical_overlap(first, second):
    return max(first.bottom, second.bottom) < min(first.top, second.top)


def test_bottom_callout_on_a_primary_with_a_much_taller_side_visual_still_rejects():
    """When the taller side moved out of the beside slot cannot fit in a
    stacked row either, the lesson rejects at compile time. A 8.5-high
    side stacked above a 1.0-high primary with a 0.55-high answer builds
    a 10.95-unit column against the 7.2-unit frame -- there is no scale
    that fits."""
    primary = _tape_like_primary(height=1.0, width=4.0)
    tall_side = MeasuredVisual(
        ref="tall", bounds=Bounds(-1.0, 1.0, -4.25, 4.25),
        parts={}, paths={}, payload={},
    )
    answer = MeasuredVisual(
        ref="evaluated_answer", bounds=Bounds(-1.0, 1.0, -0.275, 0.275),
        parts={}, paths={}, payload={},
    )
    relations = [_callout("tape", part="box", index=0, anchor="bottom", text="!")]

    with pytest.raises(V3ValidationError) as excinfo:
        place_vertical_lesson([primary, tall_side, answer], relations)
    assert excinfo.value.failure.code == "below_minimum_text_scale"


def test_bottom_callout_stays_in_frame_when_no_below_stack_absorbs_the_gap():
    """Answerless layout: `_place_instructional` inserts a gap below the
    primary only when there is a below stack to push. Crediting a phantom
    `GAP * scale` against the envelope in that case shrinks the reservation
    below what the callout actually needs and drops its tip past the safe
    frame's bottom edge."""
    primary = _tape_like_primary(height=6.0, width=4.0)
    relations = [_callout("tape", part="box", index=0, anchor="bottom")]

    placed = place_vertical_lesson([primary], relations)

    by_ref = {item.measured.ref: item for item in placed}
    tape = by_ref["tape"]
    # `box[0].bottom` sits at the primary's own outer bottom, so the callout
    # tip is at `anchor_y - CALLOUT_ENVELOPE`.
    anchor_y = tape.anchor(part="box", index=0, name="bottom").y
    callout_tip_y = anchor_y - CALLOUT_ENVELOPE
    assert callout_tip_y >= SAFE_FRAME.bottom - 1e-9, (
        f"callout tip {callout_tip_y:g} escapes frame bottom {SAFE_FRAME.bottom:g}"
    )


def test_bottom_callout_pad_credits_the_gap_already_below_the_primary():
    """Reserving the full CALLOUT_ENVELOPE ignores the GAP the layout already
    inserts between the primary band and whatever sits below it. On a
    near-limit column that difference decides whether the lesson fits: a 9.2
    unit column against a 7.2 unit frame lands at scale 0.72 when the gap is
    credited, and 0.6848 (below MIN_TEXT_SCALE) when it is not."""
    primary = _tape_like_primary(height=4.0, width=4.0)
    support = MeasuredVisual(
        ref="support", bounds=Bounds(-3.0, 3.0, -1.5, 1.5),
        parts={}, paths={}, payload={},
    )
    answer = MeasuredVisual(
        ref="evaluated_answer", bounds=Bounds(-2.0, 2.0, -0.65, 0.65),
        parts={}, paths={}, payload={},
    )
    relations = [_callout("tape", part="box", index=0, anchor="bottom")]

    placed = place_vertical_lesson([primary, support, answer], relations)

    by_ref = {item.measured.ref: item for item in placed}
    # Column: 4.0 + 0.45 + 3.0 + 0.45 + 1.3 = 9.2. Scale = (7.2 - 0.9) /
    # (9.2 - 0.45) = 6.3/8.75 = 0.72.
    assert by_ref["tape"].scale == pytest.approx(0.72, abs=1e-3)
    primary_bottom = by_ref["tape"].bounds.bottom
    answer_top = by_ref["evaluated_answer"].bounds.top
    # The scaled gap plus the reservation must together hold the envelope.
    assert primary_bottom - answer_top >= CALLOUT_ENVELOPE - 1e-9


def test_bottom_anchored_callout_on_a_non_primary_visual_reserves_nothing():
    """The reservation is scoped to the primary because that is the visual
    the answer is stacked directly below. A callout targeting a supporting
    visual is not currently addressed by #82 and must not silently shrink
    unrelated lessons."""
    measurer = _WidthPerCharacterMeasurer()
    measured = [
        _label("primary", "P", measurer),
        _label("supporting", "note", measurer),
        _answer("22", measurer),
    ]
    relations = [_callout("supporting", part=None, index=None, anchor="bottom")]

    with_relation = place_vertical_lesson(measured, relations)
    without_relation = place_vertical_lesson(measured)

    assert {item.measured.ref: item.bounds for item in with_relation} == {
        item.measured.ref: item.bounds for item in without_relation
    }
