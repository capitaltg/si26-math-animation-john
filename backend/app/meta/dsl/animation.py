import re
from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.limits import (
    MAX_ANIMATION_DEPTH,
    MAX_ANIMATION_NODES,
    MAX_ANIMATION_STEPS,
    MAX_LABEL_TEXT_LENGTH,
    MAX_TOTAL_DURATION_SECONDS,
)

StyleToken = Literal["primary", "secondary", "accent", "muted", "success", "warning"]


class _AnimationNodeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class RowNode(_AnimationNodeBase):
    kind: Literal["row"] = "row"
    children: list["AnimationNode"] = Field(min_length=1, max_length=8)
    gap: float = Field(default=0.25, ge=0, le=2)


class ColumnNode(_AnimationNodeBase):
    kind: Literal["column"] = "column"
    children: list["AnimationNode"] = Field(min_length=1, max_length=8)
    gap: float = Field(default=0.25, ge=0, le=2)


class OverlayNode(_AnimationNodeBase):
    kind: Literal["overlay"] = "overlay"
    children: list["AnimationNode"] = Field(min_length=1, max_length=8)


class AlignNode(_AnimationNodeBase):
    kind: Literal["align"] = "align"
    child: "AnimationNode"
    edge: Literal["left", "right", "top", "bottom", "center"]


class PaddingNode(_AnimationNodeBase):
    kind: Literal["padding"] = "padding"
    child: "AnimationNode"
    amount: float = Field(default=0.25, ge=0, le=2)


class SequenceNode(_AnimationNodeBase):
    kind: Literal["sequence"] = "sequence"
    steps: list["AnimationNode"] = Field(min_length=1, max_length=40)
    # Parsed and bounded, but intentionally NOT read at runtime: dynamic_scene.py's
    # `sequence` branch does not route through build_sequence (see its NOTE), so no
    # per-step wait is injected. Kept in the schema for forward-compatibility.
    step_duration: float = Field(default=1.0, gt=0, le=5)


class ParallelNode(_AnimationNodeBase):
    kind: Literal["parallel"] = "parallel"
    steps: list["AnimationNode"] = Field(min_length=1, max_length=8)


class NumberLineNode(_AnimationNodeBase):
    kind: Literal["number_line"] = "number_line"
    minimum: ExpressionNode
    maximum: ExpressionNode
    marker_value: ExpressionNode
    style: StyleToken = "primary"


class GridNode(_AnimationNodeBase):
    kind: Literal["grid"] = "grid"
    rows: ExpressionNode
    cols: ExpressionNode
    style: StyleToken = "primary"


class BarNode(_AnimationNodeBase):
    kind: Literal["bar"] = "bar"
    filled: ExpressionNode
    total: ExpressionNode
    style: StyleToken = "primary"


class ObjectSetNode(_AnimationNodeBase):
    kind: Literal["object_set"] = "object_set"
    count: ExpressionNode
    style: StyleToken = "primary"


class ShapePartitionNode(_AnimationNodeBase):
    kind: Literal["shape_partition"] = "shape_partition"
    parts: ExpressionNode
    shaded: ExpressionNode
    style: StyleToken = "primary"


class ArrowNode(_AnimationNodeBase):
    kind: Literal["arrow"] = "arrow"
    from_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    to_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    style: StyleToken = "accent"


class BraceNode(_AnimationNodeBase):
    kind: Literal["brace"] = "brace"
    target_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    text: str = Field(max_length=MAX_LABEL_TEXT_LENGTH)
    style: StyleToken = "muted"


class TallyMarksNode(_AnimationNodeBase):
    kind: Literal["tally_marks"] = "tally_marks"
    count: ExpressionNode
    style: StyleToken = "primary"


class LabelNode(_AnimationNodeBase):
    kind: Literal["label"] = "label"
    text: str = Field(max_length=MAX_LABEL_TEXT_LENGTH)
    style: StyleToken = "primary"


class ExpressionLabelNode(_AnimationNodeBase):
    kind: Literal["expression_label"] = "expression_label"
    expression: ExpressionNode
    prefix: str = Field(default="", max_length=MAX_LABEL_TEXT_LENGTH)
    suffix: str = Field(default="", max_length=MAX_LABEL_TEXT_LENGTH)
    role: Literal["working", "answer"] = "working"
    style: StyleToken = "primary"


class RectangleNode(_AnimationNodeBase):
    kind: Literal["rectangle"] = "rectangle"
    length: ExpressionNode
    width: ExpressionNode
    unit: str = Field(default="", max_length=MAX_LABEL_TEXT_LENGTH)
    style: StyleToken = "primary"


