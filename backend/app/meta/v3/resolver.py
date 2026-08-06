from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace

from app.meta.dsl.expression import _evaluate
from app.meta.dsl.scene_program import (
    ProgramAction, ProgramVisual, Relation, SceneProgramDocument, StyleRecipeDocument,
    TimedAction,
)
from app.meta.dsl.v3_common import TargetRef
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.expression_display import expression_display, format_number, has_operation
from app.meta.v3.geometry import (
    Bounds, PlacedVisual, Point, TextMeasurer, translate_bounds, translate_point,
)
from app.meta.v3.layout import place_vertical_lesson
from app.meta.v3.visual_registry import VisualRegistry, default_visual_registry


@dataclass(frozen=True)
class ResolvedRelation:
    ref: str
    kind: str
    target: Point
    text: str


@dataclass(frozen=True)
class ResolvedTarget:
    ref: TargetRef
    bounds: Bounds


@dataclass(frozen=True)
class ResolvedAction:
    at_seconds: float
    duration_seconds: float
    beat_id: str
    action: ProgramAction
    targets: list[ResolvedTarget]
    path: list[Point] | None


@dataclass(frozen=True)
class ResolvedScene:
    visuals: list[PlacedVisual]
    relations: list[ResolvedRelation]
    timeline: list[ResolvedAction]
    total_duration_seconds: float
    style_recipe: StyleRecipeDocument
    answer_anchor: TargetRef | None = None

    def visual(self, ref: str) -> PlacedVisual:
        return next(item for item in self.visuals if item.measured.ref == ref)

    def relation(self, ref: str) -> ResolvedRelation:
        return next(item for item in self.relations if item.ref == ref)

    def anchor(
        self,
        visual_ref: str,
        part: str | None,
        index: int | None,
        name: str,
    ) -> Point:
        return self.visual(visual_ref).anchor(part, index, name)


def resolve_scene(
    program: SceneProgramDocument,
    values: Mapping[str, object],
    measurer: TextMeasurer,
    registry: VisualRegistry | None = None,
) -> ResolvedScene:
    registry = registry or default_visual_registry()
    measured = []
    for visual in program.visuals:
        evaluated, evaluated_values = evaluate_program_visual(visual, values)
        measured.append(registry.measure(evaluated, evaluated_values, measurer))
    placed = place_vertical_lesson(measured, program.relations)
    by_ref = {visual.measured.ref: visual for visual in placed}
    relations = [
        resolve_relation(relation, by_ref, index)
        for index, relation in enumerate(program.relations)
    ]
    timeline = bind_timeline(program.timeline, by_ref, relations)
    return ResolvedScene(
        visuals=placed,
        relations=relations,
        timeline=list(timeline),
        total_duration_seconds=program.total_duration_seconds,
        style_recipe=program.style_recipe,
        answer_anchor=program.answer_anchor,
    )


