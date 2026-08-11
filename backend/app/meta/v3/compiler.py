from dataclasses import asdict
from fractions import Fraction
from math import ceil, cos, gcd, radians, sin

from app.meta.dsl.expression import FieldContract, compile_expression
from app.meta.dsl.scene_program import SceneProgramDocument, StyleRecipeDocument
from app.meta.dsl.v3_common import TargetRef
from app.meta.v3.beat_expander import (
    STRUCTURE_VISUAL_KINDS,
    common_denominator_bridge_beat_id, equivalence_align_beat_id,
    expand_beats, magnitude_sweep_beat_id, percent_sweep_beat_id, regroup_beat_id,
    rotation_focus_or_derive_beats,
)
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.style_recipe import resolve_style_recipe
from app.meta.v3.timeline import schedule_beats
from app.meta.v3.visual_registry import _SUPPORTED_STRATEGIES, _polygon_self_intersects


_EXPRESSION_FIELDS = {
    "ordered_values": ("values",),
    "rectangle_measurement": ("length", "width"),
    "number_line": ("minimum", "maximum", "markers"),
    "grid": ("rows", "columns"),
    "partition": ("whole", "parts", "shaded"),
    "bar": ("value", "maximum"),
    "object_set": ("count",),
    "label": (),
    "unit_tape": ("value", "per_unit"),
    "coordinate_plane": ("x_min", "x_max", "y_min", "y_max"),
    "data_display": (),
}

#: Optional ExpressionNode fields whose value is only present under specific
#: strategies. Iterated in `expressions_from_plan` when the field is set.
_OPTIONAL_EXPRESSION_FIELDS = {
    "bar": ("constant", "coefficient"),
    "number_line": ("boundary",),
}

def _bar_x_region_cardinality(spec):
    """One `x_region` / `constant_region` exists exactly when the bar carries
    an equation partition. Returns 0 (rejecting any target) on a plain bar
    and 1 otherwise, so `_validate_target` catches a stray part reference
    with `target_index_out_of_range` instead of `unknown_semantic_part`.
    """
    return 1 if spec.constant is not None else 0


def _bar_x_part_cardinality(spec):
    if spec.constant is None or spec.coefficient is None:
        return 0
    return _literal_integer(spec.coefficient)


def _number_line_boundary_cardinality(spec):
    return 1 if spec.boundary is not None else 0


_PART_CARDINALITY = {
    "ordered_values": {"item": lambda spec: len(spec.values)},
    "rectangle_measurement": {
        "edge": lambda spec: 4,
        "length_edge": lambda spec: 2,
        "width_edge": lambda spec: 2,
        "vertex": lambda spec: 4,
    },
    "number_line": {
        "marker": lambda spec: len(spec.markers),
        "boundary": _number_line_boundary_cardinality,
        "ray": _number_line_boundary_cardinality,
    },
    "grid": {"cell": lambda spec: _literal_product(spec.rows, spec.columns)},
    "partition": {"partition": lambda spec: _literal_integer(spec.parts)},
    "bar": {
        "segment": lambda spec: _literal_integer(spec.maximum),
        "x_region": _bar_x_region_cardinality,
        "constant_region": _bar_x_region_cardinality,
        "x_part": _bar_x_part_cardinality,
    },
    "object_set": {"item": lambda spec: _literal_integer(spec.count)},
    "label": {},
    "unit_tape": {
        "box": lambda spec: _literal_ceiling(spec.value),
        "source_label": lambda spec: _literal_ceiling(spec.value),
        "target_label": lambda spec: _literal_ceiling(spec.value),
    },
    "coordinate_plane": {"point": lambda spec: len(spec.points)},
    "data_display": {
        # `mark` covers every per-data-point primitive across styles: `bar_graph`
        # bars, `histogram` bins, `line_plot` / `dot_plot` per-value marks, and
        # `box_plot`'s single box. A single part name lets a plan address a
        # specific display element without branching on `display_style`; the
        # cardinality is whichever collection the style uses.
        "mark": lambda spec: _data_display_mark_count(spec),
    },
}


def _data_display_mark_count(spec):
    """How many `mark` parts the display exposes at compile time.

    Category-based styles read from the plan directly; number-line-based styles
    return the length of their `values` list. `box_plot` exposes exactly one
    mark -- the box itself. `None` when the count is not known at compile time
    (a category count that is a field reference), letting the resolver bound
    the index instead.
    """
    style = spec.display_style
    if style in {"bar_graph", "histogram"}:
        return len(spec.categories)
    if style in {"line_plot", "dot_plot"}:
        return len(spec.values)
    if style == "box_plot":
        return 1
    return None

_DECLARED_PATHS = {"rectangle_measurement": {"perimeter"}}

_DRAWABLE_TARGETS = {"rectangle_measurement": {None}}
_MOVABLE_TARGETS = {"rectangle_measurement": {None}}
_TRANSFORM_COMPATIBILITY = {"rectangle_measurement": {"rectangle_measurement"}}
_ITEM_CALLOUT_ANCHORS = {"bottom"}

#: Upper bound on segments the percent-sweep may emit. Each swept segment is a
#: `focus` role change with its own `at_seconds` (see `_slot_count` for
#: percent strategies), so the sweep alone contributes N timeline entries
#: against the 40-action cap. Values above this cap compiled the plan but
#: later failed with `too_many_timeline_actions` at scheduling; refusing them
#: up front turns a hard-to-diagnose scheduler failure into a clear compile
#: error naming the sweep as the cause.
_MAX_PERCENT_SWEEP_SEGMENTS = 30


def compile_teaching_plan(plan, answer_expression, known_fields, context):
    compile_expression(answer_expression, known_fields)
    for expression in expressions_from_plan(plan):
        compile_expression(expression, known_fields)
    validate_unique_visual_refs(plan)
    validate_target_refs(plan)
    validate_strategy_compatibility(plan, answer_expression)
    validate_unit_rate_value_range(plan, known_fields)
    validate_pair_elimination_answer(plan, answer_expression)
    visuals, relations, beats = expand_beats(plan, answer_expression)
    if plan.strategy == "rotation":
        # `expand_beats` builds every `ProgramVisual` through the generic,
        # strategy-blind `_program_visual` mapping (`beat_expander.py`) --
        # branching on `rotation` there is Task 5's `RotateAction` staging
        # work, and doing it early here would falsely retire
        # `test_every_supported_strategy_has_expander_behavior`'s tracked gap.
        # So the frozen frames are stitched onto the already-built
        # `CoordinatePlaneProgramVisual` as a post-processing step instead.
        visuals = _apply_rotation_frames(plan, visuals)
    recipe = resolve_style_recipe(
        seed=plan.variation_seed,
        visual_kind=plan.primary_visual.kind,
        strategy=plan.strategy,
        concept_family=context.concept_family,
        grade_band=context.grade_band,
        content_density=classify_content_density(visuals),
    )
    timeline, total = schedule_beats(beats)
    if len(timeline) > 40:
        _fail(
            "too_many_timeline_actions", "timeline", "at most 40 timed actions",
            str(len(timeline)), "simplify custom actions or combine semantic beats",
        )
    return SceneProgramDocument(
        scene_version=3,
        visuals=visuals,
        relations=relations,
        timeline=timeline,
        total_duration_seconds=total,
        variation_seed=plan.variation_seed,
        style_recipe=StyleRecipeDocument(**asdict(recipe)),
        answer_anchor=_answer_anchor(plan),
    )


def _apply_rotation_frames(plan, visuals):
    """Stitch `_compute_rotation_frames`'s output onto the primary visual's
    already-built `CoordinatePlaneProgramVisual` (M22).

    `_validate_rotation_compatibility` already ran `_compute_rotation_frames`
    once during `validate_strategy_compatibility` -- any raise happens there,
    long before `expand_beats` runs. Re-running it here is cheap (at most
    4 iterations over a handful of vertices) and it's the only way to hand the
    frozen frames to a `ProgramVisual` that `expand_beats` built generically.
    """
    frames = _compute_rotation_frames(plan.primary_visual)
    primary_ref = plan.primary_visual.ref
    return [
        visual.model_copy(update={"rotation_frames": frames})
        if visual.ref == primary_ref else visual
        for visual in visuals
    ]


def expressions_from_plan(plan):
    for spec in _visual_specs(plan):
        for field_name in _EXPRESSION_FIELDS[spec.kind]:
            value = getattr(spec, field_name)
            yield from value if isinstance(value, list) else (value,)
        for field_name in _OPTIONAL_EXPRESSION_FIELDS.get(spec.kind, ()):
            value = getattr(spec, field_name, None)
            if value is not None:
                yield value
        if spec.kind == "coordinate_plane":
            for point in spec.points:
                yield point.x
                yield point.y
        if spec.kind == "data_display":
            yield from _data_display_expressions(spec)


