from collections.abc import Sequence
from dataclasses import dataclass

from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.geometry import (
    Bounds, MeasuredVisual, PlacedVisual, Point, SemanticPart, translate_bounds,
)


SAFE_FRAME = Bounds(-6.6, 6.6, -3.6, 3.6)
MIN_TEXT_SCALE = 0.7
GAP = 0.45
#: The downward reach of a rendered callout below its anchor point: one line of
#: `FONT_SIZES["label"]` text plus the arrow that connects the label to the
#: anchor, plus the `next_to` buff. Fixed in world units because
#: `renderer._build_relation` builds the callout at that font size regardless
#: of the lesson's uniform scale, so the space to reserve for it does not
#: shrink alongside the visuals (see #82).
CALLOUT_ENVELOPE = 0.9
#: The answer used to be placed in a reserved strip at the bottom of the frame,
#: which read as a caption stapled under the lesson rather than as its outcome.
#: It is now arranged with everything else, so the instructional frame is the
#: whole safe frame.
INSTRUCTIONAL_FRAME = SAFE_FRAME
ANSWER_REF = "evaluated_answer"


def scale_measured_visual(item: MeasuredVisual, scale: float) -> MeasuredVisual:
    scale_point = lambda point: Point(point.x * scale, point.y * scale)
    scale_bounds = lambda bounds: Bounds(
        bounds.left * scale, bounds.right * scale,
        bounds.bottom * scale, bounds.top * scale,
    )
    parts = {
        key: SemanticPart(part.part, part.index, scale_bounds(part.bounds))
        for key, part in item.parts.items()
    }
    paths = {
        name: [scale_point(point) for point in points]
        for name, points in item.paths.items()
    }
    return MeasuredVisual(
        ref=item.ref,
        bounds=scale_bounds(item.bounds),
        parts=parts,
        paths=paths,
        payload=item.payload,
    )


@dataclass(frozen=True)
class _Arrangement:
    """Which supporting visuals sit beside the primary and which stack over it."""

    primary: MeasuredVisual
    left: list[MeasuredVisual]
    right: list[MeasuredVisual]
    above: list[MeasuredVisual]
    below: list[MeasuredVisual]


def place_vertical_lesson(
    measured_visuals: Sequence[MeasuredVisual],
    relations: Sequence[object] = (),
) -> list[PlacedVisual]:
    arrangement = _arrange(measured_visuals)
    callout_room = _bottom_callout_room_per_scale(arrangement, relations)
    scale = min(1.0, _fit_instructional_scale(
        arrangement, INSTRUCTIONAL_FRAME, callout_room,
    ))
    if scale < MIN_TEXT_SCALE:
        raise V3ValidationError(V3Failure(
            code="below_minimum_text_scale",
            path="visuals",
            expected=f"a uniform scale of at least {MIN_TEXT_SCALE:g}",
            observed=f"{scale:g}",
            hint="reduce visual content so the lesson remains readable",
        ))
    primary_bottom_pad = _callout_pad(callout_room, scale)
    placed_by_ref = {
        item.measured.ref: item
        for item in _place_instructional(
            arrangement, INSTRUCTIONAL_FRAME, scale, primary_bottom_pad,
        )
    }
    return [placed_by_ref[item.ref] for item in measured_visuals]


def _bottom_callout_room_per_scale(arrangement, relations):
    """Room, per unit of `scale`, between a bottom-anchored callout's anchor
    on the primary and whatever the callout tip must stay above.

    Two summands, both in unscaled units:
    - `interior`: room within the primary's own bounds below the anchor.
      rectangle_measurement's length label pushes bounds.bottom ~0.68
      below length_edge[0].bottom, so a callout there absorbs the envelope
      without a reservation.
    - `GAP` when `arrangement.below` is nonempty: the gap
      `_place_instructional` inserts between the primary band and the below
      stack. Answerless layouts insert no such gap.

    A taller side visual pulls band_bottom below primary.bounds.bottom, but
    that band padding is *occupied* by the side over the side's x-range --
    counting it as empty callout room lets the callout render into the
    side's pixels (`callout_collision`). Verifying disjointness would need
    the callout's rendered width against the side's *scaled* placed range;
    the width depends on glyph shape (a "WWWWWW" measures ~2.7 units where
    a fixed-per-char estimate says 1.2) and side ranges scale while the
    callout does not, so the two are not comparable without the measurer.
    Forfeit the credit rather than risk the false positive; the lesson
    rejects at compile time with `below_minimum_text_scale` rather than
    dead-ending at the rendered gate.

    The tightest callout dictates the constraint. Returns None when no
    bottom-anchored callout targets the primary.
    """
    primary = arrangement.primary
    if primary is None or not relations:
        return None
    below_gap = GAP if arrangement.below else 0.0
    tightest = None
    for relation in relations:
        target = getattr(relation, "target", None)
        if target is None or getattr(target, "visual_ref", None) != primary.ref:
            continue
        if getattr(target, "anchor", None) != "bottom":
            continue
        try:
            anchor_point = primary.anchor(
                part=target.part, index=target.index, name="bottom",
            )
        except KeyError:
            # Leave anchor validity to `resolve_relation`.
            continue
        room = (anchor_point.y - primary.bounds.bottom) + below_gap
        tightest = room if tightest is None else min(tightest, room)
    return tightest


