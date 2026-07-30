from dataclasses import dataclass

from app.meta.dsl.scene_program import (
    AnswerProgramVisual, BarProgramVisual, CalloutRelation, DrawAction,
    GridProgramVisual, LabelProgramVisual, MoveAction, NumberLineProgramVisual,
    ObjectSetProgramVisual, OrderedValuesProgramVisual, PartitionProgramVisual,
    ProgramAction, RectangleProgramVisual, RevealAction, SetRoleAction, ShowRelationAction,
    TraceAction, TransformAction,
)
from app.meta.dsl.v3_common import TargetRef


@dataclass(frozen=True)
class ExpandedBeat:
    beat_id: str
    actions: list[ProgramAction]
    minimum_seconds: float
    weight: float


_PROGRAM_VISUALS = {
    "ordered_values": (OrderedValuesProgramVisual, "neutral"),
    "rectangle_measurement": (RectangleProgramVisual, "structure"),
    "number_line": (NumberLineProgramVisual, "structure"),
    "grid": (GridProgramVisual, "structure"),
    "partition": (PartitionProgramVisual, "structure"),
    "bar": (BarProgramVisual, "structure"),
    "object_set": (ObjectSetProgramVisual, "structure"),
    "label": (LabelProgramVisual, "neutral"),
}

_BEAT_TIMING = {
    "orient": (0.75, 1.0),
    "reveal": (1.0, 1.0),
    "organize": (1.25, 1.25),
    "focus": (1.0, 1.0),
    "derive": (1.25, 1.25),
    "conclude": (1.5, 1.5),
}


class BeatExpander:
    def __init__(self, *, answer_expression):
        self.answer_expression = answer_expression

    def expand(self, plan):
        visuals = [self._program_visual(spec) for spec in self._visual_specs(plan)]
        visuals.append(AnswerProgramVisual(ref="evaluated_answer", expression=self.answer_expression))
        initial_roles = {visual.ref: visual.initial_role for visual in visuals}
        current_roles = dict(initial_roles)
        previous_roles = {}
        relations = []
        expanded = []
        boundary_trace_beat_id = self._boundary_trace_beat_id(plan)

        for beat_index, beat in enumerate(plan.beats):
            actions = self._standard_actions(
                plan, beat, relations, current_roles, boundary_trace_beat_id,
            )
            for action_index, request in enumerate(beat.custom_actions):
                actions.extend(self._custom_actions(
                    request=request,
                    beat_index=beat_index,
                    action_index=action_index,
                    relations=relations,
                    initial_roles=initial_roles,
                    current_roles=current_roles,
                    previous_roles=previous_roles,
                ))
            minimum_seconds, weight = _BEAT_TIMING[beat.kind]
            expanded.append(ExpandedBeat(
                beat_id=beat.id,
                actions=actions,
                minimum_seconds=minimum_seconds,
                weight=weight,
            ))
        return visuals, relations, expanded

    @staticmethod
    def _visual_specs(plan):
        return [plan.primary_visual, *plan.supporting_visuals]

    @staticmethod
    def _program_visual(spec):
        program_type, initial_role = _PROGRAM_VISUALS[spec.kind]
        return program_type.model_validate({**spec.model_dump(), "initial_role": initial_role})

    def _standard_actions(self, plan, beat, relations, current_roles, boundary_trace_beat_id):
        if beat.kind in {"orient", "reveal"}:
            mode = "stagger" if plan.strategy == "short_stagger" else "together"
            return [RevealAction(targets=beat.targets, mode=mode)]

        if beat.kind == "organize" and plan.strategy == "pair_elimination":
            count = len(plan.primary_visual.values)
            middle = count // 2
            return [
                self._set_role(
                    TargetRef(visual_ref=plan.primary_visual.ref, part="item", index=index),
                    "constraint", current_roles,
                )
                for index in range(count) if index != middle
            ]

        if plan.strategy == "boundary_trace" and beat.id == boundary_trace_beat_id:
            return [TraceAction(path_ref=f"{plan.primary_visual.ref}.perimeter")]

        if beat.kind == "focus":
            actions = [self._set_role(target, "focus", current_roles) for target in beat.targets]
            if plan.strategy == "pair_elimination":
                middle = len(plan.primary_visual.values) // 2
                for target in beat.targets:
                    if (
                        target.visual_ref == plan.primary_visual.ref
                        and target.part == "item"
                        and target.index == middle
                        and not any(relation.ref == "median_callout" for relation in relations)
                    ):
                        relations.append(CalloutRelation(
                            ref="median_callout",
                            target={
                                "visual_ref": target.visual_ref,
                                "part": "item",
                                "index": middle,
                                "anchor": "bottom",
                            },
                            text="median",
                        ))
                        actions.append(ShowRelationAction(relation_ref="median_callout"))
                        break
            return actions

        if beat.kind == "conclude":
            answer_target = TargetRef(visual_ref="evaluated_answer")
            return [
                RevealAction(targets=[answer_target], mode="together"),
                self._set_role(answer_target, "conclusion", current_roles),
            ]

        return [self._set_role(target, "structure", current_roles) for target in beat.targets]

    @staticmethod
    def _boundary_trace_beat_id(plan):
        if plan.strategy != "boundary_trace":
            return None
        for beat in plan.beats:
            if beat.kind in {"organize", "derive", "focus"}:
                return beat.id
        return None

    def _custom_actions(
        self, *, request, beat_index, action_index, relations,
        initial_roles, current_roles, previous_roles,
    ):
        kind = request.kind
        if kind == "reveal":
            return [RevealAction(targets=request.targets, mode=request.mode)]
        if kind == "emphasize":
            return [self._set_role(request.target, request.role, current_roles)]
        if kind == "dim":
            key = self._target_key(request.target)
            previous_roles[key] = current_roles.get(key, initial_roles[request.target.visual_ref])
            return [self._set_role(request.target, "neutral", current_roles)]
        if kind == "restore":
            key = self._target_key(request.target)
            role = previous_roles.pop(key, initial_roles[request.target.visual_ref])
            return [self._set_role(request.target, role, current_roles)]
        if kind == "trace":
            return [TraceAction(path_ref=request.path_ref)]
        if kind == "draw":
            return [DrawAction(target=request.target)]
        if kind == "transform":
            return [TransformAction(source=request.source, target=request.target)]
        if kind == "move":
            return [MoveAction(target=request.target, path_ref=request.path_ref)]
        if kind == "callout":
            relation_ref = f"callout_{beat_index}_{action_index}"
            relations.append(CalloutRelation(
                ref=relation_ref, target=request.target, text=request.text,
            ))
            return [ShowRelationAction(relation_ref=relation_ref)]
        raise ValueError(f"unsupported requested action {kind}")

    @staticmethod
    def _target_key(target):
        return target.visual_ref, target.part, target.index

    def _set_role(self, target, role, current_roles):
        current_roles[self._target_key(target)] = role
        return SetRoleAction(target=target, role=role)


def expand_beats(plan, answer_expression):
    return BeatExpander(answer_expression=answer_expression).expand(plan)
