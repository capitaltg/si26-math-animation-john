from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.v3_common import (
    MAX_PLAN_BEATS, MAX_SIMPLE_STAGGER_SECONDS, MIN_PLAN_BEATS,
    AnchorRef, GeneratedText, ProseText, StyleRole, TargetRef,
)


class OrderedValuesVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ordered_values"] = "ordered_values"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    values: list[ExpressionNode] = Field(min_length=3, max_length=15)


class RectangleMeasurementVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rectangle_measurement"] = "rectangle_measurement"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    length: ExpressionNode
    width: ExpressionNode
    unit: ProseText = Field(default="", max_length=20)


class NumberLineVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["number_line"] = "number_line"
    ref: GeneratedText
    minimum: ExpressionNode
    maximum: ExpressionNode
    markers: list[ExpressionNode] = Field(default_factory=list, max_length=16)


class GridVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["grid"] = "grid"
    ref: GeneratedText
    rows: ExpressionNode
    columns: ExpressionNode


class PartitionVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["partition"] = "partition"
    ref: GeneratedText
    whole: ExpressionNode
    parts: ExpressionNode


class BarVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["bar"] = "bar"
    ref: GeneratedText
    value: ExpressionNode
    maximum: ExpressionNode


class ObjectSetVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["object_set"] = "object_set"
    ref: GeneratedText
    count: ExpressionNode


class LabelVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["label"] = "label"
    ref: GeneratedText
    text: ProseText = Field(min_length=1, max_length=80)


SemanticVisualSpec = Annotated[
    Union[
        OrderedValuesVisual, RectangleMeasurementVisual, NumberLineVisual,
        GridVisual, PartitionVisual, BarVisual, ObjectSetVisual, LabelVisual,
    ],
    Field(discriminator="kind"),
]


class RevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["reveal"] = "reveal"
    targets: list[TargetRef] = Field(min_length=1, max_length=8)
    mode: Literal["together", "stagger"] = "together"
    stagger_seconds: float = Field(default=0.0, ge=0, le=MAX_SIMPLE_STAGGER_SECONDS)


class EmphasizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["emphasize"] = "emphasize"
    target: TargetRef
    role: StyleRole = "focus"


class DimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["dim"] = "dim"
    target: TargetRef


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["restore"] = "restore"
    target: TargetRef


class TraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["trace"] = "trace"
    path_ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_.]{0,95}$")


class CalloutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["callout"] = "callout"
    target: AnchorRef
    text: ProseText = Field(min_length=1, max_length=80)


class DrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["draw"] = "draw"
    target: TargetRef


class TransformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["transform"] = "transform"
    source: TargetRef
    target: TargetRef


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["move"] = "move"
    target: TargetRef
    path_ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_.]{0,95}$")


RequestedAction = Annotated[
    Union[
        RevealRequest, EmphasizeRequest, DimRequest, RestoreRequest,
        TraceRequest, CalloutRequest, DrawRequest, TransformRequest, MoveRequest,
    ],
    Field(discriminator="kind"),
]


class TeachingBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    kind: Literal["orient", "reveal", "organize", "focus", "derive", "conclude"]
    targets: list[TargetRef] = Field(min_length=1, max_length=8)
    intent: ProseText = Field(min_length=1, max_length=240)
    custom_actions: list[RequestedAction] = Field(default_factory=list, max_length=8)


class TeachingPlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: Literal[3] = 3
    learning_objective: ProseText = Field(min_length=1, max_length=300)
    primary_visual: SemanticVisualSpec
    supporting_visuals: list[SemanticVisualSpec] = Field(default_factory=list, max_length=4)
    strategy: Literal[
        "group_reveal", "short_stagger", "pair_elimination", "boundary_trace",
        "partition", "regroup", "magnitude_comparison",
    ]
    beats: list[TeachingBeat] = Field(min_length=MIN_PLAN_BEATS, max_length=MAX_PLAN_BEATS)
    variation_seed: GeneratedText = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_focus_and_conclusion_order(self):
        if self.beats[-1].kind != "conclude":
            raise ValueError("the final beat must be conclude")
        # A `conclude` beat is where the compiler reveals the evaluated answer
        # and gives it the `conclusion` role (see
        # `beat_expander._standard_actions`). Requiring only that the LAST beat
        # be `conclude` made a *second*, mid-scene `conclude` schema-legal --
        # which reveals the answer before the focus/derive beat that is
        # supposed to derive it, violating the constraint that the
        # evaluated-answer visual is introduced only during `conclude`. There
        # is exactly one conclusion per lesson, so say so here.
        if any(beat.kind == "conclude" for beat in self.beats[:-1]):
            raise ValueError("only the final beat may be conclude")
        if not any(beat.kind in {"orient", "reveal", "organize"} for beat in self.beats[:-1]):
            raise ValueError("a context-establishing beat must precede conclude")
        if not any(beat.kind in {"focus", "derive"} for beat in self.beats[:-1]):
            raise ValueError("an explicit focus or derivation must precede conclude")
        return self
