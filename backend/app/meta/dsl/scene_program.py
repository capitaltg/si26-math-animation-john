from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.teaching_plan import (
    BarVisual, GridVisual, LabelVisual, NumberLineVisual, ObjectSetVisual,
    PartitionVisual,
)
from app.meta.dsl.v3_common import (
    MAX_ACTION_SECONDS, MAX_SCENE_SECONDS, MIN_ACTION_SECONDS, MIN_SCENE_SECONDS,
    AnchorRef, GeneratedText, StyleRole, TargetRef,
)


class OrderedValuesProgramVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ordered_values"] = "ordered_values"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    values: list[ExpressionNode]
    initial_role: StyleRole = "neutral"


class RectangleProgramVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rectangle_measurement"] = "rectangle_measurement"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    length: ExpressionNode
    width: ExpressionNode
    unit: GeneratedText = Field(default="", max_length=20)
    initial_role: StyleRole = "structure"


class AnswerProgramVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["answer_expression"] = "answer_expression"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    expression: ExpressionNode
    prefix: GeneratedText = ""
    suffix: GeneratedText = ""
    initial_role: Literal["neutral"] = "neutral"


class NumberLineProgramVisual(NumberLineVisual):
    initial_role: StyleRole = "structure"


class GridProgramVisual(GridVisual):
    initial_role: StyleRole = "structure"


class PartitionProgramVisual(PartitionVisual):
    initial_role: StyleRole = "structure"


class BarProgramVisual(BarVisual):
    initial_role: StyleRole = "structure"


class ObjectSetProgramVisual(ObjectSetVisual):
    initial_role: StyleRole = "structure"


class LabelProgramVisual(LabelVisual):
    initial_role: StyleRole = "neutral"


ProgramVisual = Annotated[
    Union[
        OrderedValuesProgramVisual, RectangleProgramVisual,
        NumberLineProgramVisual, GridProgramVisual, PartitionProgramVisual,
        BarProgramVisual, ObjectSetProgramVisual, LabelProgramVisual,
        AnswerProgramVisual,
    ],
    Field(discriminator="kind"),
]


class CalloutRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["callout"] = "callout"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    target: AnchorRef
    text: GeneratedText = Field(min_length=1, max_length=80)


Relation = CalloutRelation


class RevealAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["reveal"] = "reveal"
    targets: list[TargetRef] = Field(min_length=1, max_length=8)
    mode: Literal["together", "stagger"] = "together"


class SetRoleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["set_role"] = "set_role"
    target: TargetRef
    role: StyleRole


class TraceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["trace"] = "trace"
    path_ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_.]{0,95}$")


class ShowRelationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["show_relation"] = "show_relation"
    relation_ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class DrawAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["draw"] = "draw"
    target: TargetRef


class TransformAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["transform"] = "transform"
    source: TargetRef
    target: TargetRef


class MoveAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["move"] = "move"
    target: TargetRef
    path_ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_.]{0,95}$")


ProgramAction = Annotated[
    Union[
        RevealAction, SetRoleAction, TraceAction, ShowRelationAction,
        DrawAction, TransformAction, MoveAction,
    ],
    Field(discriminator="kind"),
]


class TimedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at_seconds: float = Field(ge=0, le=MAX_SCENE_SECONDS)
    duration_seconds: float = Field(ge=MIN_ACTION_SECONDS, le=MAX_ACTION_SECONDS)
    beat_id: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    action: ProgramAction


class StyleRecipeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    palette: Literal["ocean", "violet", "teal"]
    composition: Literal["vertical_lesson", "comparison", "equation_flow"]
    motion_variant: Literal["smooth", "crisp"]


class SceneProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_version: Literal[3] = 3
    visuals: list[ProgramVisual] = Field(min_length=1, max_length=16)
    relations: list[Relation] = Field(default_factory=list, max_length=16)
    timeline: list[TimedAction] = Field(min_length=1, max_length=40)
    total_duration_seconds: float = Field(ge=MIN_SCENE_SECONDS, le=MAX_SCENE_SECONDS)
    variation_seed: GeneratedText = Field(min_length=1, max_length=64)
    style_recipe: StyleRecipeDocument
