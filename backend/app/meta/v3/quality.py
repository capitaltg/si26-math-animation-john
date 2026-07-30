"""Structured, reviewer-safe pedagogical quality gates for v3 candidates."""

from dataclasses import asdict, dataclass

from app.meta.dsl.v3_common import (
    MAX_SCENE_SECONDS,
    MIN_CONCLUSION_HOLD_SECONDS,
    MIN_SCENE_SECONDS,
)
from app.meta.v3.errors import V3Failure, V3ValidationError


@dataclass(frozen=True)
class QualityCheck:
    code: str
    passed: bool
    path: str
    detail: str


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    checks: list[QualityCheck]

    def model_payload(self):
        return {"passed": self.passed, "checks": [asdict(check) for check in self.checks]}

    def require_passed(self):
        failed = next((check for check in self.checks if not check.passed), None)
        if failed is not None:
            raise V3ValidationError(V3Failure(
                code=failed.code,
                path=failed.path,
                expected="quality check to pass",
                observed=failed.detail,
                hint="revise the teaching plan and regenerate the candidate",
            ))


def validate_static_quality(plan, program) -> QualityReport:
    checks = [
        check_duration(program),
        check_grouped_simple_reveals(plan, program),
        check_answer_timing(plan, program),
        check_conclusion_hold(program),
        check_unexplained_idle_time(program),
        check_strategy_affordance(plan, program),
        check_semantic_anchor_specificity(plan, program),
        check_dimension_anchor_specificity(plan, program),
        check_salience(program),
    ]
    return QualityReport(all(check.passed for check in checks), checks)


def check_duration(program) -> QualityCheck:
    duration = program.total_duration_seconds
    if duration > MAX_SCENE_SECONDS:
        return _failed("timeline_over_budget", "total_duration_seconds", "scene duration exceeds the 12-second budget")
    if duration < MIN_SCENE_SECONDS:
        return _failed("timeline_duration_out_of_bounds", "total_duration_seconds", "scene duration is below the 6-second minimum")
    return _passed("timeline_duration", "total_duration_seconds")


def check_grouped_simple_reveals(plan, program) -> QualityCheck:
    ordered_refs = {
        visual.ref for visual in [plan.primary_visual, *plan.supporting_visuals]
        if visual.kind == "ordered_values"
    }
    serial = [
        index for index, entry in enumerate(program.timeline)
        if entry.action.kind == "reveal"
        and entry.action.mode != "together"
        and any(target.visual_ref in ordered_refs for target in entry.action.targets)
    ]
    if serial:
        return _failed("serial_simple_reveal", f"timeline[{serial[0]}].action.mode", "ordered values must reveal together")
    return _passed("serial_simple_reveal", "timeline")


def check_answer_timing(plan, program) -> QualityCheck:
    answer = next((visual for visual in program.visuals if visual.ref == "evaluated_answer"), None)
    if answer is not None and getattr(answer, "initial_role", "neutral") != "neutral":
        return _failed("premature_answer_emphasis", "visuals.evaluated_answer.initial_role", "the evaluated answer must begin neutral")

    conclusions = {beat.id for beat in plan.beats if beat.kind == "conclude"}
    premature = [
        index for index, entry in enumerate(program.timeline)
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
        and entry.beat_id not in conclusions
    ]
    if premature:
        return _failed("premature_answer_emphasis", f"timeline[{premature[0]}].beat_id", "the evaluated answer may only appear in conclude")
    return _passed("premature_answer_emphasis", "visuals.evaluated_answer")


