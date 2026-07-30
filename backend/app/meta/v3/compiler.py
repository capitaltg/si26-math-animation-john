from dataclasses import asdict

from app.meta.dsl.expression import compile_expression
from app.meta.dsl.scene_program import SceneProgramDocument, StyleRecipeDocument
from app.meta.v3.beat_expander import expand_beats
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
}

_DECLARED_PATHS = {"rectangle_measurement": {"perimeter"}}


def compile_teaching_plan(plan, answer_expression, known_fields, context):
    compile_expression(answer_expression, known_fields)
    for expression in expressions_from_plan(plan):
        compile_expression(expression, known_fields)
    validate_unique_visual_refs(plan)
    validate_target_refs(plan)
    validate_strategy_compatibility(plan)
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
    )


def expressions_from_plan(plan):
    for spec in _visual_specs(plan):
        for field_name in _EXPRESSION_FIELDS[spec.kind]:
            value = getattr(spec, field_name)
            yield from value if isinstance(value, list) else (value,)


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
            elif action.kind in {"emphasize", "dim", "restore", "draw", "move"}:
                _validate_target(action.target, specs, f"{path}.target")
            elif action.kind == "transform":
                source = _validate_target(action.source, specs, f"{path}.source")
                target = _validate_target(action.target, specs, f"{path}.target")
                if source.kind != target.kind:
                    _fail(
                        "incompatible_transform", path, "source and target visual kinds to match",
                        f"{source.kind}:{target.kind}", "transform between compatible semantic visuals",
                    )
            elif action.kind == "callout":
                _validate_target(action.target, specs, f"{path}.target")

            if action.kind in {"trace", "move"}:
                path_ref = action.path_ref
                path_spec = _validate_path_ref(path_ref, specs, f"{path}.path_ref")
                if action.kind == "move" and path_spec.ref != action.target.visual_ref:
                    _fail(
                        "path_target_mismatch", f"{path}.path_ref", "a path owned by the moved visual",
                        path_ref, "use a declared path on the move target",
                    )


def validate_strategy_compatibility(plan):
    supported = _SUPPORTED_STRATEGIES[plan.primary_visual.kind]
    if plan.strategy not in supported:
        _fail(
            "incompatible_strategy", "strategy", "a strategy supported by the visual kind",
            f"{plan.strategy}:{plan.primary_visual.kind}", "select a compatible strategy",
        )
    if plan.strategy == "pair_elimination" and len(plan.primary_visual.values) % 2 == 0:
        _fail(
            "pair_elimination_requires_odd_values", "primary_visual.values",
            "an odd number of ordered values", str(len(plan.primary_visual.values)),
            "use an odd-sized collection with one middle item",
        )


def classify_content_density(visuals):
    if len(visuals) <= 2:
        return "low"
    if len(visuals) <= 4:
        return "medium"
    return "high"


def _visual_specs(plan):
    return [plan.primary_visual, *plan.supporting_visuals]


def _validate_target(target, specs, path):
    try:
        spec = specs[target.visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", f"{path}.visual_ref", "a visual declared by the plan",
            target.visual_ref, "reference the primary or a supporting visual",
        )
    if target.part is None:
        return spec
    parts = _PART_CARDINALITY[spec.kind]
    if target.part not in parts:
        _fail(
            "unknown_semantic_part", f"{path}.part", "a part exposed by the visual",
            f"{spec.kind}.{target.part}", "choose a declared semantic part",
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
        _fail(
            "invalid_path_ref", path, "a declared visual path reference", path_ref,
            "use the form visual_ref.path_name",
        )
    try:
        spec = specs[visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", path, "a visual declared by the plan", visual_ref,
            "reference the primary or a supporting visual",
        )
    if name not in _DECLARED_PATHS.get(spec.kind, set()):
        _fail(
            "unknown_declared_path", path, "a path exposed by the visual", path_ref,
            "use a declared semantic path",
        )
    return spec


def _literal_integer(expression):
    if expression.node != "literal" or not float(expression.value).is_integer():
        return None
    return int(expression.value)


def _literal_product(left, right):
    left_value, right_value = _literal_integer(left), _literal_integer(right)
    if left_value is None or right_value is None:
        return None
    return left_value * right_value


def _fail(code, path, expected, observed, hint):
    raise V3ValidationError(V3Failure(
        code=code, path=path, expected=expected, observed=observed, hint=hint,
    ))