class AppearNode(_AnimationNodeBase):
    kind: Literal["appear"] = "appear"
    target_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class HighlightNode(_AnimationNodeBase):
    kind: Literal["highlight"] = "highlight"
    target_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class TransformNode(_AnimationNodeBase):
    kind: Literal["transform"] = "transform"
    from_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    to_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class MoveAlongPathNode(_AnimationNodeBase):
    kind: Literal["move_along_path"] = "move_along_path"
    target_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class CameraFocusNode(_AnimationNodeBase):
    kind: Literal["camera_focus"] = "camera_focus"
    target_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class WaitNode(_AnimationNodeBase):
    kind: Literal["wait"] = "wait"
    seconds: float = Field(gt=0, le=5)


AnimationNode = Annotated[
    Union[
        RowNode, ColumnNode, OverlayNode, AlignNode, PaddingNode, SequenceNode, ParallelNode,
        NumberLineNode, GridNode, BarNode, ObjectSetNode, ShapePartitionNode, ArrowNode,
        BraceNode, TallyMarksNode, LabelNode, ExpressionLabelNode, RectangleNode,
        AppearNode, HighlightNode, TransformNode, MoveAlongPathNode, CameraFocusNode, WaitNode,
    ],
    Field(discriminator="kind"),
]

for _cls in (RowNode, ColumnNode, OverlayNode, AlignNode, PaddingNode, SequenceNode, ParallelNode):
    _cls.model_rebuild()


class AnimationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    animation_version: Literal[1, 2] = 1
    root: AnimationNode


_CONTAINER_KINDS = {"row", "column", "overlay", "sequence", "parallel"}
_SINGLE_CHILD_KINDS = {"align", "padding"}
_VISUAL_EXPRESSION_FIELDS = {
    "number_line": ("minimum", "maximum", "marker_value"),
    "grid": ("rows", "cols"),
    "bar": ("filled", "total"),
    "object_set": ("count",),
    "shape_partition": ("parts", "shaded"),
    "tally_marks": ("count",),
    "expression_label": ("expression",),
    "rectangle": ("length", "width"),
}
_REF_FIELDS = ("target_ref", "from_ref", "to_ref", "path_ref")
_TIMED_ACTION_KINDS = {"appear", "highlight", "transform", "move_along_path", "camera_focus"}
_BATCHABLE_TIMED_ACTION_KINDS = _TIMED_ACTION_KINDS - {"camera_focus"}
_LAYOUT_KINDS = {"row", "column", "overlay", "align", "padding"}
# Node kinds whose render_animation_node branch produces a mobject and stores it in
# mobjects[ref]. Only refs on these kinds can be resolved at render time; a *_ref that
# points at any other kind (timed-action/control, which return None) would KeyError.
_PRODUCING_KINDS = {
    "row", "column", "overlay", "align", "padding",
    "number_line", "grid", "bar", "object_set", "shape_partition",
    "arrow", "brace", "tally_marks", "label", "expression_label", "rectangle",
}


@dataclass(frozen=True)
class CompiledAnimation:
    document: AnimationDocument
    refs: frozenset[str]
    total_duration_seconds: float
    answer_expressions: tuple[ExpressionNode, ...] = ()


def _children_of(node) -> list:
    if node.kind in _CONTAINER_KINDS:
        return node.children if hasattr(node, "children") else list(node.steps)
    if node.kind in _SINGLE_CHILD_KINDS:
        return [node.child]
    return []


def _contains_field_placeholder(text: str, known_fields: frozenset[str]) -> bool:
    for fragment in re.findall(r"\{([^{}]+)\}", text):
        if any(re.search(rf"\b{re.escape(field)}\b", fragment) for field in known_fields):
            return True
    return False


