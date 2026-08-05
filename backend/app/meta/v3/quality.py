"""Structured, reviewer-safe pedagogical quality gates for v3 candidates."""

from dataclasses import asdict, dataclass

from app.meta.dsl.v3_common import (
    MAX_SCENE_SECONDS,
    MIN_CONCLUSION_HOLD_SECONDS,
    MIN_SCENE_SECONDS,
)
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.expression_display import has_operation
from app.meta.v3.visual_registry import DEFERRED_PARTS

# Semantic parts that name a rectangle's length/width dimension edges (see
# `app/meta/v3/rectangle_measurement.py`). `check_dimension_anchor_specificity`
# below identifies a *candidate* dimension callout more broadly, by the target
# visual's kind rather than this specific part set -- see that function's
# docstring.
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
            # The retry loop only forwards `code`, `path`, and `hint` to the
            # model (`_STABLE_REPAIR_FEEDBACK_FIELDS` in
            # `app/meta/draft_generation.py`), so the per-check diagnosis has to
            # travel through `hint` or the model never hears what is wrong and
            # proposes the same repair unchanged. Every `_failed(...)` site
            # already phrases `detail` as an actionable diagnosis; the previous
            # generic hint just clobbered it.
            raise V3ValidationError(V3Failure(
                code=failed.code,
                path=failed.path,
                expected="quality check to pass",
                observed=failed.detail,
                hint=failed.detail,
            ))


