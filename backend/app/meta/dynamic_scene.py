from manim import MovingCameraScene

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import _evaluate
from app.meta.manim_primitives.layout import (
    build_align,
    build_column,
    build_overlay,
    build_padding,
    build_parallel,
    build_row,
)
from app.meta.manim_primitives.motions import (
    build_appear,
    build_camera_focus,
    build_highlight,
    build_move_along_path,
    build_transform,
    build_wait,
)
from app.meta.manim_primitives.visuals import (
    build_arrow,
    build_bar,
    build_brace,
    build_grid,
    build_label,
    build_number_line,
    build_object_set,
    build_shape_partition,
    build_tally_marks,
)

_VISUAL_EXPRESSION_FIELDS = {
    "number_line": ("minimum", "maximum", "marker_value"),
    "grid": ("rows", "cols"),
    "bar": ("filled", "total"),
    "object_set": ("count",),
    "shape_partition": ("parts", "shaded"),
    "tally_marks": ("count",),
}


def _resolve(node, field_name: str, values: dict) -> int:
    value = _evaluate(getattr(node, field_name), values)
    # Visual builders take integer counts/bounds; an expression that evaluates to
    # a non-whole Fraction (e.g. 9/2) would be silently truncated by int(). Reject
    # it explicitly rather than render something the author never expressed.
    if value.denominator != 1:
        raise DslValidationError(
            "non_integer_value", f"{field_name} evaluated to {value}, which is not a whole number"
        )
    return int(value)


def render_animation_node(scene, node, values: dict, mobjects: dict, collect_animation: bool = False):
    # collect_animation: when True (set by the `parallel` branch for its steps),
    # timed-action branches RETURN their Animation instead of calling scene.play,
    # so the caller can batch them into a single scene.play(*animations) call.
    kind = node.kind

    if kind == "row":
        result = build_row([render_animation_node(scene, child, values, mobjects) for child in node.children], gap=node.gap)
    elif kind == "column":
        result = build_column([render_animation_node(scene, child, values, mobjects) for child in node.children], gap=node.gap)
    elif kind == "overlay":
        result = build_overlay([render_animation_node(scene, child, values, mobjects) for child in node.children])
    elif kind == "align":
        result = build_align(render_animation_node(scene, node.child, values, mobjects), node.edge)
    elif kind == "padding":
        result = build_padding(render_animation_node(scene, node.child, values, mobjects), node.amount)
    elif kind == "sequence":
        # NOTE: intentionally NOT routed through build_sequence. build_sequence
        # injects scene.wait(step_duration) after every step, but the Task 8
        # compiler's total_duration_seconds never counts step_duration (it counts
        # only WaitNode.seconds and 1.0 per timed action). Using build_sequence
        # would let a validated animation run past its certified duration bound —
        # a resource-gate violation. Steps run one-after-another in source order;
        # timing comes from explicit WaitNodes and the intrinsic time of play().
        for step in node.steps:
            render_animation_node(scene, step, values, mobjects)
        result = None
    elif kind == "parallel":
        # Each step is rendered with collect_animation=True so timed actions RETURN
        # their Animation; build_parallel gathers the non-None results and fires them
        # in one scene.play(*animations) call, so they genuinely run together.
        build_parallel(
            scene,
            [
                lambda step=step: render_animation_node(
                    scene, step, values, mobjects, collect_animation=True
                )
                for step in node.steps
            ],
        )
        result = None
    elif kind == "number_line":
        result = build_number_line(
            _resolve(node, "minimum", values), _resolve(node, "maximum", values),
            _resolve(node, "marker_value", values), style=node.style,
        )
    elif kind == "grid":
        result = build_grid(_resolve(node, "rows", values), _resolve(node, "cols", values), style=node.style)
    elif kind == "bar":
        result = build_bar(_resolve(node, "filled", values), _resolve(node, "total", values), style=node.style)
    elif kind == "object_set":
        result = build_object_set(_resolve(node, "count", values), style=node.style)
    elif kind == "shape_partition":
        result = build_shape_partition(
            _resolve(node, "parts", values), _resolve(node, "shaded", values), style=node.style
        )
    elif kind == "arrow":
        result = build_arrow(mobjects[node.from_ref], mobjects[node.to_ref], style=node.style)
    elif kind == "brace":
        result = build_brace(mobjects[node.target_ref], node.text, style=node.style)
    elif kind == "tally_marks":
        result = build_tally_marks(_resolve(node, "count", values), style=node.style)
    elif kind == "label":
        result = build_label(node.text, style=node.style)
    elif kind == "appear":
        animation = build_appear(mobjects[node.target_ref])
        if collect_animation:
            return animation
        scene.play(animation)
        result = None
    elif kind == "highlight":
        animation = build_highlight(mobjects[node.target_ref])
        if collect_animation:
            return animation
        scene.play(animation)
        result = None
    elif kind == "transform":
        animation = build_transform(mobjects[node.from_ref], mobjects[node.to_ref])
        if collect_animation:
            return animation
        scene.play(animation)
        result = None
    elif kind == "move_along_path":
        animation = build_move_along_path(mobjects[node.target_ref], mobjects[node.path_ref])
        if collect_animation:
            return animation
        scene.play(animation)
        result = None
    elif kind == "camera_focus":
        # camera_focus is a scene-level operation, not a per-mobject Animation:
        # build_camera_focus drives scene.camera.frame via its own scene.play. It
        # cannot be batched into a sibling scene.play(*animations), so even inside a
        # parallel block it self-plays (returning None, which build_parallel skips).
        build_camera_focus(scene, mobjects[node.target_ref])
        result = None
    elif kind == "wait":
        build_wait(scene, node.seconds)
        result = None
    else:
        raise ValueError(f"unknown animation node kind: {kind}")

    if node.ref is not None and result is not None:
        mobjects[node.ref] = result
    return result


class DynamicTemplateScene(MovingCameraScene):
    compiled_animation = None
    field_values = None
    params = None

    def construct(self):
        if self.field_values is None and self.params is not None:
            self.field_values = self.params.model_dump()
        if self.compiled_animation is None or self.field_values is None:
            raise ValueError(
                "DynamicTemplateScene.compiled_animation and .field_values must be set before construct() runs"
            )
        render_animation_node(self, self.compiled_animation.document.root, self.field_values, {})
