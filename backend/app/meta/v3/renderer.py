from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from math import tau

from manim import (
    AnimationGroup,
    Arrow,
    Circle,
    Create,
    Dot,
    FadeIn,
    Line,
    Rectangle,
    Sector,
    Text,
    Transform,
    VectorizedPoint,
    VGroup,
    VMobject,
)

from app.meta.manim_primitives.motions import (
    build_move_along_path,
    build_role_transition,
)
from app.meta.manim_primitives.style import resolve_semantic_style
from app.meta.v3.geometry import Bounds, Point
from app.meta.v3.manim_measurer import FONT_SIZES
from app.meta.v3.resolver import ResolvedAction, ResolvedScene
from app.meta.v3.visual_registry import DEFERRED_PARTS


@dataclass(frozen=True)
class RenderedScene:
    visuals: dict[str, object]
    targets: dict[tuple[str, str | None, int | None], object]
    relations: dict[str, object]
    #: Alias/base keys that share a Line (e.g. `("edge", 0)` and
    #: `("length_edge", 0)`) start at the same role but drift once a `set_role`
    #: fires: only the addressed key is updated even though the Line's colour
    #: changed. No production reader consults this today (only `test_renderer`),
    #: so the divergence is inert -- fold both keys before adding one.
    roles: dict[tuple[str, str | None, int | None], str]
    #: Answer visual ref -> stage name -> mobject. Deliberately NOT in
    #: `targets`: a plan may address the answer, never one of its stages.
    answer_stages: dict[str, dict[str, object]] = field(default_factory=dict)


def render_resolved_scene(scene, resolved_scene: ResolvedScene) -> RenderedScene:
    """Construct and play a semantic scene using only resolved v3 data."""
    composition = _COMPOSITIONS[resolved_scene.style_recipe.composition]
    motion = _MOTIONS[resolved_scene.style_recipe.motion_variant]
    palette = resolved_scene.style_recipe.palette
    rendered = composition(resolved_scene, palette)
    if hasattr(scene, "set_rendered_scene"):
        scene.set_rendered_scene(rendered)

    cursor = 0.0
    for at_seconds, actions in _actions_by_start(resolved_scene.timeline):
        gap = at_seconds - cursor
        if gap > 1e-9:
            scene.wait(gap)

        together = [action for action in actions if action.action.kind == "reveal" and action.action.mode == "together"]
        if len(actions) == len(together):
            _play_together_reveals(scene, together, rendered, motion)
        elif len(actions) == 1:
            action = actions[0]
            if action.action.kind == "set_role":
                _play_role_batches(scene, actions, rendered, palette)
            else:
                _play_action(scene, action, rendered, motion, palette)
        else:
            _play_parallel_actions(scene, actions, rendered, motion, palette)
        cursor = max(cursor, *(action.at_seconds + action.duration_seconds for action in actions))

    final_hold = resolved_scene.total_duration_seconds - cursor
    if final_hold > 1e-9:
        scene.wait(final_hold)
    return rendered


def _actions_by_start(timeline):
    by_start = defaultdict(list)
    for action in timeline:
        by_start[action.at_seconds].append(action)
    return [(at_seconds, by_start[at_seconds]) for at_seconds in sorted(by_start)]


def _build_vertical_lesson(scene: ResolvedScene, palette: str) -> RenderedScene:
    visuals: dict[str, object] = {}
    targets: dict[tuple[str, str | None, int | None], object] = {}
    roles: dict[tuple[str, str | None, int | None], str] = {}
    answer_stages: dict[str, dict[str, object]] = {}
    staged_refs = _staged_answer_refs(scene.timeline)
    for placed in scene.visuals:
        payload = placed.measured.payload
        if isinstance(payload, dict) and "stages" in payload:
            root, stages = _build_answer_stages(
                placed, palette, staged=placed.measured.ref in staged_refs,
            )
            answer_stages[placed.measured.ref] = stages
            children = {}
        else:
            root, children = _build_visual(placed, palette)
        visuals[placed.measured.ref] = root
        targets[(placed.measured.ref, None, None)] = root
        targets.update({(placed.measured.ref, part, index): child for (part, index), child in children.items()})
        role = _initial_role(placed.measured.ref, payload)
        roles[(placed.measured.ref, None, None)] = role
        roles.update({(placed.measured.ref, part, index): role for part, index in children})
    relations = {relation.ref: _build_relation(relation, palette) for relation in scene.relations}
    return RenderedScene(
        visuals=visuals, targets=targets, relations=relations, roles=roles,
        answer_stages=answer_stages,
    )


_COMPOSITIONS: dict[str, Callable[[ResolvedScene, str], RenderedScene]] = {
    "vertical_lesson": _build_vertical_lesson,
    "comparison": _build_vertical_lesson,
    "equation_flow": _build_vertical_lesson,
}


def _smooth_reveal(mobject):
    return FadeIn(mobject)


def _crisp_reveal(mobject):
    return FadeIn(mobject)


_MOTIONS = {"smooth": _smooth_reveal, "crisp": _crisp_reveal}


