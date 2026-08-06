from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.teaching_plan import (
    BarVisual, CoordinatePlaneVisual, DataDisplayVisual, GridVisual, LabelVisual,
    NumberLineVisual, ObjectSetVisual, PartitionVisual, UnitTapeVisual,
)
from app.meta.dsl.v3_common import (
    MAX_ACTION_SECONDS, MAX_SCENE_SECONDS, MIN_ACTION_SECONDS, MIN_SCENE_SECONDS,
    AnchorRef, CalloutText, GeneratedText, ProseText, StyleRole, TargetRef,
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
    unit: ProseText = Field(default="", max_length=20)
    initial_role: StyleRole = "structure"


class AnswerProgramVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["answer_expression"] = "answer_expression"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    expression: ExpressionNode
    prefix: ProseText = ""
    suffix: ProseText = ""
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


class UnitTapeProgramVisual(UnitTapeVisual):
    initial_role: StyleRole = "structure"


class CoordinatePlaneProgramVisual(CoordinatePlaneVisual):
    initial_role: StyleRole = "structure"


class DataDisplayProgramVisual(DataDisplayVisual):
    initial_role: StyleRole = "structure"


ProgramVisual = Annotated[
    Union[
        OrderedValuesProgramVisual, RectangleProgramVisual,
        NumberLineProgramVisual, GridProgramVisual, PartitionProgramVisual,
        BarProgramVisual, ObjectSetProgramVisual, LabelProgramVisual,
        AnswerProgramVisual, UnitTapeProgramVisual, CoordinatePlaneProgramVisual,
        DataDisplayProgramVisual,
    ],
    Field(discriminator="kind"),
]


class CalloutRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["callout"] = "callout"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    target: AnchorRef
    text: CalloutText = Field(min_length=1, max_length=80)


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


class ShowAnswerStageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["show_answer_stage"] = "show_answer_stage"
    #: Always the answer visual. Carried explicitly, rather than being implied,
    #: so every existing consumer that discovers targets generically --
    #: `resolver.action_targets`, `quality._targets`,
    #: `quality.check_unused_visual` -- sees this action without modification.
    target: TargetRef
    stage: Literal["work", "value"]


class SignedHopArrowAction(BaseModel):
    """Directed arrow from a start marker to an end marker on a number_line.

    Compiler-emitted for the `signed_hop` strategy: one action per consecutive
    marker pair encodes the hop's sign through the source/target order (source
    left of target -> right-pointing arrow -> positive; reversed -> negative).
    Not authored by plans, so it has no `custom_action` counterpart.
    """
    model_config = ConfigDict(extra="forbid")
    kind: Literal["signed_hop_arrow"] = "signed_hop_arrow"
    source: TargetRef
    target: TargetRef


class DistanceAnnotationAction(BaseModel):
    """Span from the origin to a marker, labelled with the magnitude.

    Compiler-emitted for the `distance_from_zero` strategy. `label` is the
    formatted absolute value (e.g. `"7"` for the fixture `|-7|`) and is what
    the renderer draws above the bracket.
    """
    model_config = ConfigDict(extra="forbid")
    kind: Literal["distance_annotation"] = "distance_annotation"
    origin: TargetRef
    target: TargetRef
    label: ProseText = Field(min_length=1, max_length=8)


ProgramAction = Annotated[
    Union[
        RevealAction, SetRoleAction, TraceAction, ShowRelationAction,
        DrawAction, TransformAction, MoveAction, ShowAnswerStageAction,
        SignedHopArrowAction, DistanceAnnotationAction,
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
    #: The target that carries the lesson's answer when no `evaluated_answer`
    #: card is drawn. `None` means the answer is the card, as it is for every
    #: strategy but `pair_elimination`. Optional with a default so stored
    #: `scene_version` 3 programs deserialise unchanged.
    answer_anchor: TargetRef | None = None

    @model_validator(mode="after")
    def timeline_actions_fit_scene_duration(self):
        for index, timed_action in enumerate(self.timeline):
            end_seconds = timed_action.at_seconds + timed_action.duration_seconds
            if end_seconds > self.total_duration_seconds:
                raise ValueError(
                    "timeline action exceeds total scene duration "
                    f"at index {index}: ends at {end_seconds:g}s, "
                    f"scene ends at {self.total_duration_seconds:g}s"
                )
        return self