def _data_display_expressions(spec):
    """Every ExpressionNode a data_display carries, in schema-declared order.

    Kept out of `_EXPRESSION_FIELDS` because the fields differ by
    `display_style` -- a flat mapping cannot express "expose `values` only for
    line_plot / dot_plot"; hard-coding the union would validate expressions
    the plan schema will reject at model_validator time anyway.
    """
    for category in spec.categories:
        yield category.count
    yield from spec.values
    for bound in (spec.axis_min, spec.axis_max):
        if bound is not None:
            yield bound
    if spec.summary is not None:
        yield spec.summary.minimum
        yield spec.summary.q1
        yield spec.summary.median
        yield spec.summary.q3
        yield spec.summary.maximum


def validate_unique_visual_refs(plan):
    refs = set()
    for index, spec in enumerate(_visual_specs(plan)):
        if spec.ref in refs:
            _fail(
                "duplicate_visual_ref", f"visuals[{index}].ref", "a unique visual reference",
                spec.ref, "rename the visual so every reference is unique",
            )
        refs.add(spec.ref)


def validate_target_refs(plan):
    specs = {spec.ref: spec for spec in _visual_specs(plan)}
    for beat_index, beat in enumerate(plan.beats):
        for target_index, target in enumerate(beat.targets):
            _validate_target(target, specs, f"beats[{beat_index}].targets[{target_index}]")
        for action_index, action in enumerate(beat.custom_actions):
            path = f"beats[{beat_index}].custom_actions[{action_index}]"
            if action.kind == "reveal":
                for target_index, target in enumerate(action.targets):
                    _validate_target(target, specs, f"{path}.targets[{target_index}]")
            elif action.kind in {"emphasize", "dim", "restore"}:
                _validate_target(action.target, specs, f"{path}.target")
            elif action.kind == "draw":
                spec = _validate_target(action.target, specs, f"{path}.target")
                _validate_compatible_target(
                    action.target, spec, _DRAWABLE_TARGETS, "incompatible_draw_target", path,
                    "a drawable whole visual", "draw a whole visual of a drawable kind",
                )
            elif action.kind == "move":
                spec = _validate_target(action.target, specs, f"{path}.target")
                _validate_compatible_target(
                    action.target, spec, _MOVABLE_TARGETS, "incompatible_move_target", path,
                    "a movable whole visual", "move a whole visual of a movable kind",
                )
            elif action.kind == "transform":
                source = _validate_target(action.source, specs, f"{path}.source")
                target = _validate_target(action.target, specs, f"{path}.target")
                compatible_kinds = _TRANSFORM_COMPATIBILITY.get(source.kind, set())
                if (
                    action.source.part is not None
                    or action.target.part is not None
                    or target.kind not in compatible_kinds
                ):
                    _fail(
                        "incompatible_transform_target", path,
                        "compatible whole source and target visuals",
                        f"{source.kind}:{target.kind}",
                        _enumerate_legal(
                            compatible_kinds,
                            "transform between whole visuals of a compatible kind",
                            "this visual kind cannot be transformed",
                        ),
                    )
            elif action.kind == "callout":
                spec = _validate_target(action.target, specs, f"{path}.target")
                _validate_callout_anchor(action.target, spec, path)

            if action.kind in {"trace", "move"}:
                path_ref = action.path_ref
                path_spec = _validate_path_ref(path_ref, specs, f"{path}.path_ref")
                if action.kind == "move" and path_spec.ref != action.target.visual_ref:
                    _fail(
                        "path_target_mismatch", f"{path}.path_ref", "a path owned by the moved visual",
                        path_ref, "use a declared path on the move target",
                    )


_MAX_REGROUP_CELLS = 30
#: Room under the 40-action timeline cap for reveals, focus/derive role
#: changes, the answer's own actions, and the conclusion, once the organize
#: beat has emitted one `set_role` per cell.


def validate_strategy_compatibility(plan, answer_expression=None):
    supported = _SUPPORTED_STRATEGIES[plan.primary_visual.kind]
    if plan.strategy not in supported:
        _fail(
            "incompatible_strategy", "strategy", "a strategy supported by the visual kind",
            f"{plan.strategy}:{plan.primary_visual.kind}",
            _enumerate_legal(
                supported, "select a compatible strategy",
                "this visual kind supports no strategies",
            ),
        )
    if plan.strategy == "pair_elimination" and len(plan.primary_visual.values) % 2 == 0:
        _fail(
            "pair_elimination_requires_odd_values", "primary_visual.values",
            "an odd number of ordered values", str(len(plan.primary_visual.values)),
            "use an odd-sized collection with one middle item",
        )
    if plan.strategy == "regroup":
        _validate_regroup_compatibility(plan)
    if plan.strategy == "magnitude_comparison":
        _validate_magnitude_comparison_compatibility(plan)
    if plan.strategy == "inverse_operation":
        _validate_inverse_operation_compatibility(plan)
    if plan.strategy == "ray_shade":
        _validate_ray_shade_compatibility(plan)
    if plan.strategy == "boundary_trace":
        _validate_boundary_trace_compatibility(plan)
    if plan.strategy == "signed_hop":
        _validate_signed_hop_compatibility(plan)
    if plan.strategy == "distance_from_zero":
        _validate_distance_from_zero_compatibility(plan)
    if plan.strategy == "equivalence_align":
        _validate_equivalence_align_compatibility(plan)
    if plan.strategy == "common_denominator_bridge":
        _validate_common_denominator_bridge_compatibility(plan, answer_expression)
    if plan.strategy == "percent_of_whole":
        _validate_percent_of_whole_compatibility(plan)
    if plan.strategy == "percent_change":
        _validate_percent_change_compatibility(plan)
    if plan.strategy == "rotation":
        _validate_rotation_compatibility(plan)


def _validate_inverse_operation_compatibility(plan):
    """Require the bar to declare the equation's partition at compile time.

    `inverse_operation` teaches "peel off the known constant, then divide the
    remainder into k equal x-parts". The compiler stages that partition on
    the bar directly, so the segment counts have to be knowable up front:
    `constant`, `coefficient`, and `maximum` must be literals, `0 < constant
    < maximum` (a non-empty x-region and a non-empty constant-region), and
    `(maximum - constant) % coefficient == 0` (each x-part is a whole
    segment count).
    """
    spec = plan.primary_visual
    maximum = _literal_integer(spec.maximum)
    if maximum is None:
        _fail(
            "inverse_operation_requires_literal_partition", "primary_visual",
            "a literal bar maximum so the compiler can partition the segments",
            f"bar maximum={_describe_expression(spec.maximum)}",
            "set maximum to a literal integer, or use a different strategy",
        )
    if spec.constant is None or spec.coefficient is None:
        _fail(
            "inverse_operation_requires_partition_fields", "primary_visual",
            "bar.constant and bar.coefficient declaring the equation's known "
            "addend and x-coefficient",
            f"constant={spec.constant is not None}, "
            f"coefficient={spec.coefficient is not None}",
            "set bar.constant (the known addend) and bar.coefficient (how many "
            "equal x-parts) as literal integers",
        )
    constant = _literal_integer(spec.constant)
    coefficient = _literal_integer(spec.coefficient)
    if constant is None or coefficient is None:
        _fail(
            "inverse_operation_requires_literal_partition", "primary_visual",
            "literal bar.constant and bar.coefficient",
            f"constant={_describe_expression(spec.constant)}, "
            f"coefficient={_describe_expression(spec.coefficient)}",
            "set both fields to literal integers so the compiler can partition "
            "the segments at compile time",
        )
    if not 0 < constant < maximum:
        _fail(
            "inverse_operation_invalid_partition", "primary_visual",
            "0 < constant < maximum so both x_region and constant_region are non-empty",
            f"constant={constant}, maximum={maximum}",
            "reduce constant below maximum and keep it positive",
        )
    if coefficient < 1:
        _fail(
            "inverse_operation_invalid_partition", "primary_visual",
            "coefficient >= 1",
            f"coefficient={coefficient}",
            "set coefficient to 1 for a one-step equation, >= 2 for a two-step",
        )
    if (maximum - constant) % coefficient != 0:
        _fail(
            "inverse_operation_invalid_partition", "primary_visual",
            "(maximum - constant) divisible by coefficient so each x_part is a "
            "whole segment count",
            f"maximum={maximum}, constant={constant}, coefficient={coefficient}",
            "adjust the equation so (maximum - constant) is a multiple of coefficient",
        )