def _build_visual(placed, palette: str):
    measured, bounds = placed.measured, placed.bounds
    payload = measured.payload
    role = _initial_role(measured.ref, payload)
    style = resolve_semantic_style(palette, role)

    if "display_style" in payload:
        # Checked before `values`: line_plot / dot_plot / box_plot payloads
        # also carry a `values` key, which the ordered_values branch below
        # would otherwise claim first and rebuild as text glyphs at part
        # centers.
        root, children = _build_data_display(measured, placed, palette)
    elif "values" in payload:
        children = {
            ("item", index): _text(
                value, "math_value", _center(part.bounds, placed.offset), placed.scale,
            )
            for (part_name, index), part in measured.parts.items()
            if part_name == "item"
            for value in (payload["values"][index],)
        }
        root = VGroup(*children.values())
    elif {"length", "width", "unit"} <= payload.keys():
        # Size the shape from its EDGE parts, not from `bounds`: the measured
        # bounds now also enclose the dimension labels outside the shape, so
        # using them would stretch the rectangle over its own labels.
        shape_bounds = _shape_bounds(measured, placed.offset)
        root = Rectangle(
            width=shape_bounds.right - shape_bounds.left,
            height=shape_bounds.top - shape_bounds.bottom,
        )
        root.move_to(_array(shape_bounds.center))
        edges = {
            index: _line_for_bounds(_translated(part_value.bounds, placed.offset))
            for (part, index), part_value in measured.parts.items()
            if part == "edge"
        }
        # `rectangle_measurement.measure_rectangle` exposes `length_edge` and
        # `width_edge` as ALIASES for two of the four numbered edges, and
        # `compiler._PART_CARDINALITY` accepts both as emphasize/dim/restore/
        # reveal targets. Register them here against the *same* Line mobjects
        # (length = bottom/top = edge 0/2, width = left/right = edge 3/1),
        # otherwise `_target_mobject` raises KeyError on a plan the compiler,
        # the resolver and the static quality gate all accept. Only `edges` is
        # added to `root` below: the aliases are additional *names* for those
        # same lines, so adding `children` would ask manim to hold a submobject
        # twice -- which it ignores with a warning rather than duplicating, so
        # this is about keeping the intent (and the log) clean, not correctness.
        dimension_labels = {
            (part, 0): _text(
                payload[part], "label",
                _center(measured.parts[(part, 0)].bounds, placed.offset), placed.scale,
            )
            for part in ("length_label", "width_label")
        }
        # `compiler._PART_CARDINALITY` accepts `vertex` as a rectangle target and
        # the resolver resolves it, but nothing built a mobject for one, so any
        # plan naming a vertex -- a callout at the corner a boundary walk starts
        # from, say -- died with a KeyError inside `_target_mobject`. In the probe
        # subprocess that surfaced only as `render_probe_failed`. A
        # `VectorizedPoint` is an anchor with no visible geometry: it gives
        # `_mobject_anchor` a position to read without drawing a corner marker.
        vertices = {
            ("vertex", index): VectorizedPoint(_array(_center(value.bounds, placed.offset)))
            for (name, index), value in measured.parts.items()
            if name == "vertex"
        }
        children = {
            **{("edge", index): line for index, line in edges.items()},
            ("length_edge", 0): edges[0], ("length_edge", 1): edges[2],
            ("width_edge", 0): edges[3], ("width_edge", 1): edges[1],
            **vertices,
            **dimension_labels,
        }
        root.add(*edges.values(), *dimension_labels.values())
    elif "text" in payload:
        root, children = _text(payload["text"], "label", bounds.center, placed.scale), {}
    elif "x_ticks" in payload:
        root, children = _build_coordinate_plane(measured, placed)
    elif "markers" in payload:
        root, children = _line_visual(placed, "marker")
        root.add(*_number_line_labels(measured, placed))
        _add_ray_shade_children(root, children, measured, placed, palette)
    elif {"rows", "columns"} <= payload.keys():
        root, children = _parts_as_rectangles(measured, placed.offset, "cell")
    elif {"whole", "parts"} <= payload.keys():
        root, children = _build_partition(measured, placed, palette)
    elif "boxes" in payload:
        root, children = _build_unit_tape(measured, placed, palette)
    elif {"value", "maximum"} <= payload.keys():
        root, children = _parts_as_rectangles(measured, placed.offset, "segment")
        _add_inverse_operation_children(root, children, measured, placed, palette)
    elif "count" in payload:
        # `_parts_as_dots` returns the children dict alone, not a (root, children)
        # pair -- unpacking it here consumed the dict's KEYS, so every
        # `object_set` visual raised (or, at count == 2, silently bound two part
        # keys to `root` and `children`). Mirror the `partition` branch instead.
        children = _parts_as_dots(measured, placed.offset, "item")
        root = VGroup(*children.values())
    else:
        raise ValueError(f"unsupported resolved visual {measured.ref}")

    _apply_style(root, style)
    return root, children


def _staged_answer_refs(timeline) -> set[str]:
    return {
        action.targets[0].ref.visual_ref
        for action in timeline if action.action.kind == "show_answer_stage"
    }


def _build_answer_stages(placed, palette: str, *, staged: bool):
    """One Text per stage, all centred on the same point.

    Every stage is built up front because `Transform` needs a target mobject to
    morph into, and only the drawn stage is ever added to the scene: the
    transitions mutate that one mobject rather than adding new ones.

    `staged` is False for a program frozen before `show_answer_stage` existed --
    it reveals the answer and never transforms it. Such a program replays
    verbatim (`dynamic_templates.load`), so drawing the `unknown` stage would
    leave a bare "?" as the lesson's final answer with nothing able to resolve
    it; draw the resolved `value` instead.
    """
    style = resolve_semantic_style(palette, _initial_role(placed.measured.ref, placed.measured.payload))
    stages = {
        stage: _text(text, "label", placed.bounds.center, placed.scale)
        for stage, text in placed.measured.payload["stages"].items()
    }
    for mobject in stages.values():
        _apply_style(mobject, style)
    return stages["unknown" if staged else "value"], stages


