from collections import defaultdict
from dataclasses import dataclass
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
    for placed in scene.visuals:
        root, children = _build_visual(placed, palette)
        visuals[placed.measured.ref] = root
        targets[(placed.measured.ref, None, None)] = root
        targets.update({(placed.measured.ref, part, index): child for (part, index), child in children.items()})
        role = _initial_role(placed.measured.ref, placed.measured.payload)
        roles[(placed.measured.ref, None, None)] = role
        roles.update({(placed.measured.ref, part, index): role for part, index in children})
    relations = {relation.ref: _build_relation(relation, palette) for relation in scene.relations}
    return RenderedScene(visuals=visuals, targets=targets, relations=relations, roles=roles)


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
            ("item", index): _text(value, "math_value", _center(part.bounds, placed.offset))
            for (part_name, index), part in measured.parts.items()
            if part_name == "item"
            for value in (payload["values"][index],)
        }
        root = VGroup(*children.values())
    elif {"length", "width", "unit"} <= payload.keys():
        root = Rectangle(width=bounds.right - bounds.left, height=bounds.top - bounds.bottom)
        root.move_to(_array(bounds.center))
        children = {
            (part, index): _line_for_bounds(_translated(part_value.bounds, placed.offset))
            for (part, index), part_value in measured.parts.items()
            if part == "edge"
        }
        root.add(*children.values())
    elif "text" in payload:
        root, children = _text(payload["text"], "label", bounds.center), {}
    elif "markers" in payload:
        root, children = _line_visual(bounds, measured, placed.offset, "marker")
    elif {"rows", "columns"} <= payload.keys():
        root, children = _parts_as_rectangles(measured, placed.offset, "cell")
    elif {"whole", "parts"} <= payload.keys():
        root = Circle(radius=(bounds.right - bounds.left) / 2).move_to(_array(bounds.center))
        children = _parts_as_dots(measured, placed.offset, "partition")
        root.add(*children.values())
    elif {"value", "maximum"} <= payload.keys():
        root, children = _parts_as_rectangles(measured, placed.offset, "segment")
    elif "count" in payload:
        root, children = _parts_as_dots(measured, placed.offset, "item")
    else:
        raise ValueError(f"unsupported resolved visual {measured.ref}")

    _apply_style(root, style)
    return root, children


def _initial_role(ref: str, payload) -> str:
    if ref == "evaluated_answer" or "values" in payload or "text" in payload:
        return "neutral"
    return "structure"


def _text(text: str, font_role: str, center: Point):
    mobject = Text(text, font_size=FONT_SIZES[font_role])
    mobject.move_to(_array(center))
    return mobject


def _line_visual(bounds: Bounds, measured, offset: Point, part_name: str):
    root = Line(_array(Point(bounds.left, bounds.center.y)), _array(Point(bounds.right, bounds.center.y)))
    children = _parts_as_dots(measured, offset, part_name)
    root_group = VGroup(root, *children.values())
    return root_group, children


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


def _rectangle_for_bounds(bounds: Bounds):
    rectangle = Rectangle(width=max(bounds.right - bounds.left, 0.02), height=max(bounds.top - bounds.bottom, 0.02))
    rectangle.move_to(_array(bounds.center))
    return rectangle


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
    animations = []
    for action in actions:
        if action.action.kind == "set_role":
            style = resolve_semantic_style(palette, action.action.role)
            target_keys = tuple(_target_tuple(target.ref) for target in action.targets)
            animations.extend(build_role_transition(_target_mobject(rendered, target.ref), style) for target in action.targets)
            rendered.roles.update({target_key: action.action.role for target_key in target_keys})
        elif action.action.kind == "reveal" and action.action.mode == "together":
            animations.extend(motion(_target_mobject(rendered, target.ref)) for target in action.targets)
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
    raise ValueError(f"unsupported resolved action {kind}")


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
