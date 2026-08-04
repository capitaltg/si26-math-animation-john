from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from manim import (
    AnimationGroup,
    Arrow,
    Circle,
    Create,
    Dot,
    FadeIn,
    Line,
    Rectangle,
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


@dataclass(frozen=True)
class RenderedScene:
    visuals: dict[str, object]
    targets: dict[tuple[str, str | None, int | None], object]
    relations: dict[str, object]
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

    if "values" in payload:
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
    elif "markers" in payload:
        root, children = _line_visual(bounds, measured, placed.offset, "marker")
        root.add(*_number_line_labels(measured, placed))
    elif {"rows", "columns"} <= payload.keys():
        root, children = _parts_as_rectangles(measured, placed.offset, "cell")
    elif {"whole", "parts"} <= payload.keys():
        root = Circle(radius=(bounds.right - bounds.left) / 2).move_to(_array(bounds.center))
        children = _parts_as_dots(measured, placed.offset, "partition")
        root.add(*children.values())
    elif "boxes" in payload:
        root, children = _build_unit_tape(measured, placed, palette)
    elif {"value", "maximum"} <= payload.keys():
        root, children = _parts_as_rectangles(measured, placed.offset, "segment")
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


def _line_visual(bounds: Bounds, measured, offset: Point, part_name: str):
    root = Line(_array(Point(bounds.left, bounds.center.y)), _array(Point(bounds.right, bounds.center.y)))
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
    y = payload["label_center_y"] + placed.offset.y
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
            if part == "source_label":
                root.add(text)
    for part in ("source_label", "target_label"):
        children[(part, None)] = VGroup(*(
            children[(part, index)] for index in range(len(payload["boxes"]))
        ))
    return root, children


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
    raise ValueError(f"unsupported resolved action {kind}")


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