def _initial_role(ref: str, payload) -> str:
    """The role a visual is drawn in before any `set_role` plays.

    The program declares this per visual, but this function used to re-derive it
    from the payload's shape and return `neutral` for every collection. The two
    agreed only by coincidence, so a program that declared anything else
    compiled role changes the renderer then played as a colour-to-itself
    transform. Prefer what the program said; keep the shape derivation for the
    kinds that do not carry one.
    """
    declared = payload.get("initial_role") if isinstance(payload, dict) else None
    if declared is not None:
        return declared
    if ref == "evaluated_answer" or "stages" in payload or "values" in payload or "text" in payload:
        return "neutral"
    return "structure"


def _text(text: str, font_role: str, center: Point, scale: float = 1.0):
    """Text at the size layout measured it, then reduced by layout's own factor.

    Scaling the built mobject -- rather than asking for `FONT_SIZES[role] *
    scale` -- reproduces exactly what layout computed: it measured the glyphs at
    the base size and multiplied that measurement by `scale`. Re-rendering at a
    smaller font size would re-run font metrics and land somewhere else.
    """
    mobject = Text(text, font_size=FONT_SIZES[font_role])
    if scale != 1.0:
        mobject.scale(scale)
    mobject.move_to(_array(center))
    return mobject


def _line_visual(placed, part_name: str):
    # The line's endpoints come from payload, not `bounds.left/right`: the
    # bounds now reserve a label strip on the sides for wide endpoint labels
    # (see `_measure_number_line`), so bounds are wider than the line itself.
    # Payload coords are unscaled -- `layout.scale_measured_visual` scales
    # bounds and parts but leaves payload alone -- so multiply by
    # `placed.scale` explicitly, matching how `_text` scales rebuilt glyphs.
    measured, offset, scale = placed.measured, placed.offset, placed.scale
    payload = measured.payload
    y = payload["line_center_y"] * scale + offset.y
    left = payload["line_left"] * scale + offset.x
    right = payload["line_right"] * scale + offset.x
    root = Line(_array(Point(left, y)), _array(Point(right, y)))
    children = _parts_as_dots(measured, offset, part_name)
    root_group = VGroup(root, *children.values())
    return root_group, children


def _number_line_labels(measured, placed):
    """The number under each tick.

    Added to the root group rather than registered as children: nothing addresses
    a tick label, and `measured.parts` is what the compiler validates plan targets
    against, so registering them would invent targets no plan should use.
    """
    payload = measured.payload
    # `label_center_y` is a payload coord, which `layout.scale_measured_visual`
    # leaves at its unscaled value; the marker `part.bounds` next to it *has*
    # been scaled. Without this multiplication the labels sat at the unscaled
    # y while the markers sat at the scaled one, so at any layout scale below
    # 1 the label strip drifted below its reserved band.
    y = payload["label_center_y"] * placed.scale + placed.offset.y
    return [
        _text(
            payload["marker_labels"][index],
            "label",
            Point(part.bounds.center.x + placed.offset.x, y),
            placed.scale,
        )
        for (part_name, index), part in sorted(measured.parts.items(), key=lambda item: item[0][1])
        if part_name == "marker"
    ]


def _build_coordinate_plane(measured, placed):
    """Axes projected through the world origin, plus dots and labels.

    Axis endpoints and tick coordinates come from payload (unscaled) and are
    multiplied by `placed.scale` explicitly, matching how `_line_visual`
    handles the number line. Point dots come from `measured.parts`, which
    layout has already scaled. Tick labels sit under the x-axis / left of the
    y-axis; each point label sits above its dot. Labels are added to the root
    group but NOT registered as children -- nothing in the compiler addresses
    them, and inventing target keys for glyphs would let a plan target a
    label the archetype does not expose (mirrors `_number_line_labels`).
    """
    payload = measured.payload
    scale, offset = placed.scale, placed.offset
    cx, cy = offset.x, offset.y
    extent_x = payload["extent_x"] * scale
    extent_y = payload["extent_y"] * scale
    zero_u = payload["axis_zero_u"] * scale
    zero_v = payload["axis_zero_v"] * scale
    axis_y = cy + zero_v
    axis_x = cx + zero_u
    grid_lines = []
    if payload.get("grid"):
        for u_value in payload.get("x_grid_lines", ()):
            u = u_value * scale + cx
            grid_lines.append(Line(
                _array(Point(u, cy - extent_y)),
                _array(Point(u, cy + extent_y)),
            ).set_opacity(0.25))
        for v_value in payload.get("y_grid_lines", ()):
            v = v_value * scale + cy
            grid_lines.append(Line(
                _array(Point(cx - extent_x, v)),
                _array(Point(cx + extent_x, v)),
            ).set_opacity(0.25))
    x_axis = Line(
        _array(Point(cx - extent_x, axis_y)),
        _array(Point(cx + extent_x, axis_y)),
    )
    y_axis = Line(
        _array(Point(axis_x, cy - extent_y)),
        _array(Point(axis_x, cy + extent_y)),
    )
    tick_len = 0.08 * scale
    tick_gap = payload["tick_label_gap"] * scale
    tick_mobjects = []
    tick_labels = []
    for tick in payload["x_ticks"]:
        u = tick["u"] * scale + cx
        tick_mobjects.append(Line(
            _array(Point(u, axis_y - tick_len)),
            _array(Point(u, axis_y + tick_len)),
        ))
        # An empty label means the measurer suppressed it because a point label
        # would have drawn over it -- keep the tick mark, drop the glyph.
        if tick["label"]:
            label_y = axis_y - tick_gap - (tick["label_height"] / 2) * scale
            tick_labels.append(_text(tick["label"], "label", Point(u, label_y), scale))
    for tick in payload["y_ticks"]:
        v = tick["v"] * scale + cy
        tick_mobjects.append(Line(
            _array(Point(axis_x - tick_len, v)),
            _array(Point(axis_x + tick_len, v)),
        ))
        if tick["label"]:
            label_x = axis_x - tick_gap - (tick["label_width"] / 2) * scale
            tick_labels.append(_text(tick["label"], "label", Point(label_x, v), scale))
    children = _parts_as_dots(measured, offset, "point")
    point_labels = []
    for point in payload["points"]:
        u = point["x"] * scale + cx
        v = point["y"] * scale + cy
        # Quadrant offset is chosen at measurement so the label rectangle
        # cannot collide with any tick label rectangle or with a prior point
        # label; a legacy payload written before the collision search shipped
        # falls back to the historical above-the-dot placement.
        if "label_dx" in point:
            label_x = u + point["label_dx"] * scale
            label_y = v + point["label_dy"] * scale
        else:
            point_offset = payload["point_label_offset"]
            label_x = u
            label_y = v + (point_offset + point["label_height"] / 2) * scale
        point_labels.append(_text(point["label"], "label", Point(label_x, label_y), scale))
    root = VGroup(
        *grid_lines, x_axis, y_axis, *tick_mobjects, *tick_labels,
        *children.values(), *point_labels,
    )
    return root, children


