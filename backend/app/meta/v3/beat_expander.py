from dataclasses import dataclass

from app.meta.dsl.scene_program import (
    AnswerProgramVisual, BarProgramVisual, CalloutRelation, DrawAction,
    GridProgramVisual, LabelProgramVisual, MoveAction, NumberLineProgramVisual,
    ObjectSetProgramVisual, OrderedValuesProgramVisual, PartitionProgramVisual,
    ProgramAction, RectangleProgramVisual, RevealAction, SetRoleAction,
    ShowAnswerStageAction, ShowRelationAction, TraceAction, TransformAction,
)
from app.meta.dsl.v3_common import TargetRef
from app.meta.v3.expression_display import has_operation


@dataclass(frozen=True)
class ExpandedBeat:
    beat_id: str
    actions: list[ProgramAction]
    minimum_seconds: float
    weight: float
    slot_count: int | None = None


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

#: Seconds per eliminated pair. Below roughly a second the two partners change
#: colour faster than a learner can register that they were a pair.
_SECONDS_PER_PAIR = 1.3
#: `ordered_values` accepts up to 15 values (`dsl/limits.py`), and an uncapped
#: seven-pair minimum overruns `MAX_SCENE_SECONDS` and raises
#: `timeline_over_budget`. Capped, a long collection degrades to a faster pair
#: step instead of failing to compile.
_MAX_ELIMINATION_SECONDS = 6.0

#: Which semantic part each strategy's expander walks. Kept next to the strategy
#: tables here rather than derived from `_PART_CARDINALITY` in `compiler.py`,
#: which `beat_expander` cannot import (compiler already depends on this module).
_REGROUP_PART = {"grid": "cell", "object_set": "item"}
_MAGNITUDE_PART = {"bar": "segment", "number_line": "marker"}


