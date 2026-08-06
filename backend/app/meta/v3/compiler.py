from dataclasses import asdict
from fractions import Fraction
from math import ceil

from app.meta.dsl.expression import FieldContract, compile_expression
from app.meta.dsl.scene_program import SceneProgramDocument, StyleRecipeDocument
from app.meta.dsl.v3_common import TargetRef
from app.meta.v3.beat_expander import (
    expand_beats, magnitude_sweep_beat_id, regroup_beat_id,
)
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.style_recipe import resolve_style_recipe
from app.meta.v3.timeline import schedule_beats
from app.meta.v3.visual_registry import _SUPPORTED_STRATEGIES


_EXPRESSION_FIELDS = {
    "ordered_values": ("values",),
    "rectangle_measurement": ("length", "width"),
    "number_line": ("minimum", "maximum", "markers"),
    "grid": ("rows", "columns"),
    "partition": ("whole", "parts"),
    "bar": ("value", "maximum"),
    "object_set": ("count",),
    "label": (),
    "unit_tape": ("value", "per_unit"),
    "coordinate_plane": ("x_min", "x_max", "y_min", "y_max"),
}

_PART_CARDINALITY = {
    "ordered_values": {"item": lambda spec: len(spec.values)},
    "rectangle_measurement": {
        "edge": lambda spec: 4,
        "length_edge": lambda spec: 2,
        "width_edge": lambda spec: 2,
        "vertex": lambda spec: 4,
    },
    "number_line": {"marker": lambda spec: len(spec.markers)},
    "grid": {"cell": lambda spec: _literal_product(spec.rows, spec.columns)},
    "partition": {"partition": lambda spec: _literal_integer(spec.parts)},
    "bar": {"segment": lambda spec: _literal_integer(spec.maximum)},
    "object_set": {"item": lambda spec: _literal_integer(spec.count)},
    "label": {},
    "unit_tape": {
        "box": lambda spec: _literal_ceiling(spec.value),
        "source_label": lambda spec: _literal_ceiling(spec.value),
        "target_label": lambda spec: _literal_ceiling(spec.value),
    },
    "coordinate_plane": {"point": lambda spec: len(spec.points)},
}

_DECLARED_PATHS = {"rectangle_measurement": {"perimeter"}}

_DRAWABLE_TARGETS = {"rectangle_measurement": {None}}
_MOVABLE_TARGETS = {"rectangle_measurement": {None}}
_TRANSFORM_COMPATIBILITY = {"rectangle_measurement": {"rectangle_measurement"}}
_ITEM_CALLOUT_ANCHORS = {"bottom"}


def compile_teaching_plan(plan, answer_expression, known_fields, context):
    compile_expression(answer_expression, known_fields)
    for expression in expressions_from_plan(plan):
        compile_expression(expression, known_fields)
    validate_unique_visual_refs(plan)
    validate_target_refs(plan)
    validate_strategy_compatibility(plan)
    validate_unit_rate_value_range(plan, known_fields)
    validate_pair_elimination_answer(plan, answer_expression)
    visuals, relations, beats = expand_beats(plan, answer_expression)
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


def expressions_from_plan(plan):
    for spec in _visual_specs(plan):
        for field_name in _EXPRESSION_FIELDS[spec.kind]:
            value = getattr(spec, field_name)
            yield from value if isinstance(value, list) else (value,)
        if spec.kind == "coordinate_plane":
            for point in spec.points:
                yield point.x
                yield point.y


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


def validate_strategy_compatibility(plan):
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
    _require_owned_sweep_beat(plan)


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
    to be told which target to hold to the final frame instead.
    """
    if plan.strategy != "pair_elimination":
        return None
    return TargetRef(
        visual_ref=plan.primary_visual.ref,
        part="item",
        index=len(plan.primary_visual.values) // 2,
    )


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