def _callout_pad(callout_room_per_scale, scale):
    """Fixed world-unit clearance to add below the primary band for a
    bottom-anchored callout. Only the shortfall against the envelope,
    after crediting the room already available at the solved `scale`,
    has to be reserved.
    """
    if callout_room_per_scale is None:
        return 0.0
    return max(0.0, CALLOUT_ENVELOPE - callout_room_per_scale * scale)


def _arrange(instructional: Sequence[MeasuredVisual]) -> _Arrangement:
    """Send each supporting visual beside the primary, or to a row of its own.

    A visual placed beside the primary has to fit in half the frame minus the
    primary's half-width -- roughly 3 units, against the 13.2 a full-width row
    offers. Forcing every supporting visual into that slot meant one ordinary
    label ("Perimeter = 2 x (length + width)", 6.6 units) shrank the whole
    lesson's uniform scale below MIN_TEXT_SCALE and failed the candidate
    outright, for want of using space the frame already had.

    The split is decided on unscaled measurements so it does not depend on the
    scale being solved for.

    The answer is exempt from the split: it takes the last row whenever there is
    anything else to arrange, and becomes the primary itself when it is alone.
    Left to `_balanced_pair`, a wide answer statement would be sorted into
    `above` by extent and end up over the lesson it concludes.
    """
    if not instructional:
        return _Arrangement(None, [], [], [], [])
    answer = next((item for item in instructional if item.ref == ANSWER_REF), None)
    rest = [item for item in instructional if item is not answer]
    if not rest:
        return _Arrangement(answer, [], [], [], [])
    primary, *supporting = rest
    budget = _side_budget(primary, INSTRUCTIONAL_FRAME)
    beside = [item for item in supporting if _width(item) <= budget]
    stacked = [item for item in supporting if _width(item) > budget]
    left, right = _balanced_pair(beside, _stack_width)
    above, below = _balanced_pair(stacked, lambda items: _stack_height(items, GAP))
    if answer is not None:
        below = [*below, answer]
    return _Arrangement(primary, left, right, above, below)


def _side_budget(primary: MeasuredVisual, frame: Bounds) -> float:
    half_width = (frame.right - frame.left) / 2
    return half_width - _width(primary) / 2 - GAP


def _width(item: MeasuredVisual) -> float:
    return item.bounds.right - item.bounds.left


def _height(item: MeasuredVisual) -> float:
    return item.bounds.top - item.bounds.bottom


def _stack_height(items: Sequence[MeasuredVisual], gap: float) -> float:
    if not items:
        return 0
    return sum(item.bounds.top - item.bounds.bottom for item in items) + gap * (len(items) - 1)


def _fit_instructional_scale(
    arrangement: _Arrangement, frame: Bounds,
    callout_room_per_scale: float | None = None,
) -> float:
    if arrangement.primary is None:
        return 1.0
    primary = arrangement.primary
    vertical_scale = _fit_vertical_scale(
        _column_height(arrangement, GAP), frame.top - frame.bottom,
        callout_room_per_scale,
    )
    half_width = (frame.right - frame.left) / 2
    horizontal_scale = min(
        _fit_extent(_horizontal_extent(primary, arrangement.left), half_width),
        _fit_extent(_horizontal_extent(primary, arrangement.right), half_width),
    )
    # A stacked row spans the whole frame, not half of it.
    stacked = arrangement.above + arrangement.below
    widest_row = max((_width(item) for item in stacked), default=0.0)
    row_scale = _fit_extent(widest_row, frame.right - frame.left)
    return min(horizontal_scale, vertical_scale, row_scale)


def _band_height(arrangement: _Arrangement) -> float:
    """Height of the row holding the primary visual and anything beside it."""
    beside = arrangement.left + arrangement.right
    return max([_height(arrangement.primary), *(_height(item) for item in beside)])


def _column_height(arrangement: _Arrangement, gap: float) -> float:
    height = _band_height(arrangement)
    for stack in (arrangement.above, arrangement.below):
        if stack:
            height += _stack_height(stack, gap) + gap
    return height


def _fit_extent(extent: float, available: float) -> float:
    return available / extent if extent else 1.0