def _validate_ray_shade_compatibility(plan):
    """Require the number_line to declare the inequality's boundary + direction.

    `ray_shade` teaches "boundary at b, shade the direction the inequality
    points". The compiler stages an open/closed circle at the boundary and
    a thick ray from the boundary to the appropriate endpoint, so all three
    fields must be present -- and `boundary` a literal inside
    `[minimum, maximum]` -- for the measurer to project the boundary onto
    the fixed +/-2.75 line.
    """
    spec = plan.primary_visual
    missing = [
        name for name in ("boundary", "boundary_kind", "ray_direction")
        if getattr(spec, name) is None
    ]
    if missing:
        _fail(
            "ray_shade_requires_boundary_fields", "primary_visual",
            "number_line.boundary, boundary_kind, and ray_direction all set",
            f"missing {', '.join(missing)}",
            "declare boundary (the inequality's cutoff value), boundary_kind "
            "('open' for strict / 'closed' for inclusive), and ray_direction "
            "('left' or 'right')",
        )
    boundary_lit = _literal_number(spec.boundary)
    minimum_lit = _literal_number(spec.minimum)
    maximum_lit = _literal_number(spec.maximum)
    if boundary_lit is None or minimum_lit is None or maximum_lit is None:
        _fail(
            "ray_shade_requires_literal_boundary", "primary_visual",
            "literal boundary/minimum/maximum so the boundary projects to a "
            "definite line position",
            f"boundary={_describe_expression(spec.boundary)}, "
            f"minimum={_describe_expression(spec.minimum)}, "
            f"maximum={_describe_expression(spec.maximum)}",
            "set all three to literal numbers, or use a different strategy",
        )
    if not minimum_lit <= boundary_lit <= maximum_lit:
        _fail(
            "ray_shade_boundary_out_of_range", "primary_visual.boundary",
            f"a boundary inside [{minimum_lit}, {maximum_lit}]",
            f"boundary={boundary_lit}",
            "move the boundary inside the number_line's declared range",
        )


def _literal_number(expression):
    """A literal expression's numeric value, or None if not a literal."""
    if expression is None or expression.node != "literal":
        return None
    return float(expression.value)


def _validate_boundary_trace_compatibility(plan):
    """`boundary_trace` teaches perimeter on the rectangle; no foreign scale.

    The perimeter's derivation IS the traced boundary on the rectangle, so
    admitting a structural companion of a DIFFERENT kind (e.g. a `number_line`
    beside the rectangle) displaces the rectangle downward and invites
    off-lesson callouts anchored to a scale the lesson never uses. A
    same-kind rectangle supporting visual stays legal because it is the
    transform target (`_TRANSFORM_COMPATIBILITY[rectangle_measurement]`
    admits only rectangle_measurement), and label supporting_visuals stay
    legal because they overlay the frame with text rather than claiming
    their own placed region.
    """
    primary_kind = plan.primary_visual.kind
    offending = [
        spec for spec in plan.supporting_visuals
        if spec.kind in STRUCTURE_VISUAL_KINDS and spec.kind != primary_kind
    ]
    if offending:
        kinds = sorted({spec.kind for spec in offending})
        _fail(
            "boundary_trace_forbids_foreign_structure_supporting_visual",
            "supporting_visuals",
            f"no structural supporting visual of a kind other than {primary_kind!r}; "
            "boundary_trace is taught on the rectangle alone (label and "
            "same-kind supporting_visuals are still allowed)",
            f"foreign structural supporting visual(s): {', '.join(kinds)}",
            "remove the foreign structural supporting visual; the perimeter "
            "trace on the rectangle is the whole derivation",
        )


def _validate_regroup_compatibility(plan):
    spec = plan.primary_visual
    if spec.kind == "grid":
        rows = _literal_integer(spec.rows)
        columns = _literal_integer(spec.columns)
        if rows is None or columns is None:
            _fail(
                "regroup_requires_literal_dimensions", "primary_visual",
                "literal rows and columns so the compiler can walk the grid",
                f"grid rows={_describe_expression(spec.rows)}, "
                f"columns={_describe_expression(spec.columns)}",
                "set rows and columns to literal integers, or use a different strategy",
            )
        cells = rows * columns
    else:  # object_set
        count = _literal_integer(spec.count)
        if count is None:
            _fail(
                "regroup_requires_literal_dimensions", "primary_visual",
                "a literal count so the compiler can walk the object set",
                f"object_set count={_describe_expression(spec.count)}",
                "set count to a literal integer, or use a different strategy",
            )
        cells = count
    if cells > _MAX_REGROUP_CELLS:
        _fail(
            "regroup_too_many_cells", "primary_visual",
            f"a regroup layout of at most {_MAX_REGROUP_CELLS} cells",
            f"{cells} cells", "shrink the primary visual so regroup fits under the "
            "40-action timeline cap",
        )
    _require_owned_regroup_beat(plan)


def _require_owned_regroup_beat(plan):
    beat_id = regroup_beat_id(plan)
    if beat_id is None:
        _fail(
            "regroup_requires_organize_beat", "beats",
            f"an organize beat targeting {plan.primary_visual.ref!r}, "
            "which the compiler stages the row walk on",
            "no organize beat names the primary visual",
            "add an organize beat whose targets include the primary visual",
        )
    # Same-beat reveal + role changes puts the reveal action in the first
    # scheduled slot, splitting a row across slots (see `_slot_count`). An
    # earlier beat must reveal the primary visual AS A WHOLE, so
    # `_reveal_unrevealed` in the walk beat sees `(ref, None, None)` in
    # `revealed` and emits no `RevealAction`. Part-level targets
    # (`array.cell[0]`) only reveal that part -- the whole grid is still
    # unrevealed at the walk beat and its `_reveal_unrevealed` still fires.
    for beat in plan.beats:
        if beat.id == beat_id:
            _fail(
                "regroup_requires_primary_revealed_before_organize", "beats",
                "an earlier beat that reveals the primary visual (whole) so "
                "the organize beat emits only role changes",
                f"organize beat {beat_id!r} is the first beat that reveals "
                f"{plan.primary_visual.ref!r} as a whole",
                "add an orient or reveal beat whose target is the primary visual "
                "at whole granularity (no part, no index) before the organize beat",
            )
        if _reveals_primary_whole(beat, plan.primary_visual.ref):
            return


def _reveals_primary_whole(beat, primary_ref):
    """True when this beat causes `(primary_ref, None, None)` to be revealed.

    Mirrors `beat_expander._is_revealed`: a whole-visual reveal covers every
    part, but a part-level reveal never covers the whole. Both `beat.targets`
    (which `_reveal_unrevealed` reveals) and a custom `RevealRequest` are
    checked here.
    """
    if any(
        target.visual_ref == primary_ref
        and target.part is None
        and target.index is None
        for target in beat.targets
    ):
        return True
    for action in beat.custom_actions:
        if action.kind != "reveal":
            continue
        if any(
            target.visual_ref == primary_ref
            and target.part is None
            and target.index is None
            for target in action.targets
        ):
            return True
    return False