def compile_animation_document(document: AnimationDocument, known_fields: frozenset[str]) -> CompiledAnimation:
    declared_refs: set[str] = set()
    producing_refs: set[str] = set()
    referenced_refs: set[str] = set()
    appeared_refs: set[str] = set()
    layout_ancestors_by_ref: dict[str, frozenset[int]] = {}
    node_count = 0
    duration = 0.0
    answer_expressions: list[ExpressionNode] = []

    def walk(node, depth: int, layout_ancestors: tuple[int, ...] = ()) -> None:
        nonlocal node_count, duration
        node_count += 1
        node_id = node_count
        current_layout_ancestors = layout_ancestors
        if node.kind in _LAYOUT_KINDS:
            current_layout_ancestors = (*layout_ancestors, node_id)
        if node_count > MAX_ANIMATION_NODES:
            raise DslValidationError("too_many_nodes", f"max {MAX_ANIMATION_NODES} exceeded")
        if depth > MAX_ANIMATION_DEPTH:
            raise DslValidationError("animation_too_deep", f"max depth {MAX_ANIMATION_DEPTH} exceeded")
        if document.animation_version == 1 and node.kind in {"expression_label", "rectangle"}:
            raise DslValidationError("unsupported_node_for_version", node.kind)

        if node.ref is not None:
            if node.ref in declared_refs:
                raise DslValidationError("duplicate_ref", node.ref)
            declared_refs.add(node.ref)
            if node.kind in _PRODUCING_KINDS:
                producing_refs.add(node.ref)
                layout_ancestors_by_ref[node.ref] = frozenset(current_layout_ancestors)

        for field_name in _REF_FIELDS:
            if hasattr(node, field_name):
                referenced_refs.add(getattr(node, field_name))

        if node.kind == "appear":
            appeared_refs.add(node.target_ref)

        for field_name in _VISUAL_EXPRESSION_FIELDS.get(node.kind, ()):
            compile_expression(getattr(node, field_name), known_fields)

        if document.animation_version == 2:
            static_text = ()
            if node.kind == "label":
                static_text = (node.text,)
            elif node.kind == "expression_label":
                static_text = (node.prefix, node.suffix)
                if node.role == "answer":
                    answer_expressions.append(node.expression)
            if any(_contains_field_placeholder(text, known_fields) for text in static_text):
                raise DslValidationError(
                    "unsupported_text_placeholder",
                    "static text cannot interpolate fields; use expression_label",
                )

        if node.kind == "wait":
            duration += node.seconds
        elif node.kind in _TIMED_ACTION_KINDS:
            duration += 1.0

        children = _children_of(node)
        if node.kind in ("sequence", "parallel") and len(children) > MAX_ANIMATION_STEPS:
            raise DslValidationError("too_many_steps", f"max {MAX_ANIMATION_STEPS} exceeded")
        if node.kind in _LAYOUT_KINDS:
            for child in children:
                if child.kind not in _PRODUCING_KINDS:
                    raise DslValidationError(
                        "invalid_layout_child",
                        f"{node.kind} child kind '{child.kind}' does not produce a mobject",
                    )
        if node.kind == "parallel":
            # render_animation_node's `parallel` branch feeds every direct step's
            # return value into one scene.play(*animations) via build_parallel.
            # Only timed actions return an Animation without playing immediately.
            for step in children:
                if step.kind not in _BATCHABLE_TIMED_ACTION_KINDS:
                    raise DslValidationError(
                        "invalid_parallel_step",
                        f"step kind '{step.kind}' does not return a batchable Animation",
                    )
        for child in children:
            walk(child, depth + 1, current_layout_ancestors)

    walk(document.root, 0)

    # A *_ref is dangling if it names no declared ref at all, OR names a ref declared
    # on a non-producing node (timed-action/control) that will never populate
    # mobjects[ref] at render time. Both are the same failure: the ref won't resolve.
    # KNOWN GAP (deferred, not fixed here): this check is order-independent set
    # subtraction, so it does NOT enforce declare-before-reference ordering. A
    # forward ref (e.g. RowNode(children=[ArrowNode(from_ref="a", to_ref="b"),
    # LabelNode(ref="a"), LabelNode(ref="b")])) compiles successfully today but
    # still crashes at render with KeyError, because render_animation_node
    # populates mobjects[] in depth-first traversal order and the ArrowNode is
    # visited before the LabelNodes that would populate mobjects["a"]/["b"].
    dangling = referenced_refs - producing_refs
    if dangling:
        raise DslValidationError("dangling_ref", ", ".join(sorted(dangling)))

    if len(appeared_refs) > 1:
        shared_layouts = set.intersection(
            *(set(layout_ancestors_by_ref[ref]) for ref in appeared_refs)
        )
        if not shared_layouts:
            refs = ", ".join(sorted(appeared_refs))
            raise DslValidationError(
                "missing_shared_layout",
                f"appeared visuals require a common row/column/layout ancestor: {refs}",
            )

    if duration > MAX_TOTAL_DURATION_SECONDS:
        raise DslValidationError(
            "total_duration_exceeded", f"{duration}s exceeds {MAX_TOTAL_DURATION_SECONDS}s"
        )

    return CompiledAnimation(
        document=document,
        refs=frozenset(declared_refs),
        total_duration_seconds=duration,
        answer_expressions=tuple(answer_expressions),
    )