def _fit_vertical_scale(
    column_h: float, frame_h: float, callout_room_per_scale,
) -> float:
    """The largest scale that fits the column and any callout envelope.

    Without a bottom callout on the primary this is just `frame_h / column_h`.
    With one, the callout adds a fixed world-unit demand (`CALLOUT_ENVELOPE`)
    which is not scaled. `callout_room_per_scale * s` of that demand is met
    by clearance already present at that scale (see
    `_bottom_callout_room_per_scale` for the summands).

    The joint vertical constraint is
    `column_h * s + max(0, CALLOUT_ENVELOPE - room_per_scale * s) <= frame_h`,
    linear in `s` on each side of the transition.
    """
    if not column_h:
        return 1.0
    unpadded_scale = frame_h / column_h
    if callout_room_per_scale is None:
        return unpadded_scale
    if callout_room_per_scale * unpadded_scale >= CALLOUT_ENVELOPE:
        # Already-present room absorbs the envelope at the ordinary scale;
        # no pad, no scale penalty.
        return unpadded_scale
    denominator = column_h - callout_room_per_scale
    if denominator <= 0:
        # Room-per-scale outweighs the whole column; nothing left for the pad
        # to bind against.
        return 1.0
    return (frame_h - CALLOUT_ENVELOPE) / denominator


def _horizontal_extent(primary: MeasuredVisual, supporting: Sequence[MeasuredVisual]) -> float:
    primary_half_width = (primary.bounds.right - primary.bounds.left) / 2
    if not supporting:
        return primary_half_width
    return primary_half_width + GAP + _stack_width(supporting)


def _stack_width(items: Sequence[MeasuredVisual]) -> float:
    if not items:
        return 0
    return sum(item.bounds.right - item.bounds.left for item in items) + GAP * (len(items) - 1)


def _balanced_pair(items, extent_of):
    """Split items into two groups of comparable extent, filling the first."""
    first, second = [], []
    for item in items:
        destination = first if extent_of(first) <= extent_of(second) else second
        destination.append(item)
    return first, second


def _place_instructional(
    arrangement: _Arrangement, frame: Bounds, scale: float,
    primary_bottom_pad: float = 0.0,
) -> list[PlacedVisual]:
    if arrangement.primary is None:
        return []
    scaled = _Arrangement(
        scale_measured_visual(arrangement.primary, scale),
        *([scale_measured_visual(item, scale) for item in stack]
          for stack in (arrangement.left, arrangement.right, arrangement.above, arrangement.below)),
    )
    gap = GAP * scale
    primary, left, right = scaled.primary, scaled.left, scaled.right
    band_height = _band_height(scaled)

    # Lay the column out from its top edge so the whole thing -- rows above, the
    # primary's band, rows below -- ends up centred in the frame. The bottom
    # callout pad is a fixed world-unit reservation that widens the column
    # only between the primary and whatever sits below it.
    column_top = frame.center.y + (_column_height(scaled, gap) + primary_bottom_pad) / 2
    placed = _stack_rows(scaled.above, column_top, gap, scale)
    band_top = column_top - (_stack_height(scaled.above, gap) + gap if scaled.above else 0.0)
    center_y = band_top - band_height / 2
    primary_offset = Point(-primary.bounds.center.x, center_y - primary.bounds.center.y)
    # The side cursors start from where the primary visual ACTUALLY lands, not
    # from its untranslated measured box. The two coincide only when the box is
    # centred on its own origin, which was true of every primary visual until
    # `measure_rectangle` began reserving space for dimension labels outside the
    # shape. For an off-centre box, untranslated bounds put each side stack wrong
    # by exactly `primary_offset.x` -- off the frame on one side, over the
    # primary visual on the other.
    primary_bounds = translate_bounds(primary.bounds, primary_offset)
    placed.append(PlacedVisual(primary, primary_offset, scale))
    placed.extend(_place_supporting_side(left, primary_bounds, center_y, -1, scale))
    placed.extend(_place_supporting_side(right, primary_bounds, center_y, 1, scale))
    band_bottom = center_y - band_height / 2
    placed.extend(_stack_rows(
        scaled.below, band_bottom - gap - primary_bottom_pad, gap, scale,
    ))
    return placed


def _stack_rows(
    items: Sequence[MeasuredVisual], top: float, gap: float, scale: float,
) -> list[PlacedVisual]:
    """Centre each item horizontally and stack them downward from `top`."""
    placed, cursor = [], top
    for item in items:
        center_y = cursor - _height(item) / 2
        placed.append(PlacedVisual(
            item,
            Point(-item.bounds.center.x, center_y - item.bounds.center.y),
            scale,
        ))
        cursor -= _height(item) + gap
    return placed


def _place_supporting_side(
    items: Sequence[MeasuredVisual],
    primary_bounds: Bounds,
    center_y: float,
    direction: int,
    scale: float,
) -> list[PlacedVisual]:
    cursor = (primary_bounds.left if direction < 0 else primary_bounds.right) + direction * GAP * scale
    placed = []
    for item in items:
        width = item.bounds.right - item.bounds.left
        center_x = cursor + direction * width / 2
        placed.append(PlacedVisual(
            item,
            Point(center_x - item.bounds.center.x, center_y - item.bounds.center.y),
            scale,
        ))
        cursor += direction * (width + GAP * scale)
    return placed