def _validate_magnitude_comparison_compatibility(plan):
    spec = plan.primary_visual
    if spec.kind == "bar":
        maximum = _literal_integer(spec.maximum)
        if maximum == 100:
            # A bar drawn at maximum 100 IS a percent bar: the count of
            # segments and the ratio are the same number, so a sweep here
            # is teaching "N percent of the whole" whether the plan says so
            # or not. `percent_of_whole` names that intent explicitly and
            # gates on a value in [1, 99]; `magnitude_comparison` would let
            # a plan claim "sweep to 40" for what a learner reads as "40%".
            # Steer the plan to the strategy that matches the semantic.
            _fail(
                "magnitude_comparison_on_percent_bar",
                "strategy",
                "percent_of_whole when the bar's maximum is 100 (percent semantic)",
                f"magnitude_comparison on bar with maximum=100",
                "use percent_of_whole for a percent-of-whole bar, or lower maximum",
            )
        value = _literal_integer(spec.value)
        if value is None:
            _fail(
                "magnitude_comparison_requires_literal_bar_value", "primary_visual.value",
                "a literal whole-number bar value so the sweep addresses "
                "specific segments",
                _describe_expression(spec.value),
                "set value to a literal integer, or use a different strategy",
            )
        if value < 1:
            # An empty sweep leaves the beat with no actions and falls through
            # to a whole-visual focus -- the same shape as `group_reveal`, and
            # the exact bug #66 targets. A bar with value 0 has no magnitude to
            # animate; use a different strategy.
            _fail(
                "magnitude_comparison_requires_positive_bar_value", "primary_visual.value",
                "a bar value of at least 1 so the sweep animates at least one segment",
                str(value),
                "use a different strategy for a zero-magnitude bar, or raise value",
            )
    else:  # number_line
        if not spec.markers:
            _fail(
                "magnitude_comparison_requires_at_least_one_marker", "primary_visual.markers",
                "at least one marker so the sweep animates at least one part",
                "no markers",
                "declare the markers you want swept, or use a different strategy",
            )
        for index, marker in enumerate(spec.markers):
            if marker.node != "literal":
                _fail(
                    "magnitude_comparison_requires_literal_markers",
                    f"primary_visual.markers[{index}]",
                    "a literal marker position so the sweep sorts left to right",
                    _describe_expression(marker),
                    "set every marker to a literal number, or use a different strategy",
                )
        # magnitude_comparison sweeps markers left-to-right and reads that order
        # as "greater magnitude". On a signed range that reading is wrong: -5
        # sits left of 2 but has the greater magnitude, so the sweep would teach
        # the opposite. Refuse a plan whose declared span crosses (or lives in)
        # the negatives; the M6 strategies `signed_hop` and `distance_from_zero`
        # handle signed number lines.
        minimum = _literal_number(spec.minimum)
        if minimum is not None and minimum < 0:
            _fail(
                "magnitude_comparison_requires_nonnegative_range", "primary_visual.minimum",
                "a number_line whose minimum is at least 0",
                _describe_expression(spec.minimum),
                "raise minimum to 0 or above, or use signed_hop / distance_from_zero for a signed line",
            )
        for index, marker in enumerate(spec.markers):
            if float(marker.value) < 0:
                _fail(
                    "magnitude_comparison_requires_nonnegative_markers",
                    f"primary_visual.markers[{index}]",
                    "markers on a nonnegative number_line",
                    _describe_expression(marker),
                    "drop the negative marker, or use signed_hop / distance_from_zero for a signed line",
                )
    _require_owned_sweep_beat(plan)


def _validate_signed_hop_compatibility(plan):
    """`signed_hop` teaches directed motion on a signed number_line.

    An addition or subtraction of signed integers reads as a hop that goes
    right for a positive addend and left for a negative one. The line has to
    carry a signed context -- either its minimum is negative or one of its
    markers is negative -- or the strategy is indistinguishable from a
    positive-only walk that `magnitude_comparison` already covers. Two markers
    is the floor: one hop needs a starting point and an ending point.
    """
    spec = plan.primary_visual
    if spec.kind != "number_line":
        # `_SUPPORTED_STRATEGIES` already rejects a non-number_line primary.
        return
    if len(spec.markers) < 2:
        _fail(
            "signed_hop_requires_at_least_two_markers", "primary_visual.markers",
            "at least two markers so the hop has a start and an end",
            f"{len(spec.markers)} marker(s)",
            "declare the start and end (and any intermediate) of the hop, "
            "or use a different strategy",
        )
    for index, marker in enumerate(spec.markers):
        if marker.node != "literal":
            _fail(
                "signed_hop_requires_literal_markers",
                f"primary_visual.markers[{index}]",
                "a literal marker position so the hop sequence is fixed at compile time",
                _describe_expression(marker),
                "set every marker to a literal number, or use a different strategy",
            )
    minimum = _literal_number(spec.minimum)
    has_negative_marker = any(float(marker.value) < 0 for marker in spec.markers)
    if (minimum is None or minimum >= 0) and not has_negative_marker:
        _fail(
            "signed_hop_requires_signed_context", "primary_visual",
            "a signed number_line (negative minimum or a negative marker)",
            f"minimum={_describe_expression(spec.minimum)}, "
            f"markers={[_describe_expression(m) for m in spec.markers]}",
            "widen the range to include negatives or add a negative marker, "
            "or use magnitude_comparison for a nonnegative line",
        )


def _validate_distance_from_zero_compatibility(plan):
    """`distance_from_zero` annotates a value's distance to the origin.

    The teaching move is "how far is this from 0", which only reads when 0
    is drawn on the line and at least one other marker sits away from it.
    A plan without a 0 marker cannot land the annotation on the origin, and
    a plan with only 0 has nothing to measure distance to.
    """
    spec = plan.primary_visual
    if spec.kind != "number_line":
        return
    literal_markers = []
    for index, marker in enumerate(spec.markers):
        if marker.node != "literal":
            _fail(
                "distance_from_zero_requires_literal_markers",
                f"primary_visual.markers[{index}]",
                "a literal marker position so the origin and the measured point are fixed",
                _describe_expression(marker),
                "set every marker to a literal number, or use a different strategy",
            )
        literal_markers.append(float(marker.value))
    if 0.0 not in literal_markers:
        _fail(
            "distance_from_zero_requires_zero_marker", "primary_visual.markers",
            "a marker at 0 so the origin is drawn on the line",
            f"markers={literal_markers}",
            "add a literal marker at 0, or use a different strategy",
        )
    if not any(value != 0.0 for value in literal_markers):
        _fail(
            "distance_from_zero_requires_nonzero_marker", "primary_visual.markers",
            "at least one nonzero marker so there is a distance to measure",
            f"markers={literal_markers}",
            "add the value whose distance from zero the lesson teaches, "
            "or use a different strategy",
        )


def _validate_equivalence_align_compatibility(plan):
    """Fraction equivalence needs a second partition of the same whole.

    The strategy teaches "these two partitions describe the same amount": one
    partition alone shows only its own fraction, and the alignment is what the
    lesson turns on. The compiler enforces the shape here so a plan that names
    the strategy but omits the equivalent partition fails at compile time
    rather than as a decorative animation later.
    """
    if plan.primary_visual.kind != "partition":
        # `_SUPPORTED_STRATEGIES` already rejects a non-partition primary, so
        # reaching here means the supported-strategy check let the plan through
        # for a kind that should not carry this strategy.
        return
    supporting_partitions = [
        spec for spec in plan.supporting_visuals if spec.kind == "partition"
    ]
    if len(supporting_partitions) != 1:
        _fail(
            "equivalence_align_requires_one_supporting_partition", "supporting_visuals",
            "exactly one supporting partition visual carrying the equivalent fraction",
            f"{len(supporting_partitions)} supporting partition(s)",
            "add one supporting partition whose parts count is the equivalent denominator, "
            "or use a different strategy",
        )
    primary_fraction = _partition_fraction(plan.primary_visual, "primary_visual")
    support_fraction = _partition_fraction(
        supporting_partitions[0],
        f"supporting_visuals.{supporting_partitions[0].ref}",
    )
    _require_same_whole(
        [plan.primary_visual, *supporting_partitions], "equivalence_align",
    )
    if primary_fraction != support_fraction:
        _fail(
            "equivalence_align_requires_equal_fractions",
            f"supporting_visuals.{supporting_partitions[0].ref}",
            "a supporting partition whose shaded/parts fraction equals the primary's",
            f"primary {primary_fraction.numerator}/{primary_fraction.denominator} "
            f"vs supporting {support_fraction.numerator}/{support_fraction.denominator}",
            "set the supporting partition's shaded and parts so shaded/parts equals "
            "the primary's, or use a different strategy",
        )
    _require_owned_equivalence_align_beat(plan)


def _require_owned_equivalence_align_beat(plan):
    """`equivalence_align` needs a focus/derive beat that targets BOTH partitions.

    `equivalence_align_beat_id` selects the beat that owns the alignment walk;
    if none exists, `_beat_kind_actions` falls through to the generic role
    change and the shaded-wedge focus never lands. `check_strategy_affordance`
    would then see a compiled plan that never actually animates the alignment,
    so it is refused here at compile time instead.
    """
    if equivalence_align_beat_id(plan) is None:
        supporting_partitions = [
            spec for spec in plan.supporting_visuals if spec.kind == "partition"
        ]
        support_ref = supporting_partitions[0].ref if supporting_partitions else "<supporting>"
        _fail(
            "equivalence_align_requires_alignment_beat", "beats",
            f"a focus or derive beat targeting both {plan.primary_visual.ref!r} "
            f"and {support_ref!r}, which the compiler stages the alignment walk on",
            "no focus/derive beat targets both partitions together",
            "add a focus or derive beat whose targets include both partitions",
        )


