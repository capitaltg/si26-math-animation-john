from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.meta.dsl.expression import ExpressionNode, LiteralNode
from app.meta.dsl.v3_common import (
    MAX_PLAN_BEATS, MAX_SIMPLE_STAGGER_SECONDS, MIN_PLAN_BEATS,
    AnchorRef, CalloutText, GeneratedText, ProseText, StyleRole, TargetRef,
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
    boundary: ExpressionNode | None = Field(
        default=None,
        description=(
            "The boundary value of an inequality graphed on the line. Required "
            "for the `ray_shade` strategy; leave `None` otherwise. The measurer "
            "exposes it as a `boundary` semantic part addressable by beats."
        ),
    )
    boundary_kind: Literal["open", "closed"] | None = Field(
        default=None,
        description=(
            "Whether the boundary is inclusive (`closed`, filled dot; the "
            "inequality includes the value) or exclusive (`open`, ring; the "
            "inequality is strict). Required for `ray_shade`."
        ),
    )
    ray_direction: Literal["left", "right"] | None = Field(
        default=None,
        description=(
            "Which side of the boundary the ray shades: `right` for x > b or "
            "x >= b, `left` for x < b or x <= b. Required for `ray_shade`."
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
        f"How many equal parts the whole is divided into, drawn one wedge per "
        f"part, at most {MAX_PART_CARDINALITY}. For a magnitude larger than that "
        f"use a number_line."
    ))
    shaded: ExpressionNode = Field(
        default_factory=lambda: LiteralNode(value=0),
        description=(
            "How many of the parts are shaded -- the numerator of the fraction "
            "this partition depicts. Defaults to 0 for a plain (unshaded) "
            "partition; the compiler requires 0 <= shaded <= parts and rejects "
            "an equivalent partition, LCD bridge, or refined operand whose "
            "shaded/parts fraction does not match the strategy's move."
        ),
    )


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
    constant: ExpressionNode | None = Field(
        default=None,
        description=(
            "The known-addend portion the bar splits off from the unknown x. "
            "Required for the `inverse_operation` strategy on one- or two-step "
            "equations (`x + c = r`, `k*x + c = r`); the last `constant` "
            "segments are grouped as the `constant_region` and the first "
            "`maximum - constant` segments as the `x_region`. Leave `None` "
            "otherwise."
        ),
    )
    coefficient: ExpressionNode | None = Field(
        default=None,
        description=(
            "How many equal x-parts the x_region subdivides into (the `k` in "
            "`k*x + c = r`). Required for `inverse_operation`; use 1 for a "
            "one-step equation, k >= 2 for a two-step equation. The compiler "
            "requires `(maximum - constant) % coefficient == 0` so each "
            "x_part is a whole segment count."
        ),
    )


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


class CoordinatePointNode(BaseModel):
    """One plotted (x, y) pair on a coordinate_plane.

    x/y are expressions so a fixture param may drive the coordinates the way
    it drives every other visual's numeric fields. Both must resolve inside the
    plane's declared span; the measurer rejects an out-of-range point.
    """

    model_config = ConfigDict(extra="forbid")
    x: ExpressionNode
    y: ExpressionNode


class DataDisplayCategory(BaseModel):
    """One labelled category on a `bar_graph` or one bin on a `histogram`.

    `count` is an expression so a fixture may drive category counts the same way
    it drives every other visual's numeric field. Every category label appears on
    the axis strip, so total label length feeds into the extent guard.
    """

    model_config = ConfigDict(extra="forbid")
    label: ProseText = Field(min_length=1, max_length=16)
    count: ExpressionNode


class DataDisplayFiveNumberSummary(BaseModel):
    """The five values a `box_plot` displays: min, Q1, median, Q3, max.

    Kept as a nested model so the schema names each role rather than relying on
    positional order in a bare list. `min <= q1 <= median <= q3 <= max` is a
    definitional invariant enforced at measurement (the measurer refuses an
    inverted summary), not here at schema time -- an expression whose ordering
    depends on fixture params cannot be settled by schema validation alone.
    """

    model_config = ConfigDict(extra="forbid")
    minimum: ExpressionNode
    q1: ExpressionNode
    median: ExpressionNode
    q3: ExpressionNode
    maximum: ExpressionNode


#: Cap on data points a `line_plot` / `dot_plot` may display. A dot plot stacks
#: repeats vertically, so a very tall stack overruns the frame -- the extent
#: guard rejects that with a driving-field hint. This cap is an upper bound for
#: the schema so a fixture cannot ask for hundreds of points; anything past ~30
#: reads as data-heavy for grades 3-6 and is better served by a summary display.
MAX_DATA_DISPLAY_VALUES = 32
#: Cap on categories a `bar_graph` / bins a `histogram` may show. Each category
#: gets an axis-strip label; past ~10 categories the labels crowd unless the
#: axis stretches wider than the frame.
MAX_DATA_DISPLAY_CATEGORIES = 10


class DataDisplayVisual(BaseModel):
    """Axis-based data display -- bar graph, line plot, dot plot, histogram, or box plot.

    Chosen as a single kind (not five) because every variant shares the same
    reasoning move: an ordered collection mapped onto one axis. The
    fixture-facing surface names each variant through `display_style`; the
    measurer branches on it. A shared kind keeps `_PROGRAM_VISUALS`,
    `_EXPRESSION_FIELDS` and the renderer's dispatch small, and every variant
    that reaches for the same axis-labeling / extent-fit machinery uses the
    same code paths.

    Required fields depend on `display_style`:
    - `bar_graph`, `histogram`: `categories` (label + count per bar).
    - `line_plot`, `dot_plot`: `values` plus `axis_min` / `axis_max`.
    - `box_plot`: `summary` (five-number summary) plus `axis_min` / `axis_max`.
    Fields for other variants must be omitted; a model_validator refuses any
    combination that would leave the shape ambiguous.

    MCAP standards: 3.MD.B.3-4, 4.MD.B.4, 5.MD.B.2, 6.SP.B.4.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["data_display"] = "data_display"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    display_style: Literal[
        "bar_graph", "line_plot", "dot_plot", "histogram", "box_plot",
    ] = Field(description=(
        "Which axis-based display to render. `bar_graph` and `histogram` "
        "use `categories`; `line_plot` and `dot_plot` use `values` on a "
        "number line spanning `axis_min` to `axis_max`; `box_plot` uses "
        "`summary` on the same number-line axis."
    ))
    categories: list[DataDisplayCategory] = Field(
        default_factory=list, max_length=MAX_DATA_DISPLAY_CATEGORIES,
        description=(
            "Bars for `bar_graph` (label + count per category) or bins for "
            "`histogram` (label = numeric range as text; count = frequency). "
            "Omit for `line_plot`, `dot_plot`, `box_plot`."
        ),
    )
    values: list[ExpressionNode] = Field(
        default_factory=list, max_length=MAX_DATA_DISPLAY_VALUES,
        description=(
            "Data points for `line_plot` / `dot_plot`. Each value must lie in "
            "[axis_min, axis_max]. Omit for other display styles."
        ),
    )
    axis_min: ExpressionNode | None = Field(
        default=None,
        description=(
            "Lower end of the numeric axis, required for `line_plot`, "
            "`dot_plot`, `box_plot`. Omit for `bar_graph` and `histogram`."
        ),
    )
    axis_max: ExpressionNode | None = Field(
        default=None,
        description=(
            "Upper end of the numeric axis. Must exceed `axis_min`."
        ),
    )
    summary: DataDisplayFiveNumberSummary | None = Field(
        default=None,
        description=(
            "Five-number summary for `box_plot`. Omit for other styles."
        ),
    )
    axis_label: ProseText = Field(
        default="", max_length=20,
        description=(
            "Optional axis title displayed beneath the axis strip. Empty "
            "string omits the label."
        ),
    )

    @model_validator(mode="after")
    def require_fields_matching_display_style(self):
        style = self.display_style
        if style in {"bar_graph", "histogram"}:
            if not self.categories:
                raise ValueError(
                    f"{style} requires at least one entry in `categories`"
                )
            if self.values or self.summary is not None:
                raise ValueError(
                    f"{style} uses `categories`; leave `values` and `summary` empty"
                )
            if self.axis_min is not None or self.axis_max is not None:
                raise ValueError(
                    f"{style} derives its numeric axis from category counts; "
                    "leave `axis_min` and `axis_max` empty"
                )
        elif style in {"line_plot", "dot_plot"}:
            if not self.values:
                raise ValueError(
                    f"{style} requires at least one entry in `values`"
                )
            if self.categories or self.summary is not None:
                raise ValueError(
                    f"{style} uses `values`; leave `categories` and `summary` empty"
                )
            if self.axis_min is None or self.axis_max is None:
                raise ValueError(
                    f"{style} requires `axis_min` and `axis_max`"
                )
        elif style == "box_plot":
            if self.summary is None:
                raise ValueError("box_plot requires `summary`")
            if self.categories or self.values:
                raise ValueError(
                    "box_plot uses `summary`; leave `categories` and `values` empty"
                )
            if self.axis_min is None or self.axis_max is None:
                raise ValueError("box_plot requires `axis_min` and `axis_max`")
        return self


class PolygonSpec(BaseModel):
    """One polygon plotted on a coordinate_plane (M22).

    Vertex order defines the polygon's edges (v[0]→v[1], v[1]→v[2], …,
    v[N-1]→v[0]). The measurer refuses a self-intersecting order at compile
    time so a rotated image cannot degenerate into a bowtie. Vertex labels
    ("A", "B", "C", …) are auto-generated by the renderer in vertex order;
    the plan authors no label field.
    """

    model_config = ConfigDict(extra="forbid")
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    vertices: list[CoordinatePointNode] = Field(min_length=3, max_length=6)


class CoordinatePlaneVisual(BaseModel):
    """A Cartesian grid with plotted points.

    Foundational archetype for MCAP 5.G.A.1-2 / 6.NS.C.6c / 6.NS.C.8 and the
    substrate downstream tickets attach transformations, scatter plots, and
    line/polygon drawings to. The plane's numeric span is declared here so the
    axes never renegotiate their extent per downstream ticket -- a point at
    (2, 3) sits in the same fraction of the frame regardless of the strategy.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["coordinate_plane"] = "coordinate_plane"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    x_min: ExpressionNode
    x_max: ExpressionNode
    y_min: ExpressionNode
    y_max: ExpressionNode
    points: list[CoordinatePointNode] = Field(
        default_factory=list, max_length=8,
        description=(
            "Points to plot as labelled dots. Each point's coordinates must lie "
            "inside the declared span; at most eight points fit the plane at a "
            "legible size."
        ),
    )
    grid: bool = Field(
        default=False,
        description=(
            "When true, draw faint grid lines at every integer coordinate "
            "inside the declared span. Ticket #108 acceptance calls the grid "
            "optional; omit or set false for a bare axes-and-points plane."
        ),
    )
    polygons: list[PolygonSpec] = Field(
        default_factory=list, max_length=1,
        description=(
            "Optional primary polygon plotted on the plane (M22). MVP caps "
            "at one; multi-polygon planes are deferred to a sibling ticket."
        ),
    )
    pivot: CoordinatePointNode | None = Field(
        default=None,
        description=(
            "The fixed point a rotation strategy pivots the polygon about. "
            "Must lie inside the declared span. Required for the `rotation` "
            "strategy; leave `None` otherwise."
        ),
    )
    rotation_angle_deg: Literal[45, 90, 180, 270] | None = Field(
        default=None,
        description=(
            "Per-iteration rotation angle in degrees. The Literal is the set "
            "of teaching-relevant angles; a chained 90° stays exact because "
            "the renderer never evaluates the angle at runtime."
        ),
    )
    rotation_iterations: int | None = Field(
        default=None, ge=1, le=4,
        description=(
            "How many discrete rotation steps to play. 1..4; the compiler "
            "rejects `iterations * angle_deg` that lands the polygon back on "
            "its start (identity mid-sequence)."
        ),
    )