def evaluate_program_visual(
    visual: ProgramVisual, values: Mapping[str, object],
) -> tuple[SimpleNamespace, dict[str, object]]:
    """Evaluate only the typed expression tree embedded in a program visual."""
    kind = visual.kind
    if kind == "ordered_values":
        return _evaluated_spec(visual), {"values": [_format_value(_evaluate(node, values)) for node in visual.values]}
    if kind == "rectangle_measurement":
        return _evaluated_spec(visual), {
            "length": _evaluate(visual.length, values),
            "width": _evaluate(visual.width, values),
            "unit": visual.unit,
        }
    if kind == "number_line":
        return _evaluated_spec(visual), {
            "minimum": _evaluate(visual.minimum, values),
            "maximum": _evaluate(visual.maximum, values),
            "markers": [_evaluate(node, values) for node in visual.markers],
        }
    if kind == "grid":
        return _evaluated_spec(visual), {
            "rows": _evaluate(visual.rows, values),
            "columns": _evaluate(visual.columns, values),
        }
    if kind == "partition":
        return _evaluated_spec(visual), {
            "whole": _evaluate(visual.whole, values),
            "parts": _evaluate(visual.parts, values),
        }
    if kind == "bar":
        return _evaluated_spec(visual), {
            "value": _evaluate(visual.value, values),
            "maximum": _evaluate(visual.maximum, values),
        }
    if kind == "object_set":
        return _evaluated_spec(visual), {"count": _evaluate(visual.count, values)}
    if kind == "unit_tape":
        return _evaluated_spec(visual), {
            "value": _evaluate(visual.value, values),
            "per_unit": _evaluate(visual.per_unit, values),
            "source_unit": visual.source_unit,
            "target_unit": visual.target_unit,
        }
    if kind == "data_display":
        return _evaluated_spec(visual), _evaluate_data_display(visual, values)
    if kind == "coordinate_plane":
        return _evaluated_spec(visual), {
            "x_min": _evaluate(visual.x_min, values),
            "x_max": _evaluate(visual.x_max, values),
            "y_min": _evaluate(visual.y_min, values),
            "y_max": _evaluate(visual.y_max, values),
            "points": [
                {"x": _evaluate(point.x, values), "y": _evaluate(point.y, values)}
                for point in visual.points
            ],
            "grid": bool(visual.grid),
        }
    if kind == "label":
        return _evaluated_spec(visual), {"text": visual.text}
    if kind == "answer_expression":
        value = format_number(_evaluate(visual.expression, values))
        stages = {"unknown": f"{visual.prefix}?{visual.suffix}"}
        if has_operation(visual.expression):
            work = expression_display(visual.expression, values)
            stages["work"] = f"{visual.prefix}{work} = ?{visual.suffix}"
            stages["value"] = f"{visual.prefix}{work} = {value}{visual.suffix}"
        else:
            stages["value"] = f"{visual.prefix}{value}{visual.suffix}"
        return _evaluated_spec(visual), {"stages": stages}
    raise ValueError(f"unknown program visual {kind}")


def resolve_relation(
    relation: Relation,
    visuals_by_ref: Mapping[str, PlacedVisual],
    index: int = 0,
) -> ResolvedRelation:
    path = f"relations[{index}].target"
    try:
        visual = visuals_by_ref[relation.target.visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", f"{path}.visual_ref", "a resolved visual reference",
            relation.target.visual_ref, "reference a visual declared by the program",
        )
    if relation.target.part == "item" and relation.target.index is None:
        _fail(
            "collection_anchor_for_item", path, "an indexed item anchor",
            "item without an index", "supply the child item index instead of using the collection anchor",
        )
    try:
        target = visual.anchor(
            relation.target.part, relation.target.index, relation.target.anchor,
        )
    except KeyError:
        _fail(
            "unknown_semantic_anchor", path, "an anchor exposed by the resolved visual",
            _anchor_description(relation.target), "choose an existing semantic child anchor",
        )
    return ResolvedRelation(
        ref=relation.ref,
        kind=relation.kind,
        target=target,
        text=relation.text,
    )


def bind_timeline(
    entries: Sequence[TimedAction],
    visuals_by_ref: Mapping[str, PlacedVisual],
    relations: Sequence[ResolvedRelation],
) -> list[ResolvedAction]:
    relations_by_ref = {relation.ref: relation for relation in relations}
    resolved = []
    for index, entry in enumerate(entries):
        targets = [
            resolve_action_target(target, visuals_by_ref, path)
            for target, path in _action_target_items(entry.action, index)
        ]
        path = resolve_action_path(entry.action, visuals_by_ref, index)
        require_relation_if_declared(entry.action, relations_by_ref, index)
        resolved.append(ResolvedAction(
            at_seconds=entry.at_seconds,
            duration_seconds=entry.duration_seconds,
            beat_id=entry.beat_id,
            action=entry.action,
            targets=targets,
            path=path,
        ))
    return resolved


def action_targets(action: ProgramAction) -> list[TargetRef]:
    if action.kind == "reveal":
        return action.targets
    if action.kind in {"set_role", "draw", "move"}:
        return [action.target]
    if action.kind == "transform":
        return [action.source, action.target]
    if action.kind == "signed_hop_arrow":
        return [action.source, action.target]
    if action.kind == "distance_annotation":
        return [action.origin, action.target]
    return []