def check_conclusion_hold(program) -> QualityCheck:
    answer_entries = [
        entry for entry in program.timeline
        if _targets(entry.action) and any(target.visual_ref == "evaluated_answer" for target in _targets(entry.action))
    ]
    if not answer_entries:
        return _passed("conclusion_hold_too_short", "timeline")
    conclusion_end = max(entry.at_seconds + entry.duration_seconds for entry in answer_entries)
    shortest_conclusion_action = min(entry.duration_seconds for entry in answer_entries)
    if (
        shortest_conclusion_action + 1e-9 < MIN_CONCLUSION_HOLD_SECONDS
        or conclusion_end > program.total_duration_seconds + 1e-9
    ):
        return _failed("conclusion_hold_too_short", "timeline", "the conclusion must remain visible for at least 1.5 seconds")
    return _passed("conclusion_hold_too_short", "timeline")


def check_unexplained_idle_time(program) -> QualityCheck:
    cursor = 0.0
    for index, entry in enumerate(sorted(program.timeline, key=lambda item: item.at_seconds)):
        if entry.at_seconds - cursor > 0.25:
            return _failed("unexplained_idle_time", f"timeline[{index}].at_seconds", "timeline contains an idle interval without a teaching action")
        cursor = max(cursor, entry.at_seconds + entry.duration_seconds)
    return _passed("unexplained_idle_time", "timeline")


def check_strategy_affordance(plan, program) -> QualityCheck:
    if plan.strategy != "boundary_trace":
        return _passed("static_process_visual", "strategy")
    has_boundary_trace = any(
        entry.action.kind == "trace" and entry.action.path_ref.endswith(".perimeter")
        for entry in program.timeline
    )
    if not has_boundary_trace:
        return _failed("static_process_visual", "timeline", "boundary-trace instruction needs a visible perimeter trace")
    return _passed("static_process_visual", "timeline")


def check_semantic_anchor_specificity(plan, program) -> QualityCheck:
    item_targets = {
        (target.visual_ref, target.part, target.index)
        for beat in plan.beats for target in beat.targets
        if target.part is not None and target.index is not None
    }
    for relation_index, relation in enumerate(program.relations):
        for visual_ref, part, index in item_targets:
            if relation.target.visual_ref == visual_ref and (relation.target.part, relation.target.index) != (part, index):
                return _failed(
                    "collection_anchor_for_item", f"relations[{relation_index}].target",
                    "item-specific instruction needs an item-specific relation anchor",
                )
    return _passed("collection_anchor_for_item", "relations")


def check_dimension_anchor_specificity(plan, program) -> QualityCheck:
    for relation_index, relation in enumerate(program.relations):
        if "dimension" in relation.ref and relation.target.part != "edge":
            return _failed(
                "dimension_anchor_mismatch", f"relations[{relation_index}].target",
                "dimension labels must attach to a rectangle edge anchor",
            )
    return _passed("dimension_anchor_mismatch", "relations")


def check_salience(program) -> QualityCheck:
    focus_by_start = {}
    for entry in program.timeline:
        if entry.action.kind != "set_role" or entry.action.role != "focus":
            continue
        targets = tuple((target.visual_ref, target.part, target.index) for target in _targets(entry.action))
        focus_by_start.setdefault(entry.at_seconds, set()).update(targets)
    collision = next((second for second, targets in focus_by_start.items() if len(targets) > 1), None)
    if collision is not None:
        return _failed("callout_collision", "timeline", "multiple unrelated focus targets compete at one instant")

    anchors = {}
    for relation in program.relations:
        key = (relation.target.visual_ref, relation.target.part, relation.target.index, relation.target.anchor)
        if key in anchors:
            return _failed("callout_collision", "relations", "multiple callouts share one anchor")
        anchors[key] = relation.ref
    return _passed("callout_collision", "timeline")


def _targets(action):
    if hasattr(action, "targets"):
        return action.targets
    if hasattr(action, "target"):
        return [action.target]
    return []


def _passed(code: str, path: str) -> QualityCheck:
    return QualityCheck(code=code, passed=True, path=path, detail="passed")


def _failed(code: str, path: str, detail: str) -> QualityCheck:
    return QualityCheck(code=code, passed=False, path=path, detail=detail)