def _build_data_display(measured, placed, palette: str):
    """Axes and marks for one of five display styles.

    Marks are added to `children` under the shared `mark` part name so the
    plan can address a specific bar / dot / stack / box without branching on
    display style. Axis lines and tick labels are added to the root group but
    not registered -- nothing addresses them, mirroring `_number_line_labels`.
    """
    payload = measured.payload
    scale, offset = placed.scale, placed.offset
    cx, cy = offset.x, offset.y
    axis_y = payload["axis_y"] * scale + cy
    axis_left = payload["axis_left"] * scale + cx
    axis_right = payload["axis_right"] * scale + cx
    axis_line = Line(
        _array(Point(axis_left, axis_y)), _array(Point(axis_right, axis_y)),
    )
    style = payload["display_style"]
    if style in {"bar_graph", "histogram"}:
        return _build_data_display_bars(measured, placed, palette, axis_line, axis_y)
    if style in {"line_plot", "dot_plot"}:
        return _build_data_display_number_line_points(measured, placed, axis_line, axis_y)
    if style == "box_plot":
        return _build_data_display_box_plot(measured, placed, axis_line, axis_y)
    raise ValueError(f"unsupported data_display style {style!r}")


def _build_data_display_bars(measured, placed, palette, axis_line, axis_y):
    payload = measured.payload
    scale, offset = placed.scale, placed.offset
    cx = offset.x
    children = {}
    parts_group = []
    count_labels = []
    category_labels = []
    label_y = payload["label_center_y"] * scale + offset.y
    for index, bar in enumerate(payload["bars"]):
        bounds = measured.parts[("mark", index)].bounds
        translated = _translated(bounds, placed.offset)
        rect = _rectangle_for_bounds(translated)
        children[("mark", index)] = rect
        parts_group.append(rect)
        cx_bar = (bar["left"] + bar["right"]) / 2 * scale + cx
        # Category label under the axis.
        category_labels.append(_text(
            bar["label"], "label", Point(cx_bar, label_y), scale,
        ))
        # Count label above the bar top.
        if bar["height"] > 0:
            count_y = translated.top + payload["count_label_gap"] * scale + (
                measurer_height_for("label") / 2
            ) * scale
            count_labels.append(_text(
                bar["count_text"], "label", Point(cx_bar, count_y), scale,
            ))
    root = VGroup(axis_line, *parts_group, *category_labels, *count_labels)
    root.add(*_data_display_axis_title(payload, placed))
    return root, children


def _build_data_display_number_line_points(measured, placed, axis_line, axis_y):
    payload = measured.payload
    scale, offset = placed.scale, placed.offset
    cx = offset.x
    style = payload["display_style"]
    children = {}
    marks = []
    for index, entry in enumerate(payload["values"]):
        u = entry["u"] * scale + cx
        cy_mark = entry["cy"] * scale + offset.y
        if style == "dot_plot":
            mark = Dot(_array(Point(u, cy_mark)))
        else:  # line_plot: X-shaped mark drawn as two crossed line segments
            half = payload["mark_half"] * scale
            mark = VGroup(
                Line(_array(Point(u - half, cy_mark - half)),
                     _array(Point(u + half, cy_mark + half))),
                Line(_array(Point(u - half, cy_mark + half)),
                     _array(Point(u + half, cy_mark - half))),
            )
        children[("mark", index)] = mark
        marks.append(mark)
    tick_group = _data_display_axis_ticks_group(payload, placed, axis_y)
    root = VGroup(axis_line, *tick_group, *marks)
    root.add(*_data_display_axis_title(payload, placed))
    return root, children


def _build_data_display_box_plot(measured, placed, axis_line, axis_y):
    payload = measured.payload
    scale, offset = placed.scale, placed.offset
    cx, cy = offset.x, offset.y
    projected = {name: value * scale + cx for name, value in payload["projected"].items()}
    box_top = payload["box_top"] * scale + cy
    box_bottom = payload["box_bottom"] * scale + cy
    box_center_y = (box_top + box_bottom) / 2
    box_rect = _rectangle_for_bounds(Bounds(
        projected["q1"], projected["q3"], box_bottom, box_top,
    ))
    median_line = Line(
        _array(Point(projected["median"], box_bottom)),
        _array(Point(projected["median"], box_top)),
    )
    left_whisker = Line(
        _array(Point(projected["minimum"], box_center_y)),
        _array(Point(projected["q1"], box_center_y)),
    )
    right_whisker = Line(
        _array(Point(projected["q3"], box_center_y)),
        _array(Point(projected["maximum"], box_center_y)),
    )
    # Small vertical bars capping each whisker so the extrema read as endpoints.
    cap_h = 0.2 * scale
    left_cap = Line(
        _array(Point(projected["minimum"], box_center_y - cap_h)),
        _array(Point(projected["minimum"], box_center_y + cap_h)),
    )
    right_cap = Line(
        _array(Point(projected["maximum"], box_center_y - cap_h)),
        _array(Point(projected["maximum"], box_center_y + cap_h)),
    )
    children = {("mark", 0): box_rect}
    tick_group = _data_display_axis_ticks_group(payload, placed, axis_y)
    root = VGroup(
        axis_line, *tick_group,
        left_whisker, right_whisker, left_cap, right_cap,
        box_rect, median_line,
    )
    root.add(*_data_display_axis_title(payload, placed))
    return root, children