def _validate_common_denominator_bridge_compatibility(plan, answer_expression):
    """Fraction arithmetic across unlike denominators needs a bridge partition.

    The lesson has five partitions on-screen: the two original operands (their
    unlike denominators), each operand's refined form on the LCD (the
    intermediate 3/6 and 2/6 states of a 1/2 + 1/3 lesson), and the LCD bridge
    that carries the combined result. The refined partitions are what make the
    animation teach the refinement itself rather than only "here are two
    fractions, here is their sum" -- without them, the frame jumps from
    unlike-denominator operands to the combined bridge and the LCD reasoning
    is invisible.

    The order in `supporting_visuals` is fixed: second_operand, refined_a,
    refined_b, bridge. Refining `refined_a` from `primary_visual` and
    `refined_b` from `second_operand` mirrors the operand order the answer
    expression is required to match.
    """
    if plan.primary_visual.kind != "partition":
        return
    supporting_partitions = [
        spec for spec in plan.supporting_visuals if spec.kind == "partition"
    ]
    if len(supporting_partitions) != 4:
        _fail(
            "common_denominator_bridge_requires_four_supporting_partitions",
            "supporting_visuals",
            "exactly four supporting partition visuals in order: "
            "second_operand, refined_a (primary on LCD), refined_b (second on LCD), bridge",
            f"{len(supporting_partitions)} supporting partition(s)",
            "declare the second operand, each operand's LCD-refined partition, and "
            "the LCD bridge as supporting partition visuals in that order, "
            "or use a different strategy",
        )
    second_operand, refined_a, refined_b, bridge = supporting_partitions
    primary_parts = _literal_integer(plan.primary_visual.parts)
    second_parts = _literal_integer(second_operand.parts)
    refined_a_parts = _literal_integer(refined_a.parts)
    refined_b_parts = _literal_integer(refined_b.parts)
    bridge_parts = _literal_integer(bridge.parts)
    if (
        primary_parts is None or second_parts is None or bridge_parts is None
        or refined_a_parts is None or refined_b_parts is None
    ):
        _fail(
            "common_denominator_bridge_requires_literal_denominators",
            "supporting_visuals",
            "literal parts counts on all five partitions so the compiler can verify the LCD",
            f"primary parts={_describe_expression(plan.primary_visual.parts)}, "
            f"second parts={_describe_expression(second_operand.parts)}, "
            f"refined_a parts={_describe_expression(refined_a.parts)}, "
            f"refined_b parts={_describe_expression(refined_b.parts)}, "
            f"bridge parts={_describe_expression(bridge.parts)}",
            "set every partition's parts to a literal integer, or use a different strategy",
        )
    expected_lcd = _lcm(primary_parts, second_parts)
    if bridge_parts != expected_lcd:
        _fail(
            "common_denominator_bridge_requires_lcd",
            f"supporting_visuals.{bridge.ref}.parts",
            f"a bridge partition of {expected_lcd} parts (the LCD of {primary_parts} and {second_parts})",
            f"bridge parts={bridge_parts}",
            f"set the bridge partition's parts to {expected_lcd}, "
            "or use a different strategy",
        )
    for spec, spec_parts, operand_ref, operand_parts in (
        (refined_a, refined_a_parts, plan.primary_visual.ref, primary_parts),
        (refined_b, refined_b_parts, second_operand.ref, second_parts),
    ):
        if spec_parts != expected_lcd:
            _fail(
                "common_denominator_bridge_requires_refined_lcd_parts",
                f"supporting_visuals.{spec.ref}.parts",
                f"a refined partition of {expected_lcd} parts "
                f"(the LCD of {primary_parts} and {second_parts})",
                f"{spec.ref} parts={spec_parts}",
                f"set {spec.ref}.parts to {expected_lcd}, or use a different strategy",
            )
    _require_same_whole(
        [plan.primary_visual, second_operand, refined_a, refined_b, bridge],
        "common_denominator_bridge",
    )
    primary_fraction = _partition_fraction(plan.primary_visual, "primary_visual")
    second_fraction = _partition_fraction(
        second_operand, f"supporting_visuals.{second_operand.ref}",
    )
    refined_a_fraction = _partition_fraction(
        refined_a, f"supporting_visuals.{refined_a.ref}",
    )
    refined_b_fraction = _partition_fraction(
        refined_b, f"supporting_visuals.{refined_b.ref}",
    )
    bridge_fraction = _partition_fraction(
        bridge, f"supporting_visuals.{bridge.ref}",
    )
    for spec, refined_fraction, operand_fraction in (
        (refined_a, refined_a_fraction, primary_fraction),
        (refined_b, refined_b_fraction, second_fraction),
    ):
        if refined_fraction != operand_fraction:
            _fail(
                "common_denominator_bridge_refined_must_equal_operand",
                f"supporting_visuals.{spec.ref}.shaded",
                f"a refined partition equal to its operand ({operand_fraction}) "
                f"expressed with denominator {expected_lcd}",
                f"{spec.ref} = {refined_fraction}",
                f"set {spec.ref}.shaded so shaded/{expected_lcd} = {operand_fraction}, "
                "or use a different strategy",
            )
    _require_bridge_matches_answer(
        answer_expression=answer_expression, bridge_ref=bridge.ref,
        primary_fraction=primary_fraction, second_fraction=second_fraction,
        bridge_fraction=bridge_fraction,
    )
    _require_owned_common_denominator_bridge_beat(plan)


def _require_bridge_matches_answer(
    *, answer_expression, bridge_ref, primary_fraction, second_fraction, bridge_fraction,
):
    """The bridge is the RESULT of the specific operation `answer_expression` names.

    A "sum or difference either way" acceptance let an addition answer compile
    with a difference bridge, so the animation contradicted the arithmetic on
    screen. Pin the accepted operator (add or subtract) and the operand order
    to `answer_expression` itself: the bridge must equal `primary op second`
    exactly, using the operator drawn from the answer and the operands in the
    same order the primary/second partitions declare them.
    """
    if answer_expression is None or answer_expression.node not in {"add", "subtract"}:
        _fail(
            "common_denominator_bridge_requires_additive_answer",
            "answer_expression",
            "an add or subtract expression combining the two operand fractions",
            _describe_expression(answer_expression) if answer_expression is not None else "none",
            "set answer_expression to an add or subtract of the two operand fractions, "
            "or use a different strategy",
        )
    operand_fractions = [_answer_operand_fraction(op) for op in answer_expression.operands]
    if len(operand_fractions) != 2 or any(f is None for f in operand_fractions):
        _fail(
            "common_denominator_bridge_answer_operands_must_be_literal_fractions",
            "answer_expression.operands",
            "two literal FractionNode operands so the compiler can match them to the partitions",
            _describe_expression(answer_expression),
            "write answer_expression as add/subtract of two fraction(literal, literal) operands",
        )
    answer_a, answer_b = operand_fractions
    if (answer_a, answer_b) != (primary_fraction, second_fraction):
        _fail(
            "common_denominator_bridge_operands_must_match_partitions",
            "answer_expression.operands",
            f"operand fractions matching primary ({primary_fraction}) and "
            f"second ({second_fraction}) in that order",
            f"answer operands {answer_a}, {answer_b}",
            "reorder answer_expression's operands so operand[0] equals the primary "
            "partition and operand[1] equals the second supporting partition",
        )
    if answer_expression.node == "add":
        expected = primary_fraction + second_fraction
        operator_label = "operand_a + operand_b"
    else:
        expected = primary_fraction - second_fraction
        operator_label = "operand_a - operand_b"
        if expected < 0:
            _fail(
                "common_denominator_bridge_subtract_must_be_nonnegative",
                "answer_expression",
                "a subtraction whose result is >= 0 (bridge cannot shade a negative fraction)",
                f"{primary_fraction} - {second_fraction} = {expected}",
                "swap the operand order or use a different strategy",
            )
    if bridge_fraction != expected:
        _fail(
            "common_denominator_bridge_result_mismatch",
            f"supporting_visuals.{bridge_ref}",
            f"a bridge shaded/parts fraction equal to {operator_label} ({expected})",
            f"primary {primary_fraction}, second {second_fraction}, bridge {bridge_fraction}",
            "set the bridge partition's shaded so shaded/parts equals the answer_expression's "
            "operation on the operands' fractions, or use a different strategy",
        )


def _answer_operand_fraction(operand):
    """Read a FractionNode(literal, literal) as a `Fraction`, else None."""
    if getattr(operand, "node", None) != "fraction":
        return None
    numerator, denominator = operand.operands
    if numerator.node != "literal" or denominator.node != "literal":
        return None
    if not float(numerator.value).is_integer() or not float(denominator.value).is_integer():
        return None
    denom = int(denominator.value)
    if denom == 0:
        return None
    return Fraction(int(numerator.value), denom)


