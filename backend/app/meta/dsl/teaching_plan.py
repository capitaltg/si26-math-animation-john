from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.v3_common import (
    MAX_PLAN_BEATS, MAX_SIMPLE_STAGGER_SECONDS, MIN_PLAN_BEATS,
    AnchorRef, GeneratedText, ProseText, StyleRole, TargetRef,
)
from app.meta.v3.visual_registry import MAX_PART_CARDINALITY


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
    maximum: ExpressionNode = Field(description=(
        "The line's numeric scale, NOT a count of anything drawn. Markers land "
        "inside fixed bounds, so a line from 0 to a million costs no more to draw "
        "than one from 0 to 10. Use this visual for any magnitude too large to "
        "show as individual parts."
    ))
    markers: list[ExpressionNode] = Field(
        default_factory=list, max_length=16,
        description=(
            "The values to mark on the line, each labelled with its number. "
            "Include minimum and maximum among the markers when the learner needs "
            "the ends labelled."
        ),
    )


class GridVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["grid"] = "grid"
    ref: GeneratedText
    rows: ExpressionNode = Field(description=(
        f"Number of rows. One cell rectangle is drawn per row x column, at most "
        f"{MAX_PART_CARDINALITY} rows and {MAX_PART_CARDINALITY} columns; for a "
        f"magnitude larger than that use a number_line."
    ))
    columns: ExpressionNode = Field(description=(
        f"Number of columns. One cell rectangle is drawn per row x column, at "
        f"most {MAX_PART_CARDINALITY} rows and {MAX_PART_CARDINALITY} columns; "
        f"for a magnitude larger than that use a number_line."
    ))


class PartitionVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["partition"] = "partition"
    ref: GeneratedText
    whole: ExpressionNode
    parts: ExpressionNode = Field(description=(
        f"How many equal parts the whole is divided into, drawn one marker per "
        f"part, at most {MAX_PART_CARDINALITY}. For a magnitude larger than that "
        f"use a number_line."
    ))


class BarVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["bar"] = "bar"
    ref: GeneratedText
    value: ExpressionNode = Field(description=(
        "How much of the bar is filled, in the same units as maximum."
    ))
    maximum: ExpressionNode = Field(description=(
        f"The bar's length as a COUNT of equal segments: one rectangle is drawn "
        f"per unit, at most {MAX_PART_CARDINALITY}, and only about 29 fit the "
        f"frame. This is NOT an axis maximum -- a quantity like 2750 out of "
        f"10000 must not be a bar. Show a magnitude that large on a number_line, "
        f"whose maximum is a scale, or on a unit_tape when the lesson converts "
        f"between two units."
    ))


class ObjectSetVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["object_set"] = "object_set"
    ref: GeneratedText
    count: ExpressionNode = Field(description=(
        f"How many objects to draw, one dot each, five per row, at most "
        f"{MAX_PART_CARDINALITY}. For a magnitude larger than that use a "
        f"number_line."
    ))