def _data_display_axis_ticks_group(payload, placed, axis_y):
    """Tick marks and labels along the axis line."""
    scale, offset = placed.scale, placed.offset
    cx = offset.x
    tick_len = 0.08 * scale
    gap = payload["tick_label_gap"] * scale
    items = []
    for tick in payload.get("ticks", ()):
        u = tick["u"] * scale + cx
        items.append(Line(
            _array(Point(u, axis_y - tick_len)),
            _array(Point(u, axis_y + tick_len)),
        ))
        label_cy = axis_y - gap - (tick["label_height"] / 2) * scale
        items.append(_text(tick["text"], "label", Point(u, label_cy), scale))
    return items


def _data_display_axis_title(payload, placed):
    """The optional axis title (e.g. "hours of sleep"), drawn below the axis.

    Placed near the visual's measured bottom edge; the measurer already
    reserved room for the title in `_axis_title_room` when the axis label is
    non-empty.
    """
    title = payload.get("axis_label", "")
    if not title:
        return ()
    scale = placed.scale
    bounds = placed.bounds
    from app.meta.v3.manim_measurer import FONT_SIZES
    label_h = FONT_SIZES["label"] * scale * 0.02
    title_y = bounds.bottom + label_h / 2 + 0.02 * scale
    return (_text(title, "label", Point(placed.offset.x, title_y), scale),)


def measurer_height_for(font_role: str) -> float:
    """Approximate glyph height in scene units, used when the measurer is out of reach.

    `_build_data_display_bars` places count labels above bar tops without
    consulting the TextMeasurer used at measurement time (the resolver has
    the measurer, the renderer does not carry it). A close-enough constant
    based on the label font size is fine here -- the count label lives inside
    the reserved plot-height budget, so slight variance in vertical placement
    does not push past the safe frame.
    """
    from app.meta.v3.manim_measurer import FONT_SIZES
    return FONT_SIZES[font_role] * 0.014


def _add_inverse_operation_children(root, children, measured, placed, palette: str):
    """Register x_region / constant_region / x_part group children on a bar.

    Only fires when the bar declares an `inverse_operation` partition
    (`payload["constant"] is not None`). Each group child is a VGroup over
    the segment mobjects it spans, so a `set_role` on the group applies
    the colour transform to every segment inside the region uniformly --
    mirroring how `_build_unit_tape` registers per-label VGroups so
    `unit_substitution` can reveal a whole label class at once.

    Also paints thin divider Lines between the x_region and the
    constant_region and (when coefficient > 1) between adjacent x_parts,
    so the partition reads as split even before any role change fires.
    The dividers are added to `root` (they arrive with the whole-bar
    reveal), NOT registered as children, since nothing addresses them.
    """
    payload = measured.payload
    if payload.get("constant") is None:
        return
    constant = payload["constant"]
    coefficient = payload["coefficient"] or 1
    maximum = payload["maximum"]
    x_segment_count = maximum - constant
    segments_per_x = x_segment_count // coefficient

    def _segment_group(first, last):
        return VGroup(*(children[("segment", idx)] for idx in range(first, last + 1)))

    children[("x_region", 0)] = _segment_group(0, x_segment_count - 1)
    children[("constant_region", 0)] = _segment_group(x_segment_count, maximum - 1)
    for i in range(coefficient):
        first = i * segments_per_x
        last = first + segments_per_x - 1
        children[("x_part", i)] = _segment_group(first, last)

    def _divider_between(left_seg_index, right_seg_index):
        left_bounds = _translated(
            measured.parts[("segment", left_seg_index)].bounds, placed.offset,
        )
        right_bounds = _translated(
            measured.parts[("segment", right_seg_index)].bounds, placed.offset,
        )
        mid_x = (left_bounds.right + right_bounds.left) / 2
        # Extend slightly above/below the bar so the divider reads as a
        # partition rather than a gap between segments (segments already
        # have a `gap` of 0.05 between them at measurement time).
        overhang = 0.15
        top = left_bounds.top + overhang
        bottom = left_bounds.bottom - overhang
        return Line(_array(Point(mid_x, bottom)), _array(Point(mid_x, top)))

    dividers = [_divider_between(x_segment_count - 1, x_segment_count)]
    if coefficient > 1:
        for i in range(1, coefficient):
            first = i * segments_per_x
            dividers.append(_divider_between(first - 1, first))
    for divider in dividers:
        divider.set_stroke(width=3)
    root.add(*dividers)