def _require_owned_common_denominator_bridge_beat(plan):
    """The bridge walk needs a focus/derive beat that targets the bridge partition.

    `common_denominator_bridge_beat_id` returns None otherwise, and
    `_beat_kind_actions` falls through to the generic role change so the
    refined-onto-LCD walk never lands. Refused here so a plan that could not
    animate the bridge fails at compile time rather than as a decorative frame.
    """
    if common_denominator_bridge_beat_id(plan) is None:
        bridge_ref = None
        partitions = [spec for spec in plan.supporting_visuals if spec.kind == "partition"]
        if len(partitions) >= 4:
            bridge_ref = partitions[3].ref
        target_ref = bridge_ref if bridge_ref is not None else "<bridge>"
        _fail(
            "common_denominator_bridge_requires_bridge_beat", "beats",
            f"a focus or derive beat targeting {target_ref!r}, "
            "which the compiler stages the bridge walk on",
            "no focus/derive beat names the bridge partition",
            "add a focus or derive beat whose targets include the bridge partition",
        )


def _partition_fraction(spec, path):
    parts = _literal_integer(spec.parts)
    shaded = _literal_integer(spec.shaded)
    if parts is None or shaded is None:
        _fail(
            "partition_requires_literal_shaded_and_parts", path,
            "a partition with literal shaded and parts so the compiler can compare fractions",
            f"shaded={_describe_expression(spec.shaded)}, parts={_describe_expression(spec.parts)}",
            "set shaded and parts to literal integers, or use a different strategy",
        )
    if parts <= 0:
        _fail(
            "partition_requires_positive_parts", f"{path}.parts",
            "a partition with at least one part", str(parts),
            "raise parts to a positive integer",
        )
    if shaded < 0 or shaded > parts:
        _fail(
            "partition_shaded_out_of_range", f"{path}.shaded",
            f"a shaded count between 0 and {parts}", str(shaded),
            f"set shaded between 0 and {parts}",
        )
    return Fraction(shaded, parts)


def _require_same_whole(specs, strategy):
    wholes = []
    for spec in specs:
        whole = _literal_integer(spec.whole)
        if whole is None:
            _fail(
                f"{strategy}_requires_literal_whole",
                f"supporting_visuals.{spec.ref}.whole",
                "a literal whole on every partition so the compiler can verify they share it",
                _describe_expression(spec.whole),
                "set whole to a literal integer, or use a different strategy",
            )
        wholes.append((spec.ref, whole))
    reference_ref, reference_whole = wholes[0]
    for ref, whole in wholes[1:]:
        if whole != reference_whole:
            _fail(
                f"{strategy}_requires_same_whole",
                f"supporting_visuals.{ref}.whole",
                f"every partition to share the primary's whole ({reference_whole})",
                f"{ref} whole={whole}",
                f"set {ref}.whole to {reference_whole}",
            )


def _lcm(a, b):
    return a * b // gcd(a, b)


def validate_unit_rate_value_range(plan, known_fields):
    """`unit_rate` teaches "1 source unit = per_unit target units".

    Box[0] carries the rate, so it has to read as a full source unit. A
    tape whose value can fall below 1 (a literal 0.5 km, or a field whose
    minimum is 0.5) would put "0.5 km" on box[0] and defeat the per-one
    framing -- the same failure mode the beat-expander and quality gate
    guard against for the render, refused here at compile time so a plan
    that could never pass is rejected before it renders.
    """
    if plan.strategy != "unit_rate":
        return
    value = plan.primary_visual.value
    contract = FieldContract.of(known_fields)
    if value.node == "literal":
        if Fraction(value.value) >= 1:
            return
        _fail(
            "unit_rate_requires_full_unit_value", "primary_visual.value",
            "a value of at least 1 so box[0] is a full source unit",
            str(value.value),
            "raise value to 1 or more, or use a different strategy",
        )
    if value.node == "field_ref" and value.index is None and value.item_field is None:
        minimum = contract.scalar_minimums.get(value.field)
        if minimum is not None and minimum >= 1:
            return
        observed = (
            f"field:{value.field} (minimum={minimum})"
            if minimum is not None else f"field:{value.field} (minimum unknown)"
        )
        _fail(
            "unit_rate_requires_full_unit_value", "primary_visual.value",
            "a field_ref whose minimum is at least 1",
            observed,
            "raise the field's minimum to 1 or more, use a literal, or use a different strategy",
        )
    _fail(
        "unit_rate_requires_full_unit_value", "primary_visual.value",
        "a literal or scalar field_ref whose minimum is at least 1",
        _describe_expression(value),
        "use a literal >= 1 or a scalar field_ref with minimum >= 1, or use a different strategy",
    )


def _require_owned_sweep_beat(plan):
    if magnitude_sweep_beat_id(plan) is None:
        _fail(
            "magnitude_comparison_requires_sweep_beat", "beats",
            f"a focus or derive beat targeting {plan.primary_visual.ref!r}, "
            "which the compiler stages the sweep on",
            "no focus/derive beat names the primary visual",
            "add a focus or derive beat whose targets include the primary visual",
        )


def _validate_percent_of_whole_compatibility(plan):
    """A percent bar is a 100-unit bar with a whole-number percent as its value.

    Constraining `maximum` to 100 keeps "part-of-whole" reasoning legible:
    each segment represents exactly one percent, so a `value` of 30 reads as
    "30% of the whole" without a separate axis. `value` in [1, 99] leaves
    both the "part" and the "whole minus part" on screen: 0 would sweep
    nothing (same shape as `magnitude_comparison`'s zero-value refusal) and
    100 would put the whole bar in `focus`, losing the two-region contrast
    the strategy exists to teach.

    `supporting_visuals` are left free -- a label naming "30%" is a common
    supporting visual and the strategy does not stage it.
    """
    spec = plan.primary_visual
    if spec.kind != "bar":
        _fail(
            "percent_of_whole_requires_bar_primary", "primary_visual.kind",
            "a bar primary visual (percent-of-whole is only defined on a bar)",
            spec.kind,
            "make the primary visual a bar with maximum=100, or use a different strategy",
        )
    maximum = _literal_integer(spec.maximum)
    if maximum != 100:
        _fail(
            "percent_of_whole_requires_hundred_maximum", "primary_visual.maximum",
            "a literal maximum of 100 so one segment reads as one percent",
            _describe_expression(spec.maximum),
            "set maximum to the literal 100, or use magnitude_comparison for a non-percent bar",
        )
    value = _literal_integer(spec.value)
    if value is None:
        _fail(
            "percent_of_whole_requires_literal_value", "primary_visual.value",
            "a literal whole-number percent (1..99) so the sweep addresses specific segments",
            _describe_expression(spec.value),
            "set value to a literal integer in [1, 99], or use a different strategy",
        )
    if value < 1 or value > 99:
        _fail(
            "percent_of_whole_requires_value_in_range", "primary_visual.value",
            "a percent value in [1, 99] so both the part and the remainder stay on screen",
            str(value),
            "set value to a whole percent between 1 and 99, or use a different strategy",
        )
    if value > _MAX_PERCENT_SWEEP_SEGMENTS:
        _fail(
            "percent_of_whole_sweep_over_budget", "primary_visual.value",
            f"a percent value at most {_MAX_PERCENT_SWEEP_SEGMENTS} so the "
            f"per-segment sweep fits under the 40-action program cap",
            str(value),
            f"lower value to {_MAX_PERCENT_SWEEP_SEGMENTS} or below, or use a different strategy",
        )
    if percent_sweep_beat_id(plan) is None:
        _fail(
            "percent_of_whole_requires_sweep_beat", "beats",
            f"a focus or derive beat targeting {plan.primary_visual.ref!r}, "
            "which the compiler stages the sweep on",
            "no focus/derive beat names the primary visual",
            "add a focus or derive beat whose targets include the primary visual",
        )