SemanticVisualSpec = Annotated[
    Union[
        OrderedValuesVisual, RectangleMeasurementVisual, NumberLineVisual,
        GridVisual, PartitionVisual, BarVisual, ObjectSetVisual, LabelVisual,
        UnitTapeVisual, CoordinatePlaneVisual, DataDisplayVisual,
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
    text: CalloutText = Field(min_length=1, max_length=80)


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
        "unit_rate", "inverse_operation", "ray_shade",
        "signed_hop", "distance_from_zero",
        "equivalence_align", "common_denominator_bridge",
        "percent_of_whole", "percent_change",
        "rotation",
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
        if self.strategy in {"percent_of_whole", "percent_change"}:
            # Same reasoning as magnitude_comparison: the compiler owns the
            # sweep beat's actions (a segment-per-slot focus over the part
            # or the delta), and a hand-written role change on the same
            # beat would either duplicate a compiler-emitted focus or slip
            # a second focus into a slot the salience gate expects to hold
            # exactly one. Author-written callouts belong on an adjacent
            # beat, not on the sweep itself.
            #
            # For percent_change the beat that owns the sweep is the first
            # focus/derive beat naming the supporting (after) bar, not the
            # primary; percent_of_whole matches magnitude_comparison and
            # picks the first focus/derive beat naming the primary.
            sweep_ref = (
                self.supporting_visuals[0].ref
                if self.strategy == "percent_change" and self.supporting_visuals
                else self.primary_visual.ref
            )
            sweep_beat = next(
                (
                    beat for beat in self.beats
                    if beat.kind in {"focus", "derive"}
                    and any(target.visual_ref == sweep_ref for target in beat.targets)
                ),
                None,
            )
            if sweep_beat is not None and sweep_beat.custom_actions:
                raise ValueError(
                    f"beat {sweep_beat.id!r} is {self.strategy}'s sweep beat, which "
                    "the compiler stages entirely on its own; move its custom actions "
                    "to another beat"
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

        `unit_rate` reuses the same target_label group reveal to name the "per
        one" pairing in every box, so it inherits the same shape constraint.
        """
        if self.strategy not in {"unit_substitution", "unit_rate"}:
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
                    f"beat {beat.id!r} names target_label, which {self.strategy} "
                    "stages on its own; remove the target or the custom action"
                )
        return self
