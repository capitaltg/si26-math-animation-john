from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.limits import MAX_LABEL_TEXT_LENGTH

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
        BraceNode, TallyMarksNode, LabelNode,
        AppearNode, HighlightNode, TransformNode, MoveAlongPathNode, CameraFocusNode, WaitNode,
    ],
    Field(discriminator="kind"),
]

for _cls in (RowNode, ColumnNode, OverlayNode, AlignNode, PaddingNode, SequenceNode, ParallelNode):
    _cls.model_rebuild()


class AnimationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    animation_version: Literal[1] = 1
    root: AnimationNode