def _add_ray_shade_children(root, children, measured, placed, palette: str):
    """Register the boundary circle and shaded ray on a number_line.

    Both parts are declared deferred (`visual_registry.DEFERRED_PARTS`), so
    they're built here but held back from `root` -- the beat_expander's
    `ray_shade` branch emits a `RevealAction` on each in beat order,
    matching how `_build_unit_tape` defers `target_label`.

    An `open` boundary_kind draws an unfilled ring (the strict inequality
    excludes the value); `closed` fills the dot (the inequality includes
    the value). The ray is a thick Line from the boundary outward to the
    line endpoint in `ray_direction`, coloured `focus` so it reads as
    highlighted shading rather than another axis segment.
    """
    payload = measured.payload
    if payload.get("boundary_x") is None:
        return
    scale, offset = placed.scale, placed.offset
    boundary_x = payload["boundary_x"] * scale + offset.x
    line_y = payload["line_center_y"] * scale + offset.y
    boundary_kind = payload["boundary_kind"]
    ray_end_x = payload["ray_end_x"] * scale + offset.x
    dot_radius = 0.12 * scale
    circle = Circle(radius=dot_radius).move_to(_array(Point(boundary_x, line_y)))
    ray_style = resolve_semantic_style(palette, "focus")
    ray_color = ray_style["color"]
    if boundary_kind == "closed":
        # Filled disc: paint the circle in the focus colour so it reads as
        # the included endpoint the inequality contains.
        circle.set_fill(ray_color, opacity=1.0)
        circle.set_stroke(ray_color, width=3)
    else:
        # Open ring: no fill, ring in the focus colour to match the ray.
        circle.set_fill(opacity=0.0)
        circle.set_stroke(ray_color, width=3)
    ray = Line(
        _array(Point(boundary_x, line_y)),
        _array(Point(ray_end_x, line_y)),
    )
    ray.set_stroke(ray_color, width=6)
    children[("boundary", 0)] = circle
    children[("ray", 0)] = ray
    # Deferred: NOT added to root. `beat_expander` reveals each on its
    # own beat via the DEFERRED_PARTS mechanism.


def _parts_as_dots(measured, offset: Point, part_name: str):
    return {
        (part, index): Dot(_array(_center(value.bounds, offset)))
        for (part, index), value in measured.parts.items()
        if part == part_name
    }


def _parts_as_rectangles(measured, offset: Point, part_name: str):
    children = {
        (part, index): _rectangle_for_bounds(_translated(value.bounds, offset))
        for (part, index), value in measured.parts.items()
        if part == part_name
    }
    return VGroup(*children.values()), children


def _build_unit_tape(measured, placed, palette: str):
    """Boxes and source labels on screen; target labels registered but held back.

    `visual_registry.DEFERRED_PARTS` declares `target_label` as arriving later, and
    the root group is what the whole-visual reveal fades in -- so a target label
    added to the root would be visible from the first beat, and the staged reveal
    would fade in something already on screen. They are still registered as
    children, which is what makes them addressable when their reveal plays.
    """
    payload = measured.payload
    children = {}
    root = VGroup()
    deferred = DEFERRED_PARTS.get("unit_tape", ())
    for index, box in enumerate(payload["boxes"]):
        box_bounds = _translated(measured.parts[("box", index)].bounds, placed.offset)
        outline = _rectangle_for_bounds(box_bounds)
        children[("box", index)] = outline
        root.add(outline)
        if box["fill_fraction"] < 1.0:
            root.add(_partial_fill(box_bounds, box["fill_fraction"], palette))
        for part in ("source_label", "target_label"):
            label_bounds = _translated(measured.parts[(part, index)].bounds, placed.offset)
            text = _text(box[part], "label", label_bounds.center, placed.scale)
            children[(part, index)] = text
            if part not in deferred:
                root.add(text)
    for part in ("source_label", "target_label"):
        children[(part, None)] = VGroup(*(
            children[(part, index)] for index in range(len(payload["boxes"]))
        ))
    return root, children


def _build_partition(measured, placed, palette: str):
    """Wedge-per-part rendering, with the numerator's wedges filled.

    A plain Circle + dots hid the numerator entirely: a plan for "2/3" and one
    for "3/3" rendered identically. Each part becomes an addressable Sector so
    a `set_role` on `partition[i]` recolours a visible wedge, not a marker dot;
    the first `shaded` wedges are filled to make the numerator readable at
    rest, before any beat plays.
    """
    payload = measured.payload
    center = _array(measured.bounds.center) + _array(placed.offset)
    count = payload["parts"]
    shaded = payload.get("shaded", 0)
    radius = (measured.bounds.right - measured.bounds.left) / 2
    angle = tau / count
    style = resolve_semantic_style(palette, "focus")
    wedges = {}
    for index in range(count):
        wedge = Sector(radius=radius, angle=angle, start_angle=index * angle)
        wedge.move_arc_center_to(center)
        if index < shaded:
            wedge.set_fill(style["color"], opacity=0.4)
        wedges[("partition", index)] = wedge
    root = VGroup(*wedges.values())
    return root, wedges


def _partial_fill(bounds: Bounds, fraction: float, palette: str):
    """The shaded portion of the remainder box, so 0.75 of a unit reads as 0.75."""
    width = (bounds.right - bounds.left) * fraction
    filled = Rectangle(width=max(width, 0.02), height=bounds.top - bounds.bottom)
    filled.move_to(_array(Point(bounds.left + width / 2, bounds.center.y)))
    style = resolve_semantic_style(palette, "focus")
    _apply_style(filled, style)
    filled.set_fill(style["color"], opacity=0.3)
    return filled


def _rectangle_for_bounds(bounds: Bounds):
    rectangle = Rectangle(width=max(bounds.right - bounds.left, 0.02), height=max(bounds.top - bounds.bottom, 0.02))
    rectangle.move_to(_array(bounds.center))
    return rectangle


def _shape_bounds(measured, offset: Point) -> Bounds:
    """The rectangle proper, from the union of its four edges."""
    edges = [
        _translated(part.bounds, offset)
        for (name, _index), part in measured.parts.items() if name == "edge"
    ]
    return Bounds(
        min(edge.left for edge in edges), max(edge.right for edge in edges),
        min(edge.bottom for edge in edges), max(edge.top for edge in edges),
    )