def resolve_action_target(
    target: TargetRef,
    visuals_by_ref: Mapping[str, PlacedVisual],
    path: str = "timeline.action.target",
) -> ResolvedTarget:
    try:
        visual = visuals_by_ref[target.visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", f"{path}.visual_ref", "a resolved visual reference",
            target.visual_ref, "reference a visual declared by the program",
        )
    if target.part is None:
        return ResolvedTarget(ref=target, bounds=visual.bounds)
    try:
        part_bounds = visual.measured.parts[(target.part, target.index)].bounds
    except KeyError:
        _fail(
            "unknown_semantic_target", path, "a semantic part exposed by the resolved visual",
            _anchor_description(target), "choose an existing semantic child target",
        )
    return ResolvedTarget(ref=target, bounds=translate_bounds(part_bounds, visual.offset))


def resolve_action_path(
    action: ProgramAction,
    visuals_by_ref: Mapping[str, PlacedVisual],
    index: int = 0,
) -> list[Point] | None:
    if action.kind not in {"trace", "move"}:
        return None
    failure_path = f"timeline[{index}].action.path_ref"
    visual_ref, separator, path_name = action.path_ref.partition(".")
    if not separator or not visual_ref or not path_name or "." in path_name:
        _fail(
            "invalid_path_ref", failure_path, "a visual path reference",
            action.path_ref, "use the form visual_ref.path_name",
        )
    try:
        visual = visuals_by_ref[visual_ref]
    except KeyError:
        _fail(
            "unknown_visual_ref", failure_path, "a resolved visual reference",
            visual_ref, "reference a visual declared by the program",
        )
    try:
        points = visual.measured.paths[path_name]
    except KeyError:
        _fail(
            "unknown_path", failure_path, "a path exposed by the resolved visual",
            action.path_ref, "use a declared semantic path",
        )
    return [translate_point(point, visual.offset) for point in points]


def require_relation_if_declared(
    action: ProgramAction,
    relations_by_ref: Mapping[str, ResolvedRelation],
    index: int,
) -> None:
    if action.kind == "show_relation" and action.relation_ref not in relations_by_ref:
        _fail(
            "unknown_relation", f"timeline[{index}].action.relation_ref",
            "a declared relation reference", action.relation_ref,
            "declare the relation before showing it",
        )


def _action_target_items(action, index):
    root = f"timeline[{index}].action"
    if action.kind == "reveal":
        return [(target, f"{root}.targets[{target_index}]") for target_index, target in enumerate(action.targets)]
    if action.kind in {"set_role", "draw", "move", "show_answer_stage"}:
        return [(action.target, f"{root}.target")]
    if action.kind == "transform":
        return [(action.source, f"{root}.source"), (action.target, f"{root}.target")]
    if action.kind == "signed_hop_arrow":
        return [(action.source, f"{root}.source"), (action.target, f"{root}.target")]
    if action.kind == "distance_annotation":
        return [(action.origin, f"{root}.origin"), (action.target, f"{root}.target")]
    return []


def _evaluate_data_display(visual, values):
    """Realise every ExpressionNode a data_display carries.

    Categories carry both a literal label (unchanged) and an expression count
    (evaluated). `line_plot` / `dot_plot` / `box_plot` carry their axis bounds
    and per-value expressions the same way `number_line.markers` does.
    """
    out = {
        "display_style": visual.display_style,
        "axis_label": visual.axis_label,
        "categories": [
            {"label": category.label, "count": _evaluate(category.count, values)}
            for category in visual.categories
        ],
        "values": [_evaluate(node, values) for node in visual.values],
    }
    if visual.axis_min is not None:
        out["axis_min"] = _evaluate(visual.axis_min, values)
    if visual.axis_max is not None:
        out["axis_max"] = _evaluate(visual.axis_max, values)
    if visual.summary is not None:
        out["summary"] = {
            name: _evaluate(getattr(visual.summary, name), values)
            for name in ("minimum", "q1", "median", "q3", "maximum")
        }
    return out


def _evaluated_spec(visual):
    return SimpleNamespace(kind=visual.kind, ref=visual.ref, initial_role=visual.initial_role)


def _format_value(value):
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _anchor_description(target):
    if target.part is None:
        return target.visual_ref
    return f"{target.visual_ref}.{target.part}[{target.index}]"


def _fail(code, path, expected, observed, hint):
    raise V3ValidationError(V3Failure(
        code=code, path=path, expected=expected, observed=observed, hint=hint,
    ))