def _validate_percent_change_compatibility(plan):
    """A percent-change lesson needs a before bar and an after bar.

    Both bars share a maximum (the axis against which the delta reads),
    so the after-bar's segments align one-to-one with the before-bar's --
    the delta the strategy sweeps has to fall inside the same segment
    span. Distinct literal values give the strategy a delta to sweep;
    equal values are the `group_reveal` shape (two identical bars, no
    change to teach). Both values sit inside [1, maximum-1] so the
    delta has room and the bars read as partial fills of the same axis.
    """
    primary = plan.primary_visual
    if primary.kind != "bar":
        _fail(
            "percent_change_requires_bar_primary", "primary_visual.kind",
            "a bar primary visual (percent_change stages a before/after bar pair)",
            primary.kind,
            "make the primary visual the 'before' bar, or use a different strategy",
        )
    supporting_bars = [
        spec for spec in plan.supporting_visuals if spec.kind == "bar"
    ]
    if len(plan.supporting_visuals) != 1 or len(supporting_bars) != 1:
        _fail(
            "percent_change_requires_one_supporting_bar", "supporting_visuals",
            "exactly one supporting bar visual (the 'after' bar)",
            f"{len(plan.supporting_visuals)} supporting visuals "
            f"({len(supporting_bars)} of them bars)",
            "declare one supporting bar with matching maximum to hold the after value",
        )
    after = supporting_bars[0]
    primary_max = _literal_integer(primary.maximum)
    after_max = _literal_integer(after.maximum)
    if primary_max is None or after_max is None:
        _fail(
            "percent_change_requires_literal_maxima", "primary_visual.maximum",
            "literal whole-number maxima on both bars so the delta sweeps a known span",
            f"before={_describe_expression(primary.maximum)}, "
            f"after={_describe_expression(after.maximum)}",
            "set both bars' maximum to a literal integer, or use a different strategy",
        )
    if primary_max != after_max:
        _fail(
            "percent_change_requires_matching_maxima",
            f"supporting_visuals[0].maximum",
            "the same literal maximum on both bars so the delta lands on the same axis",
            f"before={primary_max}, after={after_max}",
            "set the supporting bar's maximum equal to the primary bar's",
        )
    before_value = _literal_integer(primary.value)
    after_value = _literal_integer(after.value)
    if before_value is None or after_value is None:
        _fail(
            "percent_change_requires_literal_values", "primary_visual.value",
            "literal whole-number values on both bars so the delta segments are known at compile time",
            f"before={_describe_expression(primary.value)}, "
            f"after={_describe_expression(after.value)}",
            "set both bars' value to a literal integer, or use a different strategy",
        )
    if before_value == after_value:
        _fail(
            "percent_change_requires_distinct_values",
            f"supporting_visuals[0].value",
            "a non-zero delta between the two bars so the sweep has segments to animate",
            f"before={before_value}, after={after_value}",
            "make the after value different from the before value, or use a different strategy",
        )
    for label, value in (("before", before_value), ("after", after_value)):
        if value < 1 or value > primary_max - 1:
            _fail(
                "percent_change_requires_value_in_range",
                (
                    "primary_visual.value" if label == "before"
                    else "supporting_visuals[0].value"
                ),
                f"a {label} value in [1, {primary_max - 1}] so the bar reads as a partial fill",
                str(value),
                "set the value between 1 and one less than maximum, or use a different strategy",
            )
    delta = abs(after_value - before_value)
    if delta > _MAX_PERCENT_SWEEP_SEGMENTS:
        _fail(
            "percent_change_sweep_over_budget", "supporting_visuals[0].value",
            f"a delta of at most {_MAX_PERCENT_SWEEP_SEGMENTS} segments so the "
            f"per-segment sweep fits under the 40-action program cap",
            f"delta={delta}",
            f"pick before/after values whose difference is {_MAX_PERCENT_SWEEP_SEGMENTS} or less",
        )
    _require_percent_change_sweep_beat(plan, after.ref)


def _validate_rotation_compatibility(plan):
    """Refuse a `rotation` plan whose polygon, pivot, or iterated images
    would fall off the plane, degenerate into a bowtie, or return to start
    mid-sequence.

    Every check here is compile-time: the schema already caps `polygons` at
    one entry and `rotation_iterations` at 1..4 (`teaching_plan.py`), so this
    only has to confirm the three rotation fields are all *present* together,
    reject an iteration count that lands the polygon back on its start pose,
    and (via `_compute_rotation_frames`) confirm every rotated vertex stays on
    the plane and every rotated image stays simple.
    """
    spec = plan.primary_visual
    if len(spec.polygons) != 1:
        _fail(
            "rotation_requires_one_polygon", "primary_visual.polygons",
            "exactly one polygon on the plane",
            f"len(polygons)={len(spec.polygons)}",
            "declare a single polygon on the coordinate_plane",
        )
    if spec.pivot is None or spec.rotation_angle_deg is None or spec.rotation_iterations is None:
        _fail(
            "rotation_requires_pivot_and_angle_and_iterations", "primary_visual",
            "pivot, rotation_angle_deg, and rotation_iterations all set",
            f"pivot={spec.pivot is not None}, angle={spec.rotation_angle_deg}, "
            f"iterations={spec.rotation_iterations}",
            "set all three fields on the coordinate_plane",
        )
    _require_owned_rotation_beat(plan)

    iterations = spec.rotation_iterations
    angle_deg = spec.rotation_angle_deg
    if iterations > 1 and (iterations * angle_deg) % 360 == 0:
        _fail(
            "rotation_returns_to_start", "primary_visual",
            "iterations * angle_deg NOT a multiple of 360 degrees",
            f"iterations={iterations}, angle_deg={angle_deg}",
            "reduce iterations or pick a smaller angle so the polygon does "
            "not return to its start pose",
        )
    # Runs (and discards) the frame computation purely to surface an
    # off-plane or self-intersecting image as a compile-time failure here,
    # at validation time, rather than later when `_apply_rotation_frames`
    # recomputes it to populate the program visual.
    _compute_rotation_frames(spec)


def _require_owned_rotation_beat(plan):
    """`rotation` needs exactly one focus-or-derive beat in the whole plan,
    and that beat must carry no plan-authored `custom_actions`.

    Every other single-owned-beat strategy (`magnitude_comparison`,
    `signed_hop`, `equivalence_align`, ...) picks the FIRST focus/derive beat
    naming its primary visual and lets a later focus/derive beat behave
    normally. `rotation` cannot: the iterated image is one indivisible
    sequence, so a SECOND focus/derive beat has nothing left to mean --
    it would either duplicate the sequence (if it also named the plane) or
    silently do nothing (if it named something else), neither of which is a
    lesson shape worth allowing. Refusing any count other than exactly one,
    rather than "first one wins", surfaces that ambiguity at compile time.

    A plan-authored `custom_actions` on the staging beat competes with the
    compiler's own `RotateAction` sequence for the same beat's timeline slots
    -- there is no way to interleave an author's emphasize/dim/reveal with a
    strictly ordered rotation sequence and have both read as intended, so
    the beat is compiler-owned outright, the same discipline `regroup` and
    `pair_elimination` already apply to their own staged beats.
    """
    matches = rotation_focus_or_derive_beats(plan)
    if len(matches) != 1:
        _fail(
            "rotation_requires_one_focus_or_derive_beat", "beats",
            "exactly one focus-or-derive beat, which the compiler stages "
            "the rotation sequence on",
            f"count={len(matches)}",
            "consolidate the rotation onto a single focus or derive beat",
        )
    beat = matches[0]
    if beat.custom_actions:
        _fail(
            "rotation_custom_actions_forbidden", f"beats[{beat.id!r}].custom_actions",
            "no plan-authored actions on the rotation staging beat",
            f"count={len(beat.custom_actions)}",
            "let the compiler stage the rotation; remove custom_actions from this beat",
        )


