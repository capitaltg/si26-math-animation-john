"""Structured, reviewer-safe pedagogical quality gates for v3 candidates."""

from dataclasses import asdict, dataclass

from app.meta.dsl.v3_common import (
    MAX_SCENE_SECONDS,
    MIN_CONCLUSION_HOLD_SECONDS,
    MIN_SCENE_SECONDS,
)
from app.meta.v3.errors import V3Failure, V3ValidationError

# Semantic parts that name a rectangle's length/width dimension edges (see
# `app/meta/v3/rectangle_measurement.py`). Used by
# `app/render/dynamic_render_worker.py`'s rendered-quality probe to key its
# observed `dimension_anchor_checks`/`declared_dimension_anchors` evidence --
# a compiled relation ref never contains the substring "dimension" (the beat
# expander names callout relations `callout_{beat}_{action}` or
# `median_callout`; see `app/meta/v3/beat_expander.py`), so identification
# must key off the relation's typed target part instead of the free-form ref
# string. `check_dimension_anchor_specificity` below identifies a *candidate*
# dimension callout more broadly, by the target visual's kind rather than
# this specific part set -- see that function's docstring.
DIMENSION_TARGET_PARTS = frozenset({"length_edge", "width_edge"})


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
        check_repeated_reveal(program),
        check_unused_visual(program),
        check_duplicate_dimension_label(program),
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

    # Only the FINAL beat may be `conclude`
    # (`TeachingPlanDocument.require_focus_and_conclusion_order`), so the one
    # beat in which the evaluated answer may legally appear is the last one.
    # Building this set from *every* `conclude` beat instead made any
    # mid-scene conclusion a legal place to reveal the answer -- so the check
    # named `premature_answer_emphasis` passed on exactly the premature
    # emphasis it exists to catch. Kept as an independent second layer: if the
    # plan schema's beat-order rule is ever relaxed, this check still fails
    # the candidate rather than silently reporting success.
    conclusions = {plan.beats[-1].id} if plan.beats[-1].kind == "conclude" else set()
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
    # A relation anchored to a whole collection cannot point at one of its
    # items, so a plan that instructs on individual items needs item-level
    # relation anchors. Quantify over the *relations*: the previous form
    # required each relation to match EVERY item target in the plan, so as soon
    # as two beats named different items of the same visual, any relation on
    # that visual mismatched at least one of them and the check failed -- on
    # plans whose anchors were already item-specific. That rejected legitimate
    # `pair_elimination` candidates (naming two items is how pairing is taught)
    # and told the repair loop to make an anchor item-specific when it already
    # was, so retries could not converge.
    visuals_with_item_instruction = {
        target.visual_ref
        for beat in plan.beats for target in beat.targets
        if target.part is not None and target.index is not None
    }
    for relation_index, relation in enumerate(program.relations):
        if relation.target.visual_ref in visuals_with_item_instruction and (
            relation.target.part is None or relation.target.index is None
        ):
            return _failed(
                "collection_anchor_for_item", f"relations[{relation_index}].target",
                "item-specific instruction needs an item-specific relation anchor",
            )
    return _passed("collection_anchor_for_item", "relations")


def check_dimension_anchor_specificity(plan, program) -> QualityCheck:
    # A compiled ref carries no "this is a dimension callout" marker (the beat
    # expander names callout relations `callout_{beat}_{action}` or
    # `median_callout`; see `app/meta/v3/beat_expander.py`), and the callout's
    # free-form text is untrusted generated content, not a reliable signal
    # either. So identify a candidate dimension callout by what IS trustworthy
    # and typed: any callout relation whose target names a
    # `rectangle_measurement` visual. Such a relation must name a specific
    # part AND index (e.g. the `length_edge`/`width_edge` alias parts the
    # rendered-quality probe selects on in `app/render/dynamic_render_worker.py`,
    # or a plain numbered `edge`/`vertex`) -- `compiler.py`'s `_validate_target`
    # returns immediately for a target with no `part` at all
    # (`_validate_callout_anchor` only restricts `ordered_values` items, never
    # `rectangle_measurement`), so a callout can compile cleanly while naming
    # the whole rectangle instead of one of its edges. That candidate is
    # rejected here, at the quality gate where the failure is reportable as
    # structured evidence, not by loosening the compiler's schema.
    visual_kind_by_ref = {visual.ref: visual.kind for visual in program.visuals}
    for relation_index, relation in enumerate(program.relations):
        target = relation.target
        if visual_kind_by_ref.get(target.visual_ref) != "rectangle_measurement":
            continue
        if target.part is None or target.index is None:
            return _failed(
                "dimension_anchor_mismatch", f"relations[{relation_index}].target",
                "a callout on a rectangle must attach to a specific edge, not the whole rectangle",
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


def check_duplicate_dimension_label(program) -> QualityCheck:
    # `rectangle_measurement.measure_rectangle` measures and labels its own
    # length and width from the `length`/`width` expressions, so those values
    # re-resolve per render and a reused template labels each problem's own
    # numbers. A callout on the same edge writes a second label into the space
    # the intrinsic one occupies -- and could not carry a live value anyway,
    # since `CalloutRelation.text` is a plain string fixed at generation time.
    # Callouts on any other anchor (a plain numbered `edge`, a `vertex`) remain
    # available; `check_dimension_anchor_specificity` still governs those.
    visual_kind_by_ref = {visual.ref: visual.kind for visual in program.visuals}
    for relation_index, relation in enumerate(program.relations):
        target = relation.target
        if visual_kind_by_ref.get(target.visual_ref) != "rectangle_measurement":
            continue
        if target.part in DIMENSION_TARGET_PARTS:
            return _failed(
                "duplicate_dimension_label", f"relations[{relation_index}].target.part",
                "the rectangle already labels this dimension, so the callout repeats it",
            )
    return _passed("duplicate_dimension_label", "relations")


def check_repeated_reveal(program) -> QualityCheck:
    # Revealing an already-revealed target fades the same mobject in a second
    # time, which reads as the visual being drawn twice. The beat expander used
    # to emit one `reveal` per `orient`/`reveal` beat with no record of what was
    # already revealed, so two beats naming one visual produced two fade-ins.
    revealed = set()
    for index, entry in enumerate(program.timeline):
        if entry.action.kind != "reveal":
            continue
        for target in entry.action.targets:
            key = (target.visual_ref, target.part, target.index)
            if key in revealed:
                return _failed(
                    "repeated_reveal", f"timeline[{index}].action.targets",
                    "a target may only be revealed once",
                )
            revealed.add(key)
    return _passed("repeated_reveal", "timeline")


def check_unused_visual(program) -> QualityCheck:
    # Nothing adds a visual to the manim scene except an animation that names
    # it, so a visual absent from the whole timeline never becomes visible --
    # while still consuming layout space, shrinking everything else to make
    # room for something the viewer never sees. Count every way a visual can be
    # named: action targets, a `trace`/`move` path it owns, and callout anchors.
    used = set()
    for entry in program.timeline:
        used.update(target.visual_ref for target in _targets(entry.action))
        path_ref = getattr(entry.action, "path_ref", None)
        if path_ref:
            used.add(path_ref.partition(".")[0])
    used.update(relation.target.visual_ref for relation in program.relations)
    for index, visual in enumerate(program.visuals):
        if visual.ref not in used:
            return _failed(
                "unused_visual", f"visuals[{index}].ref",
                "every declared visual must be named by a timeline action",
            )
    return _passed("unused_visual", "visuals")


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