class BeatExpander:
    def __init__(self, *, answer_expression):
        self.answer_expression = answer_expression

    def expand(self, plan):
        visuals = [
            self._program_visual(spec, plan.strategy, primary=spec is plan.primary_visual)
            for spec in self._visual_specs(plan)
        ]
        if plan.strategy != "pair_elimination":
            # The answer is one of the collection's own values, already on
            # screen. Suppressed at declaration rather than at reveal because
            # `quality.check_unused_visual` fails any visual absent from the
            # timeline.
            visuals.append(AnswerProgramVisual(
                ref="evaluated_answer",
                expression=self.answer_expression,
                suffix=f" {plan.answer_unit}" if plan.answer_unit else "",
            ))
        initial_roles = {visual.ref: visual.initial_role for visual in visuals}
        # Keyed by `_target_key`, not by bare ref, so a part-level lookup can
        # fall back to its whole visual's role -- the renderer initialises every
        # child target to its parent's role, and role bookkeeping here has to
        # agree with it or `_role_change` cannot tell a real change from a no-op.
        current_roles = {(visual.ref, None, None): visual.initial_role for visual in visuals}
        previous_roles = {}
        relations = []
        expanded = []
        revealed = set()
        boundary_trace_beat_id = self._boundary_trace_beat_id(plan)
        answer_declared = any(visual.ref == "evaluated_answer" for visual in visuals)
        answer_target = TargetRef(visual_ref="evaluated_answer")
        work_beat_id = self._work_beat_id(plan) if answer_declared else None

        for beat_index, beat in enumerate(plan.beats):
            actions = self._standard_actions(
                plan, beat, relations, current_roles, revealed, boundary_trace_beat_id,
            )
            for action_index, request in enumerate(beat.custom_actions):
                actions.extend(self._custom_actions(
                    plan=plan,
                    request=request,
                    beat_index=beat_index,
                    action_index=action_index,
                    relations=relations,
                    initial_roles=initial_roles,
                    current_roles=current_roles,
                    previous_roles=previous_roles,
                    revealed=revealed,
                ))
            if answer_declared and beat_index == 0:
                # The unresolved "? unit" is on screen from the start, so the
                # lesson poses its question before answering it. A separate
                # reveal rather than an extra target on the beat: folding it in
                # would also subject the answer to the beat kind's own role
                # change, focusing it before anything has been derived.
                actions.extend(self._reveal_unrevealed(plan, [answer_target], revealed))
            if beat.id == work_beat_id:
                actions.append(
                    ShowAnswerStageAction(target=answer_target, stage="work")
                )
            minimum_seconds, weight = self._beat_timing(plan, beat)
            expanded.append(ExpandedBeat(
                beat_id=beat.id,
                actions=actions,
                minimum_seconds=minimum_seconds,
                weight=weight,
                slot_count=self._slot_count(plan, beat, actions),
            ))
        return visuals, relations, expanded

    @staticmethod
    def _visual_specs(plan):
        return [plan.primary_visual, *plan.supporting_visuals]

    @staticmethod
    def _program_visual(spec, strategy, *, primary):
        program_type, initial_role = _PROGRAM_VISUALS[spec.kind]
        if primary and spec.kind == "ordered_values" and strategy == "pair_elimination":
            # Elimination has to read as "these are dismissed", which needs the
            # items to start in a colour that dimming to `neutral` visibly
            # leaves. Born `neutral`, every dim is a grey-to-grey transform.
            initial_role = "structure"
        return program_type.model_validate({**spec.model_dump(), "initial_role": initial_role})

    def _work_beat_id(self, plan):
        """The beat that shows the answer's arithmetic, if there is any to show.

        `TeachingPlanDocument.require_focus_and_conclusion_order` guarantees a
        `focus` or `derive` beat before `conclude`, so a slot always exists. The
        last one is chosen so the work appears as late as possible while still
        preceding the conclusion.
        """
        if not has_operation(self.answer_expression):
            return None
        return next(
            beat.id for beat in reversed(plan.beats[:-1])
            if beat.kind in {"derive", "focus"}
        )

    @staticmethod
    def _beat_timing(plan, beat):
        minimum_seconds, weight = _BEAT_TIMING[beat.kind]
        if plan.strategy == "pair_elimination" and beat.kind == "organize":
            pair_count = (len(plan.primary_visual.values) - 1) // 2
            minimum_seconds = min(_SECONDS_PER_PAIR * pair_count, _MAX_ELIMINATION_SECONDS)
        return minimum_seconds, weight

    @staticmethod
    def _slot_count(plan, beat, actions):
        """Choose a slot count that groups related role changes into one instant.

        `timeline.schedule_beats` otherwise derives slots from the action count
        and plays every recolour in sequence, which reads as a left-to-right
        wave rather than as the strategy's own grouping.

        Derived from `len(actions)` rather than from a value count so a
        suppressed no-op cannot leave an empty slot.

        - pair_elimination organize: one slot per pair (two partners per slot).
        - regroup organize: one slot per row, alternating highlight and release
          (2R slots), so a whole row recolours together.
        - magnitude_comparison focus/derive: one slot per part, so the focus
          sweeps left to right and `check_salience` never sees two focus role
          changes at one instant.
        """
        if not actions:
            return None
        if plan.strategy == "pair_elimination" and beat.kind == "organize":
            return -(-len(actions) // 2)
        if plan.strategy == "regroup" and beat.kind == "organize":
            layout = _regroup_layout(plan.primary_visual)
            if layout is not None:
                rows, _columns, _count = layout
                return 2 * rows
        if plan.strategy == "magnitude_comparison" and beat.kind in {"focus", "derive"}:
            count = _magnitude_count(plan.primary_visual)
            if count is not None and count > 0:
                return count
        return None

    def _standard_actions(
        self, plan, beat, relations, current_roles, revealed, boundary_trace_beat_id,
    ):
        """Reveal whatever the beat names, then act on it, then add the strategy affordance.

        Every branch here used to `return` outright, so a beat matched by an
        earlier branch lost the actions of every later one. In particular the
        `boundary_trace` branch replaced the beat's own semantics, leaving the
        visual the beat named with no action at all.
        """
        actions = self._reveal_unrevealed(plan, beat.targets, revealed)
        actions.extend(self._beat_kind_actions(plan, beat, relations, current_roles))
        if plan.strategy == "boundary_trace" and beat.id == boundary_trace_beat_id:
            actions.append(TraceAction(path_ref=f"{plan.primary_visual.ref}.perimeter"))
        if not actions and not beat.custom_actions:
            actions.extend(self._attention_fallback(beat, current_roles))
        return actions

    def _attention_fallback(self, beat, current_roles):
        """Draw attention to the beat's targets when its kind had nothing left to do.

        Two ordinary shapes leave a beat with no action once no-ops are
        suppressed, and both are legitimate teaching:

        - a `reveal` naming a part of an already-revealed visual. The part is
          inside the group the reveal faded in (`_line_visual` puts marker dots
          there), so fading it again changes nothing -- but "now point out the
          endpoints" still has to show something.
        - an `organize` whose target already holds `structure`, which every
          structural primary visual does from the start.

        Moving attention to the target is observable, is what both intents mean,
        and needs no new action kind. A beat whose targets are ALL already in
        focus really is redundant, and `quality.check_every_beat_acts` still
        rejects it.
        """
        actions = []
        for target in beat.targets:
            actions.extend(self._role_change(target, "focus", current_roles))
        return actions

    def _reveal_unrevealed(self, plan, targets, revealed, mode=None):
        """Reveal only targets not already on screen.

        Nothing else adds a mobject to the manim scene, so an unrevealed target
        is invisible; revealing one twice fades the same mobject in twice, which
        reads as the visual being drawn two times over. Custom reveals share this
        path, so an author's `reveal` cannot re-fade something a beat already
        brought on screen.
        """
        pending = [target for target in targets if not self._is_revealed(target, revealed)]
        if not pending:
            return []
        revealed.update(self._target_key(target) for target in pending)
        if mode is None:
            mode = "stagger" if plan.strategy == "short_stagger" else "together"
        return [RevealAction(targets=pending, mode=mode)]

    @staticmethod
    def _is_revealed(target, revealed):
        # Revealing a whole visual reveals its parts with it, so a part-level
        # target is already on screen once its visual is.
        return (
            (target.visual_ref, target.part, target.index) in revealed
            or (target.visual_ref, None, None) in revealed
        )

    def _beat_kind_actions(self, plan, beat, relations, current_roles):
        if beat.kind in {"orient", "reveal"}:
            return []  # `_reveal_unrevealed` has already staged the reveal

        if beat.kind == "organize" and plan.strategy == "regroup":
            # Cycle each row of the primary visual through the `constraint`
            # accent and back to `structure`, so the collection reads as R
            # groups of C rather than one undifferentiated set. Without this
            # branch the beat falls through to `_generic_role_change`, which
            # asserts `structure` on the whole visual -- a no-op, since every
            # regroup-eligible visual is born `structure` -- and the animation
            # is indistinguishable from `group_reveal`.
            actions = self._regroup_actions(plan, current_roles)
            if actions:
                return actions

        if beat.kind in {"focus", "derive"} and plan.strategy == "magnitude_comparison":
            # Focus the primary visual's magnitude-carrying parts one at a
            # time, so the observed extent sweeps left to right and the
            # animation teaches the magnitude rather than asserting it. Without
            # this branch a magnitude_comparison plan on a `bar` or
            # `number_line` renders as a whole-visual focus -- the same shape
            # as `group_reveal`.
            actions = self._magnitude_comparison_actions(plan, current_roles)
            if actions:
                return actions

        if beat.kind == "organize" and plan.strategy == "pair_elimination":
            # Iterate pairs, not indices. The middle item is never reached, so
            # the old `if index == middle: continue` guard goes with the loop it
            # guarded -- and emitting a pair adjacently is what lets the
            # timeline batch both partners into one slot.
            count = len(plan.primary_visual.values)
            actions = []
            for offset in range(count // 2):
                for index in (offset, count - 1 - offset):
                    actions.extend(self._role_change(
                        TargetRef(visual_ref=plan.primary_visual.ref, part="item", index=index),
                        "neutral", current_roles,
                    ))
            return actions

        if beat.kind == "focus":
            return self._generic_role_change(beat, "focus", current_roles)

        if beat.kind == "derive":
            # "map visible structure into a calculation or relationship" -- the
            # targets being mapped are what the viewer must watch, and the spec
            # permits `focus` during `derive`. Rolling `derive` into the generic
            # `structure` fallthrough below made the beat a no-op whenever its
            # targets were already structural, which is every boundary-trace
            # plan: the primary visual starts `structure`.
            return self._generic_role_change(beat, "focus", current_roles)

        if beat.kind == "conclude":
            if plan.strategy == "pair_elimination":
                return self._median_callout(plan, beat, relations)
            # The answer is already on screen as "? unit", revealed in the first
            # beat, so conclude resolves it rather than introducing it.
            answer_target = TargetRef(visual_ref="evaluated_answer")
            return [
                ShowAnswerStageAction(target=answer_target, stage="value"),
                *self._role_change(answer_target, "conclusion", current_roles),
            ]

        return self._generic_role_change(beat, "structure", current_roles)

    def _regroup_actions(self, plan, current_roles):
        layout = _regroup_layout(plan.primary_visual)
        if layout is None:
            return []
        rows, columns, count = layout
        part = _REGROUP_PART[plan.primary_visual.kind]
        ref = plan.primary_visual.ref
        actions = []
        for row in range(rows):
            row_indices = [
                row * columns + col
                for col in range(columns)
                if row * columns + col < count
            ]
            for index in row_indices:
                actions.extend(self._role_change(
                    TargetRef(visual_ref=ref, part=part, index=index),
                    "constraint", current_roles,
                ))
            for index in row_indices:
                actions.extend(self._role_change(
                    TargetRef(visual_ref=ref, part=part, index=index),
                    "structure", current_roles,
                ))
        return actions

    def _magnitude_comparison_actions(self, plan, current_roles):
        count = _magnitude_count(plan.primary_visual)
        if count is None or count == 0:
            return []
        part = _MAGNITUDE_PART[plan.primary_visual.kind]
        ref = plan.primary_visual.ref
        actions = []
        for index in range(count):
            actions.extend(self._role_change(
                TargetRef(visual_ref=ref, part=part, index=index),
                "focus", current_roles,
            ))
        return actions

    def _median_callout(self, plan, beat, relations):
        """Name the surviving middle value -- unless the plan already names it.

        Two callouts on one anchor stack two labels in the same space, which
        `quality.check_salience` rejects outright, so defer to the author's own
        wording when there is any. Emitting no recolour here is deliberate: the
        median changes colour exactly once, at the focus beat.
        """
        middle = len(plan.primary_visual.values) // 2
        anchor = (plan.primary_visual.ref, "item", middle)
        if any(
            (action.target.visual_ref, action.target.part, action.target.index) == anchor
            for action in beat.custom_actions if action.kind == "callout"
        ):
            return []
        relations.append(CalloutRelation(
            ref="median_callout",
            target={
                "visual_ref": plan.primary_visual.ref, "part": "item",
                "index": middle, "anchor": "bottom",
            },
            text="median",
        ))
        return [ShowRelationAction(relation_ref="median_callout")]

    def _generic_role_change(self, beat, role, current_roles):
        """The kind's default role change, minus targets the beat details itself.

        When a beat's custom actions reach *inside* a whole-visual target -- and
        name that visual's semantic parts -- the author has already said which
        parts carry the emphasis, so a whole-visual transition on top would only
        compete with them. A custom action on the very same target is different:
        it modulates the role this change establishes (`focus`, then `dim`, then
        `restore` back to focus), so the two compose and both are emitted.
        """
        detailed = self._targets_detailed_by_custom_actions(beat)
        actions = []
        for target in beat.targets:
            if self._target_key(target) in detailed:
                continue
            actions.extend(self._role_change(target, role, current_roles))
        return actions

    @staticmethod
    def _targets_detailed_by_custom_actions(beat):
        parted_visuals = set()
        for action in beat.custom_actions:
            candidates = [
                *getattr(action, "targets", ()),
                *(
                    getattr(action, attribute)
                    for attribute in ("target", "source")
                    if getattr(action, attribute, None) is not None
                ),
            ]
            parted_visuals.update(
                target.visual_ref for target in candidates if target.part is not None
            )
        return {
            (target.visual_ref, target.part, target.index)
            for target in beat.targets
            if target.part is None and target.visual_ref in parted_visuals
        }

    @staticmethod
    def _boundary_trace_beat_id(plan):
        """The beat that needs a compiler-supplied perimeter trace, if any.

        `boundary_trace` requires a visible perimeter trace
        (`quality.check_strategy_affordance`). When the plan already declares one
        as a custom action, supplying a second traces the same boundary twice --
        two stacked accent-coloured paths over the shape, neither ever removed.
        """
        if plan.strategy != "boundary_trace":
            return None
        perimeter_path = f"{plan.primary_visual.ref}.perimeter"
        if any(
            action.kind == "trace" and action.path_ref == perimeter_path
            for beat in plan.beats for action in beat.custom_actions
        ):
            return None
        for beat in plan.beats:
            if beat.kind in {"organize", "derive", "focus"}:
                return beat.id
        return None

    def _role_change(self, target, role, current_roles):
        """A role change, or nothing when the target already holds that role.

        The renderer plays every `set_role` as a colour `Transform`, so
        re-asserting a role the target already has animates a recolour from a
        colour to itself -- a visible flicker mid-lesson that teaches nothing.
        """
        key = self._target_key(target)
        if self._current_role(key, current_roles) == role:
            return []
        current_roles[key] = role
        return [SetRoleAction(target=target, role=role)]

    @staticmethod
    def _current_role(key, current_roles):
        if key in current_roles:
            return current_roles[key]
        visual_ref, _part, _index = key
        return current_roles.get((visual_ref, None, None))

    def _custom_actions(
        self, *, plan, request, beat_index, action_index, relations,
        initial_roles, current_roles, previous_roles, revealed,
    ):
        kind = request.kind
        if kind == "reveal":
            return self._reveal_unrevealed(plan, request.targets, revealed, request.mode)
        if kind == "emphasize":
            return [self._set_role(request.target, request.role, current_roles)]
        if kind == "dim":
            key = self._target_key(request.target)
            previous_roles.setdefault(
                key, current_roles.get(key, initial_roles[request.target.visual_ref]),
            )
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


def _literal_int(expression):
    """Extract a whole-number literal, or return None if the expression is not one.

    The plan schema allows a visual's driving fields to be any `ExpressionNode`,
    so a regroup or magnitude_comparison plan may hand-write an addition or a
    field reference. Nothing here evaluates such expressions; the expander only
    walks parts whose count it can read at compile time.
    """
    if getattr(expression, "node", None) != "literal":
        return None
    value = expression.value
    if not float(value).is_integer():
        return None
    return int(value)


def _regroup_layout(spec):
    """Return (rows, columns, count) for the regroup walk, or None if unknown.

    Grid rows and columns are read from the plan; object_set inherits the
    5-per-row wrap the renderer uses in `_measure_object_set`. The two shapes
    are kept close to their measurement so a walk here and a mobject there
    address the same cells.
    """
    if spec.kind == "grid":
        rows = _literal_int(spec.rows)
        columns = _literal_int(spec.columns)
        if rows is None or columns is None or rows <= 0 or columns <= 0:
            return None
        return rows, columns, rows * columns
    if spec.kind == "object_set":
        count = _literal_int(spec.count)
        if count is None or count <= 0:
            return None
        columns = min(5, count)
        rows = -(-count // columns)
        return rows, columns, count
    return None


def _magnitude_count(spec):
    """Number of parts the magnitude sweep walks, or None if unknown."""
    if spec.kind == "bar":
        return _literal_int(spec.maximum)
    if spec.kind == "number_line":
        return len(spec.markers)
    return None