def validate_static_quality(plan, program) -> QualityReport:
    checks = [
        check_duration(program),
        check_grouped_simple_reveals(plan, program),
        check_answer_timing(plan, program),
        check_answer_stand_in(program),
        check_answer_work_shown(program),
        check_answer_stage_target(program),
        check_conclusion_hold(program),
        # Before the idle-interval check: an empty beat IS the cause of the gap,
        # and `require_passed` reports the first failure, so the named cause has
        # to come before the anonymous symptom.
        check_every_beat_acts(plan, program),
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
    """The answer is posed early as "? unit" and resolved only at conclude.

    This check used to require the opposite -- that `evaluated_answer` appear
    ONLY in conclude -- because the answer was a card drawn at the end. Now the
    unresolved placeholder is what the first beat reveals, and the resolved
    value is a stage transition, so the timing contract moves with it.
    """
    answer = next((visual for visual in program.visuals if visual.ref == "evaluated_answer"), None)
    if answer is None:
        # `pair_elimination` states its answer with one of its own values.
        return _passed("premature_answer_emphasis", "visuals")
    # The ref is reserved for the compiler-supplied `answer_expression` visual
    # (see `BeatExpander.expand`, which appends it). Nothing in the plan schema
    # stops a plan from declaring its own visual under that name -- and a
    # non-`answer_expression` shape reaches `check_answer_work_shown`'s
    # `answer.expression` access as an `AttributeError`, not a quality failure.
    # Fail loudly here instead.
    if answer.kind != "answer_expression":
        return _failed(
            "premature_answer_emphasis", "visuals.evaluated_answer.kind",
            "the ref `evaluated_answer` is reserved for the compiler-supplied answer visual; "
            f"a plan-declared {answer.kind!r} visual must use a different name",
        )
    if getattr(answer, "initial_role", "neutral") != "neutral":
        return _failed(
            "premature_answer_emphasis", "visuals.evaluated_answer.initial_role",
            "the evaluated answer must begin neutral",
        )

    reveals = [
        index for index, entry in enumerate(program.timeline)
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    ]
    # The first beat that ACTS, not `plan.beats[0]`: a beat compiling to nothing
    # contributes no timeline entry at all, so the reveal of a correct lesson can
    # sit in a later plan beat than the zeroth. What catches a silent beat 0 is
    # `check_every_beat_acts`, in this same report -- so relaxing that check would
    # also let this one accept a late placeholder.
    first_beat_id = program.timeline[0].beat_id
    if len(reveals) != 1 or program.timeline[reveals[0]].beat_id != first_beat_id:
        return _failed(
            "answer_placeholder_missing", "timeline",
            "the unresolved answer must be revealed exactly once, in the first beat, "
            "so the lesson poses its question before answering it",
        )

    # Only the FINAL beat may be `conclude`
    # (`TeachingPlanDocument.require_focus_and_conclusion_order`), so that is the
    # one beat in which the resolved value may appear. Kept as an independent
    # second layer: if the plan schema's beat-order rule is ever relaxed, this
    # check still fails the candidate rather than silently reporting success.
    # Together with the kind gate above, this function is the sole gate against
    # a plan hijacking the `evaluated_answer` ref -- a reachability-annotation
    # pass that retires either branch as dead would silently reopen the hole.
    conclusion_id = plan.beats[-1].id if plan.beats[-1].kind == "conclude" else None
    seen = []
    for index, entry in enumerate(program.timeline):
        if entry.action.kind != "show_answer_stage":
            continue
        stage = entry.action.stage
        if stage in seen:
            return _failed(
                "premature_answer_emphasis", f"timeline[{index}].action.stage",
                f"the {stage} stage is shown more than once",
            )
        seen.append(stage)
        if stage == "value" and entry.beat_id != conclusion_id:
            return _failed(
                "premature_answer_emphasis", f"timeline[{index}].beat_id",
                "the resolved answer may only appear in conclude",
            )
    if seen not in (["value"], ["work", "value"]):
        return _failed(
            "premature_answer_emphasis", "timeline",
            f"answer stages must be shown before resolving; found {seen}",
        )
    return _passed("premature_answer_emphasis", "visuals.evaluated_answer")


def check_conclusion_hold(program) -> QualityCheck:
    """Every action of the final acting beat must hold for the floor.

    Scoped to that beat rather than to every entry naming `evaluated_answer`:
    the answer is now revealed in the FIRST beat too, and that short reveal
    would otherwise set the minimum and fail the check on a correct lesson.
    `timeline.schedule_beats` identifies its own conclusion the same way.
    """
    final_beat_id = program.timeline[-1].beat_id
    conclusion_entries = [entry for entry in program.timeline if entry.beat_id == final_beat_id]
    conclusion_end = max(entry.at_seconds + entry.duration_seconds for entry in conclusion_entries)
    shortest_conclusion_action = min(entry.duration_seconds for entry in conclusion_entries)
    if (
        shortest_conclusion_action + 1e-9 < MIN_CONCLUSION_HOLD_SECONDS
        or conclusion_end > program.total_duration_seconds + 1e-9
    ):
        return _failed("conclusion_hold_too_short", "timeline", "the conclusion must remain visible for at least 1.5 seconds")
    return _passed("conclusion_hold_too_short", "timeline")


def check_every_beat_acts(plan, program) -> QualityCheck:
    """Every beat must reach the timeline.

    `docs/meta-template-dsl-v3-design.md`: "every beat produces an observable
    state change". A beat that compiles to nothing -- a second `reveal` naming an
    already-revealed visual, or a role change restating the role a target already
    holds -- contributes no timeline entry at all, so the only symptom was
    `unexplained_idle_time` at the index of the NEXT action. That named neither
    the beat nor the reason, leaving the repair loop nothing to act on. Name the
    beat instead.
    """
    acted = {entry.beat_id for entry in program.timeline}
    for index, beat in enumerate(plan.beats):
        if beat.id in acted:
            continue
        return _failed(
            "beat_without_action", f"beats[{index}].id",
            f"beat {beat.id!r} ({beat.kind}) produces no observable state change; "
            "give it a target it changes, or drop it and let the neighbouring beats hold its time",
        )
    return _passed("beat_without_action", "beats")


def check_unexplained_idle_time(program) -> QualityCheck:
    cursor = 0.0
    for index, entry in enumerate(sorted(program.timeline, key=lambda item: item.at_seconds)):
        if entry.at_seconds - cursor > 0.25:
            return _failed("unexplained_idle_time", f"timeline[{index}].at_seconds", "timeline contains an idle interval without a teaching action")
        cursor = max(cursor, entry.at_seconds + entry.duration_seconds)
    return _passed("unexplained_idle_time", "timeline")


def check_strategy_affordance(plan, program) -> QualityCheck:
    if plan.strategy in {"unit_substitution", "unit_rate"}:
        # The lesson's whole move is the exchange, so the target unit's labels
        # have to reach the screen. The compiler stages this reveal; the check
        # exists because a strategy whose affordance is optional is decorative.
        has_substitution = any(
            entry.action.kind == "reveal"
            and any(target.part == "target_label" for target in entry.action.targets)
            for entry in program.timeline
        )
        if not has_substitution:
            return _failed(
                "static_process_visual", "timeline",
                f"{plan.strategy} instruction needs the target unit's labels revealed",
            )
        if plan.strategy == "unit_rate":
            # `unit_rate` adds a per-one emphasis on box[0]; without it the
            # lesson is indistinguishable from `unit_substitution`.
            primary_ref = plan.primary_visual.ref
            reveal_entry = next(
                (
                    entry for entry in program.timeline
                    if entry.action.kind == "reveal"
                    and any(target.part == "target_label" for target in entry.action.targets)
                ),
                None,
            )
            # Effective role of box[0] at the *end* of the reveal beat.
            # Scoping by the reveal entry's `at_seconds` alone would miss
            # actions scheduled in the same beat after the reveal (a custom
            # whole-tape focus attached to the reveal beat lands later on the
            # timeline but is still part of the compiler-owned reveal beat's
            # final state). Use plan beat order and include every entry in
            # prior beats or the reveal beat itself, sorted by at_seconds so
            # a later-appended entry is not missed by list order. A
            # whole-visual `set_role` restyles descendants in the renderer
            # (`build_role_transition` recolours the whole group), so it
            # OVERWRITES any earlier explicit box[0] role -- preserving the
            # older one would let a plan reset the tape to `structure` after
            # box[0] was focused and still pass, while the frame shows no
            # per-one emphasis.
            reveal_beat_id = reveal_entry.beat_id if reveal_entry is not None else None
            beat_order = {beat.id: index for index, beat in enumerate(plan.beats)}
            reveal_beat_index = beat_order.get(reveal_beat_id) if reveal_beat_id is not None else None
            box_zero_role = None
            whole_visual_role = None
            entries_through_reveal = (
                sorted(
                    (
                        entry for entry in program.timeline
                        if entry.beat_id in beat_order
                        and beat_order[entry.beat_id] <= reveal_beat_index
                    ),
                    key=lambda entry: entry.at_seconds,
                )
                if reveal_beat_index is not None else []
            )
            for entry in entries_through_reveal:
                if entry.action.kind == "set_role":
                    target = entry.action.target
                    if target.visual_ref == primary_ref:
                        if target.part == "box" and target.index == 0:
                            box_zero_role = entry.action.role
                        elif target.part is None:
                            whole_visual_role = entry.action.role
                            box_zero_role = entry.action.role
            effective_box_zero_role = box_zero_role or whole_visual_role
            if effective_box_zero_role != "focus":
                return _failed(
                    "static_process_visual", "timeline",
                    "unit_rate instruction needs box[0] focused as the per-one column",
                )
            # The rate is *only* box[0]. Any active whole-tape focus at the
            # reveal beat -- whether emitted on the reveal beat or an earlier
            # one that never reset it -- makes every column read as equally
            # salient and defeats the per-one emphasis. `whole_visual_role`
            # tracks the effective whole-visual role through the reveal, so
            # a same-beat focus and a stale earlier focus are both caught.
            if whole_visual_role == "focus":
                return _failed(
                    "static_process_visual", "timeline",
                    "unit_rate reveal beat must not focus the whole primary visual",
                )
        return _passed("static_process_visual", "timeline")
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
    revealed_wholes = set()
    deferred = {
        visual.ref: DEFERRED_PARTS.get(visual.kind, ()) for visual in program.visuals
    }
    for index, entry in enumerate(program.timeline):
        if entry.action.kind != "reveal":
            continue
        for target in entry.action.targets:
            key = (target.visual_ref, target.part, target.index)
            # A whole-visual reveal brings its children on screen with it, so a
            # later reveal of one of those parts is a repeat -- unless the visual
            # declares that part deferred, in which case the whole-visual reveal
            # never showed it and this is its first appearance.
            is_deferred = target.part in deferred.get(target.visual_ref, ())
            if key in revealed or (target.visual_ref in revealed_wholes and not is_deferred):
                return _failed(
                    "repeated_reveal", f"timeline[{index}].action.targets",
                    "a target may only be revealed once, and revealing a visual "
                    "reveals its parts with it",
                )
            revealed.add(key)
            if target.part is None:
                revealed_wholes.add(target.visual_ref)
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


def check_answer_stand_in(program) -> QualityCheck:
    """No model-authored text may stand in for the answer.

    The system supplies the answer statement, so a label like "? meters" is a
    second, dead answer competing with it -- which is exactly what the
    kilometers draft produced. A question prompt is legitimate teaching, and a
    stand-in is distinguishable from one without reading the wording: a stand-in
    uses "?" as a value, so the mark sits mid-string (or is the whole of it),
    while a question ends with it.

    Relation text is held to the same rule. `CalloutRelation.text` is the DSL's
    only other model-authored text surface, so a callout reading "? meters"
    anchored to the primary visual produces the identical dead placeholder while
    passing a check that only walked `program.visuals`.
    """
    for index, visual in enumerate(program.visuals):
        if visual.kind != "label":
            continue
        if _stands_in_for_the_answer(visual.text):
            return _failed(
                "answer_stand_in_label", f"visuals[{index}].text",
                "this label stands in for the answer; the system supplies the answer "
                "statement, so remove the label and name the unit in answer_unit",
            )
    for index, relation in enumerate(program.relations):
        if _stands_in_for_the_answer(relation.text):
            return _failed(
                "answer_stand_in_label", f"relations[{index}].text",
                "this callout stands in for the answer; the system supplies the answer "
                "statement, so word the callout as teaching and name the unit in answer_unit",
            )
    return _passed("answer_stand_in_label", "visuals")


def check_answer_work_shown(program) -> QualityCheck:
    """An answer with arithmetic must show that arithmetic before resolving.

    Without this, a `derive` beat whose targets already hold their role compiles
    to a bare recolour and the lesson states its answer having demonstrated
    nothing -- the kilometers lesson's original failing.
    """
    answer = next((visual for visual in program.visuals if visual.ref == "evaluated_answer"), None)
    # A plan-declared non-`answer_expression` under this ref has no `.expression`
    # attribute; `check_answer_timing` has already reported it, so treat the shape
    # as unreachable rather than crashing on the attribute access.
    if answer is None or answer.kind != "answer_expression" or not has_operation(answer.expression):
        return _passed("answer_work_not_shown", "timeline")
    if not any(
        entry.action.kind == "show_answer_stage" and entry.action.stage == "work"
        for entry in program.timeline
    ):
        return _failed(
            "answer_work_not_shown", "timeline",
            "the answer's arithmetic is never shown; give the lesson a derive or focus "
            "beat before its conclusion so the calculation appears before the answer",
        )
    return _passed("answer_work_not_shown", "timeline")


def check_answer_stage_target(program) -> QualityCheck:
    """A `show_answer_stage` action must name a stage that actually exists.

    `ShowAnswerStageAction.target` is a plain `TargetRef`, unconstrained by the
    action's own schema, and `resolver.evaluate_program_visual` only ever builds
    a `stages` dict for the `answer_expression` visual -- `work` is even in that
    dict only when `has_operation` is true (see `evaluate_program_visual`'s
    `answer_expression` branch). `_action_animation`
    (`app/meta/v3/renderer.py`) looks the stage up with
    `rendered.answer_stages[target.visual_ref][stage]`, so a target that isn't
    that visual, or a `work` stage on an expression with no operation, is a
    `KeyError` at render time rather than a reported failure. Catch both here,
    the same way every other cross-reference in this module is caught.
    """
    answer = next((visual for visual in program.visuals if visual.kind == "answer_expression"), None)
    for index, entry in enumerate(program.timeline):
        if entry.action.kind != "show_answer_stage":
            continue
        target_ref = entry.action.target.visual_ref
        if answer is None or target_ref != answer.ref:
            return _failed(
                "answer_stage_undefined", f"timeline[{index}].action.target",
                f"show_answer_stage must target the declared answer visual, not {target_ref!r}",
            )
        if entry.action.stage == "work" and not has_operation(answer.expression):
            return _failed(
                "answer_stage_undefined", f"timeline[{index}].action.stage",
                "the work stage does not exist for an answer with no operation to show",
            )
    return _passed("answer_stage_undefined", "timeline")


def _stands_in_for_the_answer(text: str) -> bool:
    stripped = text.strip()
    return stripped == "?" or "?" in stripped[:-1]


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