def _line_for_bounds(bounds: Bounds):
    return Line(_array(Point(bounds.left, bounds.bottom)), _array(Point(bounds.right, bounds.top)))


def _build_relation(relation, palette: str):
    target = _array(relation.target)
    label = Text(relation.text, font_size=FONT_SIZES["label"])
    label.next_to(target, direction=np.array([0, -1, 0]))
    arrow = Arrow(label.get_top(), target, buff=0.08)
    relation_mobject = VGroup(arrow, label)
    _apply_style(relation_mobject, resolve_semantic_style(palette, "focus"))
    return relation_mobject


def _translated(bounds: Bounds, offset: Point) -> Bounds:
    return Bounds(bounds.left + offset.x, bounds.right + offset.x, bounds.bottom + offset.y, bounds.top + offset.y)


def _center(bounds: Bounds, offset: Point) -> Point:
    return Point(bounds.center.x + offset.x, bounds.center.y + offset.y)


def _array(point: Point):
    return np.array([point.x, point.y, 0.0])


def _apply_style(mobject, style: dict) -> None:
    mobject.set_color(style["color"])
    mobject.set_stroke(width=style["stroke_width"])


def _play_together_reveals(scene, actions, rendered: RenderedScene, motion) -> None:
    animations, refs = [], []
    for action in actions:
        for target in action.targets:
            animations.append(motion(_target_mobject(rendered, target.ref)))
            if target.ref.visual_ref not in refs:
                refs.append(target.ref.visual_ref)
    animation = AnimationGroup(*animations)
    _play(
        scene, animation, max(action.duration_seconds for action in actions), "group_reveal",
        target_refs=tuple(refs), events=tuple(_probe_event(action) for action in actions),
    )


def _play_role_batches(scene, actions, rendered: RenderedScene, palette: str) -> None:
    role_actions = [action for action in actions if action.action.kind == "set_role"]
    if not role_actions:
        return
    by_role = defaultdict(list)
    for action in role_actions:
        by_role[action.action.role].append(action)
    for role, batch in by_role.items():
        target_refs = [target.ref for action in batch for target in action.targets]
        target_keys = tuple(_target_tuple(target_ref) for target_ref in target_refs)
        animations = [
            build_role_transition(_target_mobject(rendered, target_ref), resolve_semantic_style(palette, role))
            for target_ref in target_refs
        ]
        rendered.roles.update({target_key: role for target_key in target_keys})
        kind = "set_role" if role == "focus" and len(target_keys) == 1 else "role_transition"
        target = target_keys[0] if len(target_keys) == 1 else None
        _play(
            scene,
            AnimationGroup(*animations),
            max(action.duration_seconds for action in batch),
            kind,
            target=target,
            targets=target_keys,
            role=role,
            events=tuple(_probe_event(action) for action in batch),
        )


def _play_parallel_actions(scene, actions, rendered: RenderedScene, motion, palette: str) -> None:
    # A `set_role` and a `show_answer_stage` on the SAME mobject in one slot --
    # exactly what the conclude beat emits on the answer -- became two competing
    # `Transform`s in one `AnimationGroup`. Both rewrite that mobject's points
    # every frame and the later one wins, and `build_role_transition`'s target is
    # a recoloured copy of the mobject's state at `begin()` -- i.e. the work
    # stage. So the recolour overwrote the value stage and every lesson ended on
    # "2.75 x 1000 = ? meters" in the conclusion colour: the resolved answer was
    # never drawn. They describe one visual event, so emit one animation.
    staged = {
        _target_tuple(action.targets[0].ref): action.action.stage
        for action in actions if action.action.kind == "show_answer_stage"
    }
    role_targets = {
        _target_tuple(target.ref)
        for action in actions if action.action.kind == "set_role"
        for target in action.targets
    }
    # Resolved before the loop, not during it: the compiler emits the stage action
    # first, so deciding as we go would let it contribute its own animation before
    # the `set_role` that absorbs it is ever seen -- two Transforms again.
    merged = role_targets & staged.keys()

    animations = []
    for action in actions:
        if action.action.kind == "set_role":
            style = resolve_semantic_style(palette, action.action.role)
            target_keys = tuple(_target_tuple(target.ref) for target in action.targets)
            for target, target_key in zip(action.targets, target_keys):
                animations.append(
                    _stage_transition(rendered, target.ref, staged[target_key], style)
                    if target_key in merged
                    else build_role_transition(_target_mobject(rendered, target.ref), style)
                )
            rendered.roles.update({target_key: action.action.role for target_key in target_keys})
        elif action.action.kind == "reveal" and action.action.mode == "together":
            animations.extend(motion(_target_mobject(rendered, target.ref)) for target in action.targets)
        elif action.action.kind == "show_answer_stage" and _target_tuple(action.targets[0].ref) in merged:
            continue  # already carried by the co-slotted `set_role` above
        else:
            animations.append(_action_animation(action, rendered, motion, palette))
    _play(
        scene,
        AnimationGroup(*animations),
        max(action.duration_seconds for action in actions),
        "parallel",
        events=tuple(_probe_event(action) for action in actions),
    )


def _play_action(scene, action: ResolvedAction, rendered: RenderedScene, motion, palette: str) -> None:
    animation = _action_animation(action, rendered, motion, palette)
    kind = action.action.kind
    if kind == "reveal":
        _play(
            scene, animation, action.duration_seconds, "stagger_reveal",
            target_refs=tuple(target.ref.visual_ref for target in action.targets), events=(_probe_event(action),),
        )
    else:
        _play(scene, animation, action.duration_seconds, kind, target=_action_target(action), events=(_probe_event(action),))