def _compute_rotation_frames(spec):
    """Rotate `spec.polygons[0].vertices` about `spec.pivot` for each
    iteration and return the list of per-iteration vertex lists.

    Entry `k` is the polygon's vertex list after iteration `k + 1` (so index
    0 is the first application of the rotation, and the last entry is the
    final image). Every produced vertex is checked against the plane extent
    and every produced image against self-intersection; either violation
    raises immediately rather than returning a partial/invalid result.
    """
    pivot_x = _literal_number(spec.pivot.x)
    pivot_y = _literal_number(spec.pivot.y)
    x_min = _literal_number(spec.x_min)
    x_max = _literal_number(spec.x_max)
    y_min = _literal_number(spec.y_min)
    y_max = _literal_number(spec.y_max)
    if None in (pivot_x, pivot_y, x_min, x_max, y_min, y_max):
        _fail(
            "rotation_requires_literal_geometry", "primary_visual",
            "a literal pivot and literal plane extent",
            "pivot or plane extent is a non-literal expression node",
            "for the M22 MVP, express pivot/x_min/x_max/y_min/y_max as literals",
        )

    angle_rad = radians(spec.rotation_angle_deg)
    cos_a, sin_a = cos(angle_rad), sin(angle_rad)

    current = [
        (_literal_number(vertex.x), _literal_number(vertex.y))
        for vertex in spec.polygons[0].vertices
    ]
    if any(x is None or y is None for x, y in current):
        _fail(
            "rotation_requires_literal_geometry", "primary_visual.polygons",
            "literal polygon vertices",
            "a polygon vertex is a non-literal expression node",
            "for the M22 MVP, express every polygon vertex as a literal",
        )

    frames = []
    for iteration_index in range(spec.rotation_iterations):
        rotated = []
        for vx, vy in current:
            dx, dy = vx - pivot_x, vy - pivot_y
            nx = round(pivot_x + cos_a * dx - sin_a * dy, 12)
            ny = round(pivot_y + sin_a * dx + cos_a * dy, 12)
            if not (x_min <= nx <= x_max and y_min <= ny <= y_max):
                _fail(
                    "rotation_image_off_plane", "primary_visual",
                    "every rotated vertex inside the plane extent",
                    f"iteration={iteration_index + 1}, vertex=({nx}, {ny}), "
                    f"span=x[{x_min}, {x_max}] y[{y_min}, {y_max}]",
                    "shrink the polygon, widen the plane, or reduce iterations",
                )
            rotated.append((nx, ny))
        # Defence in depth, not a duplicate of the measurer's original-order
        # check: a rotation preserves simplicity mathematically, but rounding
        # every vertex to 12 decimals could in principle flip a degenerate,
        # near-collinear edge pair. Cheap to check; free of false positives on
        # every fixture exercised so far.
        if _polygon_self_intersects(rotated):
            _fail(
                "rotation_image_self_intersects", "primary_visual",
                "a rotated polygon that is still simple",
                f"iteration={iteration_index + 1}, vertices={rotated}",
                "adjust the vertex order or the rotation angle",
            )
        frames.append(rotated)
        current = rotated
    return frames


def _require_percent_change_sweep_beat(plan, after_ref):
    """The compiler stages `percent_change`'s delta sweep on the after-bar.

    Mirrors `_require_owned_sweep_beat` but pins to the supporting bar's
    ref -- the sweep colours the delta segments on the after-bar, so the
    beat that owns the sweep is the first focus/derive beat naming it, not
    the primary.
    """
    for beat in plan.beats:
        if beat.kind not in {"focus", "derive"}:
            continue
        if any(target.visual_ref == after_ref for target in beat.targets):
            return
    _fail(
        "percent_change_requires_sweep_beat", "beats",
        f"a focus or derive beat targeting {after_ref!r}, "
        "which the compiler stages the delta sweep on",
        "no focus/derive beat names the after bar",
        "add a focus or derive beat whose targets include the after bar",
    )


def _describe_expression(expression):
    if expression.node == "literal":
        return str(expression.value)
    if expression.node == "field_ref":
        return f"field:{expression.field}"
    return expression.node


def validate_pair_elimination_answer(plan, answer_expression):
    """`pair_elimination`'s answer is the surviving middle value, by definition.

    `_answer_anchor` always points the probe gates at the middle item, so a
    plan whose `answer_expression` names something else would animate to,
    caption, and hold the persistence gate on one value while claiming a
    different one is the answer -- and nothing else compares the two.
    """
    if plan.strategy != "pair_elimination":
        return
    middle = plan.primary_visual.values[len(plan.primary_visual.values) // 2]
    if answer_expression != middle:
        _fail(
            "pair_elimination_answer_must_be_middle_value", "answer_expression",
            "the same expression as the primary visual's middle value",
            str(answer_expression),
            "set answer_expression to primary_visual.values[len(values) // 2]",
        )


def classify_content_density(visuals):
    if len(visuals) <= 2:
        return "low"
    if len(visuals) <= 4:
        return "medium"
    return "high"


def _answer_anchor(plan):
    """The on-screen target that IS the answer, when nothing else states it.

    `pair_elimination` leaves the answer standing as the one unpaired item, so
    the lesson draws no separate answer card and the rendered-quality probe has
    to be told which target to hold to the final frame instead. `rotation`
    (M22) is the same shape: the final rotated image IS the answer -- there is
    no separate numeric result -- so the probe is pointed at the polygon
    rather than at a card.
    """
    if plan.strategy == "pair_elimination":
        return TargetRef(
            visual_ref=plan.primary_visual.ref,
            part="item",
            index=len(plan.primary_visual.values) // 2,
        )
    if plan.strategy == "rotation":
        return TargetRef(visual_ref=plan.primary_visual.ref, part="polygon", index=0)
    return None


def _visual_specs(plan):
    return [plan.primary_visual, *plan.supporting_visuals]


def _validate_target(target, specs, path):
    try:
        spec = specs[target.visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", f"{path}.visual_ref", "a visual declared by the plan",
            target.visual_ref,
            _enumerate_legal(
                specs, "reference the primary or a supporting visual",
                "the plan declares no visuals",
            ),
        )
    if target.part is None:
        return spec
    parts = _PART_CARDINALITY[spec.kind]
    if target.part not in parts:
        _fail(
            "unknown_semantic_part", f"{path}.part", "a part exposed by the visual",
            f"{spec.kind}.{target.part}",
            _enumerate_legal(
                parts, "choose a declared semantic part",
                "this visual exposes no semantic parts",
            ),
        )
    if target.index is None:
        _fail(
            "missing_semantic_index", f"{path}.index", "an index for the semantic part",
            "none", "supply the part index",
        )
    cardinality = parts[target.part](spec)
    if cardinality is not None and target.index >= cardinality:
        _fail(
            "target_index_out_of_range", f"{path}.index", f"an index below {cardinality}",
            str(target.index), "choose an existing semantic item",
        )
    return spec


def _validate_path_ref(path_ref, specs, path):
    visual_ref, separator, name = path_ref.partition(".")
    if not separator or not visual_ref or not name or "." in name:
        declared = _DECLARED_PATHS.get(specs[visual_ref].kind, set()) if visual_ref in specs else set()
        _fail(
            "invalid_path_ref", path, "a declared visual path reference", path_ref,
            _enumerate_legal(
                declared, "use the form visual_ref.path_name",
                "use the form visual_ref.path_name",
            ),
        )
    try:
        spec = specs[visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", path, "a visual declared by the plan", visual_ref,
            _enumerate_legal(
                specs, "reference the primary or a supporting visual",
                "the plan declares no visuals",
            ),
        )
    declared = _DECLARED_PATHS.get(spec.kind, set())
    if name not in declared:
        _fail(
            "unknown_declared_path", path, "a path exposed by the visual", path_ref,
            _enumerate_legal(
                declared, "use a declared semantic path",
                "this visual exposes no semantic paths",
            ),
        )
    return spec


def _validate_compatible_target(target, spec, compatible_targets, code, path, expected, prefix):
    compatible_parts = compatible_targets.get(spec.kind, set())
    if target.part not in compatible_parts:
        _fail(
            code, f"{path}.target", expected, f"{spec.kind}.{target.part}",
            _enumerate_legal(compatible_targets, prefix, "no visual kind supports this action"),
        )


def _validate_callout_anchor(target, spec, path):
    if (
        spec.kind == "ordered_values"
        and target.part == "item"
        and target.anchor not in _ITEM_CALLOUT_ANCHORS
    ):
        _fail(
            "incompatible_callout_anchor", f"{path}.target.anchor",
            "the bottom anchor of an ordered-value item", target.anchor,
            _enumerate_legal(
                _ITEM_CALLOUT_ANCHORS, "attach item callouts to a permitted anchor",
                "this part accepts no callout anchors",
            ),
        )


def _literal_integer(expression):
    if expression.node != "literal" or not float(expression.value).is_integer():
        return None
    return int(expression.value)


def _literal_number(expression):
    """The literal's float value, or None when the expression is not a literal."""
    if expression.node != "literal":
        return None
    return float(expression.value)


def _literal_ceiling(expression):
    """The box count when the plan states it outright, else unknown.

    A tape's `value` is normally a field reference, so the count is only known
    once fixture params arrive -- `None` tells `_validate_target` to leave index
    bounds to the resolver, as it already does for a `bar` with a computed
    `maximum`.
    """
    if expression.node != "literal":
        return None
    return ceil(float(expression.value))


def _literal_product(left, right):
    left_value, right_value = _literal_integer(left), _literal_integer(right)
    if left_value is None or right_value is None:
        return None
    return left_value * right_value


def _enumerate_legal(values, prefix, empty):
    if not values:
        return empty
    return f"{prefix}: {', '.join(sorted(values))}"


def _fail(code, path, expected, observed, hint):
    raise V3ValidationError(V3Failure(
        code=code, path=path, expected=expected, observed=observed, hint=hint,
    ))
