import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.meta.manim_primitives.style import resolve_semantic_style
from app.meta.v3.errors import V3ValidationError
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dynamic_scene import DynamicTemplateScene
from app.meta.v3.layout import SAFE_FRAME
from app.meta.v3.manim_measurer import ManimTextMeasurer
from app.meta.v3.quality import DIMENSION_TARGET_PARTS
from app.meta.v3.renderer import render_resolved_scene
from app.meta.v3.resolver import resolve_scene

VALID_MODES = {"full", "thumbnail", "probe"}


def main() -> None:
    program_path, known_fields_path, values_path, output_path_str, mode, scratch_dir_str = sys.argv[1:7]
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown render mode {mode!r}; expected one of {sorted(VALID_MODES)}")

    if mode == "probe":
        try:
            _render_probe(
                Path(program_path), Path(known_fields_path), Path(values_path),
                Path(output_path_str), Path(scratch_dir_str),
            )
        except V3ValidationError as exc:
            # A structured rejection (`below_minimum_text_scale`, an unresolvable
            # target ...) is actionable evidence with its own code and hint. Left
            # to propagate it becomes a nonzero exit and nothing more, which the
            # parent can only report as `render_probe_failed` / "regenerate the
            # candidate". Hand the failure across the process boundary so it
            # survives intact; the traceback still goes to stderr for the log.
            Path(output_path_str).with_suffix(".failure.json").write_text(
                json.dumps(asdict(exc.failure))
            )
            raise
        return

    del known_fields_path  # The stored scene program is already compiled against its field contract.
    scene_program = SceneProgramDocument.model_validate_json(Path(program_path).read_text())
    field_values = json.loads(Path(values_path).read_text())

    from manim import tempconfig

    output_path = Path(output_path_str)
    overrides = {
        "media_dir": scratch_dir_str,
        "output_file": output_path.stem,
        "disable_caching": True,
    }
    if mode == "thumbnail":
        overrides["save_last_frame"] = True
        overrides["quality"] = "low_quality"
    else:
        overrides["quality"] = "medium_quality"

    with tempconfig(overrides):
        scene = DynamicTemplateScene()
        scene.scene_program = scene_program
        scene.field_values = field_values
        scene.render()

    ext = "png" if mode == "thumbnail" else "mp4"
    destination = output_path.resolve()
    matches = [
        path
        for path in Path(scratch_dir_str).rglob(f"{output_path.stem}.{ext}")
        if path.resolve() != destination
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly 1 {ext} file for {output_path.stem}, found {len(matches)}: {matches}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    matches[0].replace(output_path)


def _render_probe(
    program_path: Path,
    known_fields_path: Path,
    values_path: Path,
    output_path: Path,
    scratch_dir: Path,
) -> None:
    """Render a v3 program and write frame/geometry evidence for the parent process."""
    del known_fields_path  # The typed program is already compiled against its field contract.
    program = SceneProgramDocument.model_validate_json(program_path.read_text())
    values = json.loads(values_path.read_text())
    resolved = resolve_scene(program, values, ManimTextMeasurer())

    from manim import Scene, config, tempconfig

    class ProbeScene(Scene):
        def __init__(self):
            super().__init__()
            self.elapsed = 0.0
            self.frames = []
            self.captured_beats = set()
            self.rendered = None
            self.render_events = []
            self.final_answer_visible = False
            self.beat_end_times = {
                beat_id: max(
                    action.at_seconds + action.duration_seconds
                    for action in resolved.timeline if action.beat_id == beat_id
                )
                for beat_id in {action.beat_id for action in resolved.timeline}
            }

        def play(self, *animations, **kwargs):
            duration = kwargs.get("run_time", 0.0)
            result = super().play(*animations, **kwargs)
            self.elapsed += duration
            self.render_events.extend(
                self._observe_render_event(event)
                for event in getattr(animations[0], "_semantic_events", ())
            )
            self._capture_completed_beats()
            return result

        def wait(self, duration=1, *args, **kwargs):
            result = super().wait(duration, *args, **kwargs)
            self.elapsed += duration
            self._capture_completed_beats()
            return result

        def construct(self):
            self.rendered = render_resolved_scene(self, resolved)
            answer = self.rendered.visuals.get("evaluated_answer")
            self.final_answer_visible = answer is not None and _mobject_is_visible(self, answer)
            self._capture_completed_beats(force=True)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.camera.get_image().save(output_path)

        def set_rendered_scene(self, rendered):
            self.rendered = rendered

        def _observe_render_event(self, event):
            observed = {**event, "seconds": self.elapsed}
            if event["kind"] == "reveal":
                observed["visible_targets"] = tuple(
                    target for target in event["targets"]
                    if _mobject_is_visible(self, self.rendered.targets[target])
                )
            if event["kind"] == "set_role":
                expected = resolve_semantic_style(resolved.style_recipe.palette, event["role"])["color"]
                observed["state_applied"] = all(
                    _mobject_has_color(self.rendered.targets[target], expected)
                    for target in event["targets"]
                )
            return observed

        def _capture_completed_beats(self, force=False):
            for beat_id, end_seconds in sorted(self.beat_end_times.items(), key=lambda item: item[1]):
                if beat_id in self.captured_beats or (not force and end_seconds > self.elapsed + 1e-6):
                    continue
                path = f"probe-{len(self.frames)}.png"
                self.camera.get_image().save(scratch_dir / path)
                self.frames.append({"beat_id": beat_id, "seconds": end_seconds, "path": path})
                self.captured_beats.add(beat_id)


    overrides = {
        "media_dir": str(scratch_dir),
        "disable_caching": True,
        "quality": "low_quality",
        "write_to_movie": False,
    }
    with tempconfig(overrides):
        scene = ProbeScene()
        scene.render()
        manifest = _probe_manifest(scene, resolved, program, config.pixel_width, config.pixel_height)
    output_path.with_suffix(".json").write_text(json.dumps(manifest))


def _probe_manifest(scene, resolved, program, width, height) -> dict:
    relation_specs = {relation.ref: relation for relation in program.relations}
    visual_bounds = {
        ref: _pixel_mobject_bounds(mobject, width, height)
        for ref, mobject in scene.rendered.visuals.items()
    }
    anchors = {}
    relations = {}
    observed_relation_refs = {
        event["relation_ref"] for event in scene.render_events
        if event["kind"] == "show_relation" and event["relation_ref"] is not None
    }
    for relation in resolved.relations:
        if relation.ref not in observed_relation_refs:
            continue
        target_anchor = _target_label(relation_specs[relation.ref].target)
        target_mobject = _rendered_target_mobject(scene, relation_specs[relation.ref].target)
        target = _pixel_array_point(_mobject_anchor(target_mobject, relation_specs[relation.ref].target.anchor), width, height)
        anchors[target_anchor] = target
        mobject = scene.rendered.relations[relation.ref]
        arrow = mobject.submobjects[0]
        relations[relation.ref] = {
            "target_anchor": target_anchor,
            "target": target,
            "tip": _pixel_array_point(arrow.get_end(), width, height),
            "bounds": _pixel_mobject_bounds(mobject, width, height),
        }

    path_events = [event["path_ref"] for event in scene.render_events if event["path_ref"] is not None]
    state_events = _state_events(scene.render_events, resolved)
    dimensions = {
        # bool(...): the coordinates flowing into `_point_distance` originate
        # from manim/numpy mobject geometry, so the comparison can yield a
        # numpy.bool_ instead of a native bool -- not JSON-serializable. This
        # dict comprehension was previously always empty (no compiled ref
        # ever matched the old "dimension" substring filter), so the
        # coercion was never exercised until real dimension relations
        # started flowing through it.
        relation.ref: {"passed": bool(_point_distance(relation_data["target"], relation_data["tip"], width, height) <= 0.02)}
        for relation in program.relations if relation.target.part in DIMENSION_TARGET_PARTS
        for relation_data in [relations.get(relation.ref, {})]
        if relation_data
    }
    conclusion_starts = [action.at_seconds for action in resolved.timeline if action.beat_id == _last_beat_id(resolved)]
    return {
        "frame_size": [width, height],
        # The box `place_vertical_lesson` lays out into, in the same pixel
        # coordinates as `visual_bounds`, so `render_probe.check_frame_bounds`
        # can hold the render to the frame layout actually targeted rather than
        # to the wider physical frame.
        "safe_frame": _pixel_bounds(SAFE_FRAME, width, height),
        "total_duration_seconds": resolved.total_duration_seconds,
        "conclusion_hold_seconds": resolved.total_duration_seconds - min(conclusion_starts),
        "simple_reveal_mode": _simple_reveal_mode(resolved),
        "frames": scene.frames,
        "visual_bounds": visual_bounds,
        "anchors": anchors,
        "relations": relations,
        "declared_relations": [relation.ref for relation in program.relations],
        "path_events": path_events,
        "declared_path_events": [
            action.action.path_ref for action in resolved.timeline if action.action.kind in {"trace", "move"}
        ],
        "dimension_anchor_checks": dimensions,
        "declared_dimension_anchors": [
            relation.ref for relation in program.relations
            if relation.target.part in DIMENSION_TARGET_PARTS
        ],
        # Evidence that each measured visual actually put its measurements on
        # screen. Read off the rendered mobjects, so it reports what the frame
        # shows rather than what the program intended.
        "dimension_labels": _dimension_labels(scene, program),
        "declared_dimension_labels": [
            visual.ref for visual in program.visuals
            if visual.kind == "rectangle_measurement"
        ],
        "state_events": state_events,
        "declared_state_events": _declared_state_events(resolved),
        "final_answer_visible": scene.final_answer_visible,
        "derivation_visible": bool(path_events) or any(event["role"] == "focus" for event in state_events),
    }


def _state_events(render_events, resolved) -> list[dict]:
    events = []
    for event in render_events:
        if event["kind"] == "reveal":
            for visual_ref, part, index in event["targets"]:
                if (visual_ref, part, index) not in event["visible_targets"]:
                    continue
                visual = resolved.visual(visual_ref)
                if part is None:
                    events.extend({
                        "seconds": event["seconds"],
                        "target": f"{visual_ref}.{part_name}[{part_index}]",
                        "role": "neutral",
                    } for part_name, part_index in visual.measured.parts if part_name == "item")
        elif event["kind"] == "set_role" and event["state_applied"]:
            for target in event["targets"]:
                events.append({
                    "seconds": event["seconds"],
                    "target": _target_label_from_key(target),
                    "role": event["role"],
                })
    return events


def _declared_state_events(resolved) -> list[dict]:
    declared = []
    for action in resolved.timeline:
        if action.action.kind == "reveal":
            for target in action.targets:
                visual = resolved.visual(target.ref.visual_ref)
                if target.ref.part is None:
                    declared.extend({"target": f"{target.ref.visual_ref}.{part}[{index}]", "role": "neutral"}
                                    for part, index in visual.measured.parts if part == "item")
        elif action.action.kind == "set_role" and action.action.role == "focus":
            declared.extend({"target": _target_label(target.ref), "role": action.action.role} for target in action.targets)
    return declared


def _simple_reveal_mode(resolved) -> str | None:
    for action in resolved.timeline:
        if action.action.kind == "reveal" and any(
            resolved.visual(target.ref.visual_ref).measured.payload.get("values") is not None
            for target in action.targets
        ):
            return action.action.mode
    return None


def _last_beat_id(resolved) -> str:
    return max(resolved.timeline, key=lambda action: action.at_seconds + action.duration_seconds).beat_id


def _target_label(target) -> str:
    if target.part is None:
        return target.visual_ref
    suffix = f".{target.part}[{target.index}]"
    return f"{target.visual_ref}{suffix}" + (f".{target.anchor}" if hasattr(target, "anchor") else "")


def _target_label_from_key(target) -> str:
    visual_ref, part, index = target
    return visual_ref if part is None else f"{visual_ref}.{part}[{index}]"


def _mobject_is_visible(scene, mobject) -> bool:
    return any(member is mobject for root in scene.mobjects for member in root.get_family())


def _mobject_has_color(mobject, expected) -> bool:
    expected_hex = expected.to_hex()
    return any(member.get_color().to_hex() == expected_hex for member in mobject.get_family())


def _rendered_target_mobject(scene, target):
    """Look up the actually-rendered mobject a relation's typed target anchors
    to. Every semantic part the compiler accepts as a target -- including a
    rectangle's `length_edge`/`width_edge` aliases -- is registered in
    `scene.rendered.targets` by `app/meta/v3/renderer.py`, so this is a direct
    lookup on renderer-OBSERVED state: a missing key means the renderer and the
    compiler disagree about what is targetable, which must fail loudly rather
    than be reconstructed from program data.
    """
    return scene.rendered.targets[(target.visual_ref, target.part, target.index)]


def _mobject_anchor(mobject, anchor):
    return {
        "center": mobject.get_center(),
        "top": mobject.get_top(),
        "bottom": mobject.get_bottom(),
        "left": mobject.get_left(),
        "right": mobject.get_right(),
    }[anchor]


def _dimension_labels(scene, program) -> dict:
    labels = {}
    for visual in program.visuals:
        if visual.kind != "rectangle_measurement":
            continue
        rendered = {}
        for part in ("length_label", "width_label"):
            mobject = scene.rendered.targets.get((visual.ref, part, 0))
            if mobject is not None:
                # `original_text` is the string handed to manim; `.text` is
                # manim's normalised form, which drops the space in "8 cm".
                rendered[part] = getattr(mobject, "original_text", "")
        labels[visual.ref] = rendered
    return labels


def _pixel_bounds(bounds, width, height) -> list[float]:
    return [
        _pixel_x(bounds.left, width), _pixel_y(bounds.top, height),
        _pixel_x(bounds.right, width), _pixel_y(bounds.bottom, height),
    ]


def _pixel_mobject_bounds(mobject, width, height) -> list[float]:
    return [
        _pixel_x(mobject.get_left()[0], width), _pixel_y(mobject.get_top()[1], height),
        _pixel_x(mobject.get_right()[0], width), _pixel_y(mobject.get_bottom()[1], height),
    ]


def _pixel_point(point, width, height) -> list[float]:
    return [_pixel_x(point.x, width), _pixel_y(point.y, height)]


def _pixel_array_point(point, width, height) -> list[float]:
    return [_pixel_x(point[0], width), _pixel_y(point[1], height)]


def _pixel_x(x, width) -> float:
    from manim import config

    return (x + config.frame_width / 2) * width / config.frame_width


def _pixel_y(y, height) -> float:
    from manim import config

    return (config.frame_height / 2 - y) * height / config.frame_height


def _point_distance(first, second, width, height) -> float:
    return (((first[0] - second[0]) / width) ** 2 + ((first[1] - second[1]) / height) ** 2) ** 0.5


if __name__ == "__main__":
    main()