class UnitTapeVisual(BaseModel):
    """A quantity in one unit, drawn as one box per whole unit, named in two units.

    The teaching visual for a conversion: each box carries the source unit's name
    and, revealed later by `unit_substitution`, the target unit's.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["unit_tape"] = "unit_tape"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: ExpressionNode = Field(description=(
        "How many source units the quantity is, e.g. 2.75 for 2.75 kilometres. "
        "One box is drawn per whole unit plus one for any remainder, at most 8 "
        "boxes; for a larger magnitude use a number_line."
    ))
    per_unit: ExpressionNode = Field(description=(
        "How many target units make one source unit, e.g. 1000 for kilometres to "
        "metres. This is a label number, not a count -- nothing is drawn per "
        "target unit -- so it may be as large as the conversion requires."
    ))
    source_unit: ProseText = Field(min_length=1, max_length=20, description=(
        "The unit the quantity is given in, as it should read on screen: \"km\"."
    ))
    target_unit: ProseText = Field(min_length=1, max_length=20, description=(
        "The unit being converted to, as it should read on screen: \"m\"."
    ))


class LabelVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["label"] = "label"
    ref: GeneratedText
    text: ProseText = Field(min_length=1, max_length=80)


SemanticVisualSpec = Annotated[
    Union[
        OrderedValuesVisual, RectangleMeasurementVisual, NumberLineVisual,
        GridVisual, PartitionVisual, BarVisual, ObjectSetVisual, LabelVisual,
        UnitTapeVisual,
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
    path_ref: GeneratedText = Field(
        pattern=r"^[a-z][a-z0-9_.]{0,95}$",
        description=(
            "A declared visual path, in the form visual_ref.path_name (exactly one dot). "
            "The only declared path today is perimeter, on rectangle_measurement visuals "
            "only. Reference any other sub-part (an edge, vertex, or item) through a "
            "target's part and index, never through path_ref."
        ),
    )


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
    path_ref: GeneratedText = Field(
        pattern=r"^[a-z][a-z0-9_.]{0,95}$",
        description=(
            "A declared visual path, in the form visual_ref.path_name (exactly one dot). "
            "The only declared path today is perimeter, on rectangle_measurement visuals "
            "only. Reference any other sub-part (an edge, vertex, or item) through a "
            "target's part and index, never through path_ref."
        ),
    )


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
        "partition", "regroup", "magnitude_comparison", "unit_substitution",
    ]
    #: The unit of the computed result ("meters"), empty when unitless. The
    #: compiler puts it on the answer visual's suffix; the model authors nothing
    #: else about answer presentation.
    answer_unit: ProseText = Field(default="", max_length=20)
    beats: list[TeachingBeat] = Field(min_length=MIN_PLAN_BEATS, max_length=MAX_PLAN_BEATS)
    variation_seed: GeneratedText = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_focus_and_conclusion_order(self):
        if self.beats[-1].kind != "conclude":
            raise ValueError("the final beat must be conclude")
        # A `conclude` beat is where the compiler resolves the evaluated answer
        # to its value and gives it the `conclusion` role (see
        # `beat_expander._standard_actions`); the answer is revealed as "? unit"
        # in the first beat, so conclude resolves it rather than introducing it.
        # Requiring only that the LAST beat be `conclude` made a *second*,
        # mid-scene `conclude` schema-legal -- which resolves the answer before
        # the focus/derive beat that is supposed to derive it, violating the
        # constraint that the resolved value appears only during `conclude`.
        # There is exactly one conclusion per lesson, so say so here.
        if any(beat.kind == "conclude" for beat in self.beats[:-1]):
            raise ValueError("only the final beat may be conclude")
        if not any(beat.kind in {"orient", "reveal", "organize"} for beat in self.beats[:-1]):
            raise ValueError("a context-establishing beat must precede conclude")
        if not any(beat.kind in {"focus", "derive"} for beat in self.beats[:-1]):
            raise ValueError("an explicit focus or derivation must precede conclude")
        return self

    @model_validator(mode="after")
    def require_pair_elimination_shape(self):
        """`pair_elimination` is staged by the compiler, not written by the plan.

        A plan that also hand-writes its elimination competes with the
        compiler's own pass: both emit role changes into one beat, and the beat
        plays as a frantic wave rather than as pairing. The strategy names a
        choreography, so the plan supplies the collection and the beat
        structure and the compiler supplies the staging.

        The primary visual kind is not checked here --
        `compiler.validate_strategy_compatibility` already rejects
        `pair_elimination` on anything but `ordered_values`, and reaching for
        `.values` on another kind would raise `AttributeError` instead of a
        readable failure.
        """
        if self.strategy != "pair_elimination" or self.primary_visual.kind != "ordered_values":
            return self

        organize_positions = [
            position for position, beat in enumerate(self.beats) if beat.kind == "organize"
        ]
        if len(organize_positions) != 1:
            raise ValueError(
                "pair_elimination needs exactly one organize beat, which is where the "
                f"compiler stages the elimination; found {len(organize_positions)}"
            )

        organize_beat = self.beats[organize_positions[0]]
        if organize_beat.custom_actions:
            raise ValueError(
                f"beat {organize_beat.id!r} is pair_elimination's organize beat, which the "
                "compiler stages entirely on its own; move its custom actions to another beat"
            )

        middle = TargetRef(
            visual_ref=self.primary_visual.ref,
            part="item",
            index=len(self.primary_visual.values) // 2,
        )
        if not any(
            beat.kind == "focus" and beat.targets == [middle]
            for beat in self.beats[organize_positions[0] + 1:]
        ):
            raise ValueError(
                "pair_elimination needs a focus beat after the organize beat whose only "
                f"target is the unpaired middle item {middle.visual_ref}.item[{middle.index}]"
            )

        for beat in self.beats:
            for action in beat.custom_actions:
                if (
                    action.kind in {"dim", "emphasize", "restore"}
                    and action.target.visual_ref == self.primary_visual.ref
                ):
                    raise ValueError(
                        f"beat {beat.id!r} changes the role of the primary visual, whole or "
                        "item; pair_elimination stages its own elimination, so remove the "
                        "custom action"
                    )
        return self

    @model_validator(mode="after")
    def reject_custom_actions_on_strategy_owned_beats(self):
        """Some beats the compiler stages end-to-end; a hand-written action on
        them either duplicates work or slips role changes past the strategy
        expander's slot arithmetic. `_slot_count` sizes the beat by the
        expander's own action count, so an extra author-written role change
        can land two `focus` targets at one `at_seconds` and fail
        `check_salience` well after generation.

        Two beats fall in this bucket today:
        - `regroup`'s `organize` beat, which the compiler walks row by row.
        - `magnitude_comparison`'s `focus` or `derive` beat -- whichever plays
          first, the beat the sweep animates. Later focus/derive beats on the
          same plan remain author-writable.
        """
        if self.strategy == "regroup":
            # Same selection rule as the expander -- the first organize beat
            # that names the primary visual. Guarding every organize beat
            # would forbid custom actions on later organize beats the
            # expander does not stage, and guarding only the first would
            # miss the actual walk beat when the first organize beat targets
            # something else.
            primary_ref = self.primary_visual.ref
            walk_beat = next(
                (
                    beat for beat in self.beats
                    if beat.kind == "organize"
                    and any(target.visual_ref == primary_ref for target in beat.targets)
                ),
                None,
            )
            if walk_beat is not None and walk_beat.custom_actions:
                raise ValueError(
                    f"beat {walk_beat.id!r} is regroup's walk beat, which the compiler "
                    "stages entirely on its own; move its custom actions to another beat"
                )
        if self.strategy == "magnitude_comparison":
            # Same selection rule as the expander -- the first focus/derive
            # beat that names the primary visual. Guarding only the first
            # focus/derive beat (regardless of what it targets) would let the
            # actual sweep beat carry custom actions when an earlier
            # focus/derive beat targets something else.
            primary_ref = self.primary_visual.ref
            sweep_beat = next(
                (
                    beat for beat in self.beats
                    if beat.kind in {"focus", "derive"}
                    and any(target.visual_ref == primary_ref for target in beat.targets)
                ),
                None,
            )
            if sweep_beat is not None and sweep_beat.custom_actions:
                raise ValueError(
                    f"beat {sweep_beat.id!r} is magnitude_comparison's sweep beat, which "
                    "the compiler stages entirely on its own; move its custom actions to "
                    "another beat"
                )
        return self

    @model_validator(mode="after")
    def require_unit_substitution_shape(self):
        """`unit_substitution` is staged by the compiler, not written by the plan.

        The compiler reveals every `target_label` at the derive beat using the
        visual's group part. A plan cannot express that: `_validate_target`
        requires an index for a part target, so a plan reveal could only name one
        box's label and would leave the rest unrevealed while still looking like
        an affordance. Same reasoning as `require_pair_elimination_shape`.
        """
        if self.strategy != "unit_substitution":
            return self
        for beat in self.beats:
            targets = [
                *beat.targets,
                *(
                    target
                    for action in beat.custom_actions
                    for target in (
                        *getattr(action, "targets", ()),
                        *(
                            getattr(action, attribute)
                            for attribute in ("target", "source")
                            if getattr(action, attribute, None) is not None
                        ),
                    )
                ),
            ]
            if any(target.part == "target_label" for target in targets):
                raise ValueError(
                    f"beat {beat.id!r} names target_label, which unit_substitution "
                    "stages on its own; remove the target or the custom action"
                )
        return self