def _action_animation(action: ResolvedAction, rendered: RenderedScene, motion, palette: str):
    kind = action.action.kind
    if kind == "reveal":
        return AnimationGroup(*(motion(_target_mobject(rendered, target.ref)) for target in action.targets))
    if kind == "trace":
        path = _path_mobject(action.path)
        _apply_style(path, resolve_semantic_style(palette, "focus"))
        return Create(path)
    if kind == "show_relation":
        return motion(rendered.relations[action.action.relation_ref])
    if kind == "draw":
        return Create(_target_mobject(rendered, action.targets[0].ref))
    if kind == "transform":
        return Transform(_target_mobject(rendered, action.targets[0].ref), _target_mobject(rendered, action.targets[1].ref))
    if kind == "move":
        return build_move_along_path(_target_mobject(rendered, action.targets[0].ref), _path_mobject(action.path))
    if kind == "show_answer_stage":
        return _stage_transition(rendered, action.targets[0].ref, action.action.stage)
    if kind == "signed_hop_arrow":
        return Create(_build_signed_hop_arrow(action, palette))
    if kind == "distance_annotation":
        return Create(_build_distance_annotation(action, palette))
    raise ValueError(f"unsupported resolved action {kind}")


#: Vertical clearance above the number line for the hop arrow. Keeps the shaft
#: clear of the marker dots so the arrowhead reads as a direction rather than
#: as another marker glyph.
_HOP_ARROW_ELEVATION = 0.35
#: Elevation for the distance bracket. Placed above the hop-arrow band so a
#: composite lesson (both strategies) does not stack marks on top of each other.
_DISTANCE_BRACKET_ELEVATION = 0.55
#: Bracket "tick" height dropping from the horizontal span down to each end.
_DISTANCE_BRACKET_TICK = 0.12
#: Label sits above the bracket by this margin so the glyphs clear the span.
_DISTANCE_LABEL_GAP = 0.12


def _build_signed_hop_arrow(action, palette: str):
    """Arrow from the source marker to the target marker, above the line.

    Source-then-target order is what encodes the sign: a positive hop has the
    source left of the target (arrow points right); a negative hop has it right
    of the target (arrow points left).
    """
    source, target = action.targets[0].bounds.center, action.targets[1].bounds.center
    start = Point(source.x, source.y + _HOP_ARROW_ELEVATION)
    end = Point(target.x, target.y + _HOP_ARROW_ELEVATION)
    arrow = Arrow(_array(start), _array(end), buff=0.0, stroke_width=4)
    _apply_style(arrow, resolve_semantic_style(palette, "focus"))
    return arrow


def _build_distance_annotation(action, palette: str):
    """A bracket from the origin to the target marker, labelled with the magnitude.

    The bracket is a three-segment polyline (down-tick at the origin, horizontal
    span across the top, down-tick at the target); the label sits centred above
    the span. Assembled as a `VGroup` so `Create` traces the whole annotation as
    one animation and one recolour.
    """
    origin, target = action.targets[0].bounds.center, action.targets[1].bounds.center
    top_y = max(origin.y, target.y) + _DISTANCE_BRACKET_ELEVATION
    left, right = sorted((origin.x, target.x))
    corners = [
        Point(left, top_y - _DISTANCE_BRACKET_TICK),
        Point(left, top_y),
        Point(right, top_y),
        Point(right, top_y - _DISTANCE_BRACKET_TICK),
    ]
    bracket = VMobject()
    bracket.set_points_as_corners([_array(point) for point in corners])
    label = _text(
        action.action.label, "label",
        Point((left + right) / 2, top_y + _DISTANCE_LABEL_GAP), 1.0,
    )
    # `_text` centres the mobject on the given point, so lift the whole glyph
    # strip clear of the bracket top edge.
    label.shift(np.array([0.0, label.height / 2, 0.0]))
    group = VGroup(bracket, label)
    _apply_style(group, resolve_semantic_style(palette, "focus"))
    return group


def _stage_transition(rendered: RenderedScene, ref, stage: str, style: dict | None = None):
    """Morph the answer text into one of its later stages.

    `style` restyles the destination, for the case where a `set_role` shares the
    slot: the role change and the stage change are then one event on one mobject
    and must be one animation. Restyling the destination rather than dropping the
    recolour also keeps the probe's `set_role` observation (`state_applied`,
    which reads the mobject's colour) true, so `check_state_order` still agrees.
    """
    destination = rendered.answer_stages[ref.visual_ref][stage]
    if style is not None:
        _apply_style(destination, style)
    return Transform(_target_mobject(rendered, ref), destination)


def _action_target(action: ResolvedAction):
    if action.action.kind in {"draw", "move"}:
        return _target_tuple(action.targets[0].ref)
    return None


def _path_mobject(points):
    path = VMobject()
    path.set_points_as_corners([_array(point) for point in points])
    return path


def _target_mobject(rendered: RenderedScene, ref):
    return rendered.targets[_target_tuple(ref)]


def _target_tuple(ref):
    return ref.visual_ref, ref.part, ref.index


def _probe_event(action: ResolvedAction) -> dict:
    return {
        "beat_id": action.beat_id,
        "kind": action.action.kind,
        "targets": tuple(_target_tuple(target.ref) for target in action.targets),
        "role": action.action.role if action.action.kind == "set_role" else None,
        "path_ref": action.action.path_ref if action.action.kind in {"trace", "move"} else None,
        "relation_ref": action.action.relation_ref if action.action.kind == "show_relation" else None,
    }


def _play(scene, animation, run_time: float, kind: str, *, target_refs=(), target=None, targets=(), role=None, events=()) -> None:
    animation._semantic_kind = kind
    animation._semantic_target_refs = target_refs
    animation._semantic_target = target
    animation._semantic_targets = targets
    animation._semantic_role = role
    animation._semantic_events = events
    scene.play(animation, run_time=run_time)
