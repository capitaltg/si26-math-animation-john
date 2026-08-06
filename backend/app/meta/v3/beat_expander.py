from dataclasses import dataclass

from app.meta.dsl.scene_program import (
    AnswerProgramVisual, BarProgramVisual, CalloutRelation,
    CoordinatePlaneProgramVisual, DataDisplayProgramVisual, DrawAction,
    GridProgramVisual, LabelProgramVisual, MoveAction, NumberLineProgramVisual,
    ObjectSetProgramVisual, OrderedValuesProgramVisual, PartitionProgramVisual,
    ProgramAction, RectangleProgramVisual, RevealAction, SetRoleAction,
    ShowAnswerStageAction, ShowRelationAction, TraceAction, TransformAction,
    UnitTapeProgramVisual,
)
from app.meta.dsl.v3_common import TargetRef
from app.meta.v3.expression_display import has_operation
from app.meta.v3.visual_registry import DEFERRED_PARTS


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
    "unit_tape": (UnitTapeProgramVisual, "structure"),
    "coordinate_plane": (CoordinatePlaneProgramVisual, "structure"),
    "data_display": (DataDisplayProgramVisual, "structure"),
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
        self._sweep_beat_id = magnitude_sweep_beat_id(plan)
        self._regroup_beat_id = regroup_beat_id(plan)
        self._inverse_partition_beat_id, self._inverse_divide_beat_id = (
            inverse_operation_beat_ids(plan)
        )
        self._ray_boundary_beat_id, self._ray_shade_beat_id = (
            ray_shade_beat_ids(plan)
        )
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
        self._deferred_parts = {
            spec.ref: DEFERRED_PARTS.get(spec.kind, ())
            for spec in self._visual_specs(plan)
        }
        unit_substitution_beat_id = self._unit_substitution_beat_id(plan)
        self._unit_rate_beat_id_state = (
            unit_substitution_beat_id if plan.strategy == "unit_rate" else None
        )
        answer_declared = any(visual.ref == "evaluated_answer" for visual in visuals)
        answer_target = TargetRef(visual_ref="evaluated_answer")
        work_beat_id = self._work_beat_id(plan) if answer_declared else None

        for beat_index, beat in enumerate(plan.beats):
            actions = self._standard_actions(
                plan, beat, relations, current_roles, revealed,
                boundary_trace_beat_id, unit_substitution_beat_id,
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

    def _slot_count(self, plan, beat, actions):
        """Choose a slot count that groups related role changes into one instant.

        `timeline.schedule_beats` otherwise derives slots from the action count
        and plays every recolour in sequence, which reads as a left-to-right
        wave rather than as the strategy's own grouping.

        Derived from `len(actions)` rather than from a value count so a
        suppressed no-op cannot leave an empty slot AND so a beat that also
        emits a `RevealAction` (an unrevealed target on the strategy's own
        beat) cannot push two role changes into one slot -- which would fail
        `check_salience` for `magnitude_comparison`'s focus role.

        - pair_elimination organize: paired items share a slot, one slot per
          pair. The organize beat never reveals the values (revealed by the
          prior beat by construction), so the pair-per-slot arithmetic is
          stable.
        - regroup organize: one slot per row, so a whole row recolours
          together -- but only when the actions ARE the strategy's own role
          changes. A beat that also emits a `RevealAction` is scheduled by
          the default rule so the reveal does not steal a row's slot.
        - magnitude_comparison sweep beat: one slot per action. Any batching
          would risk co-starting two `focus` role changes and failing
          `check_salience`.
        """
        if not actions:
            return None
        if plan.strategy == "pair_elimination" and beat.kind == "organize":
            return -(-len(actions) // 2)
        if (
            plan.strategy == "regroup"
            and beat.id == getattr(self, "_regroup_beat_id", None)
        ):
            layout = _regroup_layout(plan.primary_visual)
            if layout is None:
                return None
            _rows, _columns, count = layout
            if count == len(actions):
                return layout[0]
            return None
        if (
            plan.strategy == "magnitude_comparison"
            and beat.id == getattr(self, "_sweep_beat_id", None)
        ):
            return len(actions)
        return None

    def _standard_actions(
        self, plan, beat, relations, current_roles, revealed,
        boundary_trace_beat_id, unit_substitution_beat_id=None,
    ):
        """Reveal whatever the beat names, then act on it, then add the strategy affordance.

        Every branch here used to `return` outright, so a beat matched by an
        earlier branch lost the actions of every later one. In particular the
        `boundary_trace` branch replaced the beat's own semantics, leaving the
        visual the beat named with no action at all.
        """
        actions = self._reveal_unrevealed(plan, beat.targets, revealed)
        actions.extend(self._beat_kind_actions(plan, beat, relations, current_roles))
        if plan.strategy == "ray_shade":
            actions.extend(self._ray_shade_extra_actions(plan, beat, revealed))
        if plan.strategy == "boundary_trace" and beat.id == boundary_trace_beat_id:
            actions.append(TraceAction(path_ref=f"{plan.primary_visual.ref}.perimeter"))
        if beat.id == unit_substitution_beat_id:
            # Emitted directly rather than through `_reveal_unrevealed`: the group
            # part carries no index, which is the only way to name every box's
            # label when the box count depends on fixture params.
            actions.append(RevealAction(
                targets=[TargetRef(visual_ref=plan.primary_visual.ref, part="target_label")],
                mode="stagger",
            ))
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

    def _is_revealed(self, target, revealed):
        # Revealing a whole visual reveals its parts with it -- except the parts
        # the visual declares deferred, which the renderer keeps out of the root
        # group precisely so they can arrive later.
        if (target.visual_ref, target.part, target.index) in revealed:
            return True
        if target.part in self._deferred_parts.get(target.visual_ref, ()):
            return False
        return (target.visual_ref, None, None) in revealed

    def _beat_kind_actions(self, plan, beat, relations, current_roles):
        if beat.kind in {"orient", "reveal"}:
            return []  # `_reveal_unrevealed` has already staged the reveal

        if plan.strategy == "inverse_operation":
            actions = self._inverse_operation_actions(plan, beat, current_roles)
            if actions is not None:
                return actions

        if (
            plan.strategy == "regroup"
            and beat.id == getattr(self, "_regroup_beat_id", None)
        ):
            # Recolour each row of the primary visual to the `constraint`
            # accent, so the collection reads as R groups of C rather than
            # one undifferentiated set. Without this branch, the beat falls
            # through to `_generic_role_change` and the animation is
            # indistinguishable from `group_reveal`.
            # One beat owns the walk (see `regroup_beat_id`); later organize
            # beats behave normally, and an organize beat whose targets
            # do not include the primary visual never restyles it.
            actions = self._regroup_actions(plan, current_roles)
            if actions:
                return actions

        if (
            plan.strategy == "magnitude_comparison"
            and beat.id == getattr(self, "_sweep_beat_id", None)
        ):
            # Focus the primary visual's magnitude-carrying parts one at a
            # time, so the observed extent sweeps left to right and the
            # animation teaches the magnitude rather than asserting it.
            # Only one beat owns the sweep -- the first focus/derive beat that
            # names the primary visual -- and every later focus/derive beat
            # falls through to `_generic_role_change`, so two derive beats do
            # not double-stage one sweep.
            actions = self._magnitude_comparison_actions(plan, current_roles)
            if actions:
                return actions

        if (
            plan.strategy == "unit_rate"
            and beat.id == getattr(self, "_unit_rate_beat_id_state", None)
        ):
            # `unit_rate` teaches "one source unit is per_unit target units" by
            # emphasising the first box while the target labels arrive. Focus
            # box[0] rather than the whole tape so the per-one column reads as
            # the rate; a whole-tape focus would fall through to
            # `_generic_role_change` and put every box on equal footing.
            # Only the whole-primary target gets swapped for the box[0] focus;
            # other targets on the same beat (a supporting visual named by a
            # `derive`, for instance) still get their generic role change, so
            # this branch does not silently drop them.
            role = "focus" if beat.kind in {"focus", "derive"} else "structure"
            actions = list(self._unit_rate_actions(plan, current_roles))
            detailed = self._targets_detailed_by_custom_actions(beat)
            primary_ref = plan.primary_visual.ref
            for target in beat.targets:
                if target.visual_ref == primary_ref and target.part is None:
                    continue
                if self._target_key(target) in detailed:
                    continue
                actions.extend(self._role_change(target, role, current_roles))
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
        """Highlight each row's cells in one accented slot per row.

        Only a highlight is emitted, not a paired release: two actions per
        cell puts a 4x5 grid at 40 organize-beat actions on its own, which
        overruns the 40-entry timeline cap in `compiler.compile_teaching_plan`
        as soon as anything else needs a slot. Rows accumulate to `constraint`
        cumulatively, which reads as "here are the R groups, assembled" -- the
        following focus/derive beats can transition them onwards from there.
        """
        layout = _regroup_layout(plan.primary_visual)
        if layout is None:
            return []
        rows, columns, count = layout
        part = _REGROUP_PART[plan.primary_visual.kind]
        ref = plan.primary_visual.ref
        actions = []
        for row in range(rows):
            for col in range(columns):
                index = row * columns + col
                if index >= count:
                    break
                actions.extend(self._role_change(
                    TargetRef(visual_ref=ref, part=part, index=index),
                    "constraint", current_roles,
                ))
        return actions

    def _magnitude_comparison_actions(self, plan, current_roles):
        """Focus the magnitude-carrying parts left-to-right.

        `_magnitude_indices` returns the walk order: `bar` walks `value` many
        segments (the actual magnitude, not the bar's capacity); `number_line`
        walks its markers sorted by resolved value, so a plan that declares
        markers out of numeric order still sweeps left to right.

        `validate_strategy_compatibility` refuses `magnitude_comparison` when
        the driving field is not a literal, so this returns None at most from
        a wholly-unsupported kind, not from a plan that would have compiled.
        """
        indices = _magnitude_indices(plan.primary_visual)
        if not indices:
            return []
        part = _MAGNITUDE_PART[plan.primary_visual.kind]
        ref = plan.primary_visual.ref
        actions = []
        for index in indices:
            actions.extend(self._role_change(
                TargetRef(visual_ref=ref, part=part, index=index),
                "focus", current_roles,
            ))
        return actions

    def _inverse_operation_actions(self, plan, beat, current_roles):
        """Stage the equation's partition on the bar, one beat at a time.

        Return `None` when this beat is not one of the strategy's owned beats
        so the caller falls through to the generic role change; otherwise
        return the actions that visibly teach the inverse operation.

        - partition beat (the first derive/focus beat naming the primary):
          set constant_region to `constraint` (the known addend, dimmed) and
          x_region to `focus` (what remains after subtracting it).
        - divide beat (only when coefficient > 1, the second such beat): focus
          each x_part in turn, so the "divide by k" reads as slicing the
          x_region into k equal pieces.
        """
        if plan.primary_visual.kind != "bar":
            return None
        if plan.primary_visual.constant is None:
            return None
        ref = plan.primary_visual.ref
        if beat.id == getattr(self, "_inverse_partition_beat_id", None):
            return [
                *self._role_change(
                    TargetRef(visual_ref=ref, part="constant_region", index=0),
                    "constraint", current_roles,
                ),
                *self._role_change(
                    TargetRef(visual_ref=ref, part="x_region", index=0),
                    "focus", current_roles,
                ),
            ]
        if beat.id == getattr(self, "_inverse_divide_beat_id", None):
            coefficient_spec = plan.primary_visual.coefficient
            coefficient = int(coefficient_spec.value) if coefficient_spec else 1
            actions = []
            for index in range(coefficient):
                actions.extend(self._role_change(
                    TargetRef(visual_ref=ref, part="x_part", index=index),
                    "focus", current_roles,
                ))
            return actions
        return None

    def _ray_shade_extra_actions(self, plan, beat, revealed):
        """Reveal the boundary circle then the shaded ray, in beat order.

        The boundary and ray parts are deferred (see
        `visual_registry.DEFERRED_PARTS`), so the whole-line reveal on the
        first beat leaves them off-screen; each arrives on its own beat.
        The boundary reveal rides the `focus_boundary` beat (first
        focus/derive beat naming primary), and the ray reveal rides the
        `shade_ray` beat (the next one), so the inequality lands as
        "boundary here, everything to the right shaded".
        """
        if plan.primary_visual.kind != "number_line":
            return []
        if plan.primary_visual.boundary is None:
            return []
        ref = plan.primary_visual.ref
        if beat.id == getattr(self, "_ray_boundary_beat_id", None):
            target = TargetRef(visual_ref=ref, part="boundary", index=0)
            return self._reveal_unrevealed(plan, [target], revealed)
        if beat.id == getattr(self, "_ray_shade_beat_id", None):
            target = TargetRef(visual_ref=ref, part="ray", index=0)
            return self._reveal_unrevealed(plan, [target], revealed)
        return []

    def _unit_rate_actions(self, plan, current_roles):
        """Focus box[0] -- the "per one" column that carries the rate.

        Box[0] alone rather than every box: the rate is what one source unit
        buys in target units, so the column that reads "1 source = per_unit
        target" is where the beat lands. A whole-tape focus would make every
        column equally salient and lose that reading.
        """
        target = TargetRef(visual_ref=plan.primary_visual.ref, part="box", index=0)
        return self._role_change(target, "focus", current_roles)

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

    @staticmethod
    def _unit_substitution_beat_id(plan):
        """The beat where the target unit's labels arrive.

        `_boundary_trace_beat_id` takes the first beat of any of organize/derive/
        focus; a substitution belongs on the beat that derives, so `derive` is
        preferred here. `require_unit_substitution_shape` forbids the plan from
        staging this itself, so there is no author's version to defer to.

        `unit_rate` shares the same staged reveal so the per-one pairing is
        legible when the rate beat lands. That reveal focuses `box[0]` as the
        per-one column, so the primary tape must already be on screen by the
        end of the chosen beat -- otherwise the focus lands on an invisible
        mobject and the target labels arrive before the tape they belong to.
        A beat qualifies once a prior beat -- or the current beat via its
        `beat.targets` -- names the primary visual with `part is None`, since
        only a whole-visual reveal populates the renderer's root group that
        carries `box[0]`. A same-beat custom `reveal` does *not* qualify the
        beat itself: the compiler schedules the substitution's box focus and
        target-label reveal before the beat's custom actions run, so the focus
        would land on an invisible mobject. Custom reveals only qualify
        subsequent beats.
        """
        if plan.strategy not in {"unit_substitution", "unit_rate"}:
            return None
        primary_ref = plan.primary_visual.ref
        tape_revealed = False
        eligible = set()
        for beat in plan.beats:
            if not tape_revealed and any(
                target.visual_ref == primary_ref and target.part is None
                for target in beat.targets
            ):
                tape_revealed = True
            if tape_revealed and beat.kind in {"derive", "organize", "focus"}:
                eligible.add(beat.id)
            if not tape_revealed:
                for action in beat.custom_actions:
                    if getattr(action, "kind", None) != "reveal":
                        continue
                    if any(
                        getattr(t, "visual_ref", None) == primary_ref
                        and getattr(t, "part", None) is None
                        for t in getattr(action, "targets", ())
                    ):
                        tape_revealed = True
                        break
        for kinds in ({"derive"}, {"organize"}, {"focus"}):
            for beat in plan.beats:
                if beat.kind in kinds and beat.id in eligible:
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
        self._clear_descendant_roles(key, current_roles)
        return [SetRoleAction(target=target, role=role)]

    def _clear_descendant_roles(self, key, current_roles):
        """A whole-visual `set_role` restyles descendants in the renderer
        (`build_role_transition` recolours the whole group). If an earlier
        explicit descendant role stays in `current_roles`, `_current_role`
        keeps returning it and a follow-up `_role_change` back to that role
        is silently dropped as a no-op -- but the frame just switched to the
        parent's role, so the descendant needs the transition too.

        Deferred parts (see `visual_registry.DEFERRED_PARTS`) are excluded
        from the visual's root group -- `_build_unit_tape` registers them as
        children but does not `.add()` them -- so a whole-visual role change
        does *not* restyle them. Clearing their bookkeeping here would falsely
        forget a role they still hold, and a later valid role change on that
        part would be suppressed as a no-op. Preserve those keys.
        """
        visual_ref, part, index = key
        if part is not None or index is not None:
            return
        deferred = self._deferred_parts.get(visual_ref, ())
        for descendant_key in [k for k in current_roles if k[0] == visual_ref and k != key]:
            if descendant_key[1] in deferred:
                continue
            del current_roles[descendant_key]

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
        key = self._target_key(target)
        current_roles[key] = role
        self._clear_descendant_roles(key, current_roles)
        return SetRoleAction(target=target, role=role)


def expand_beats(plan, answer_expression):
    return BeatExpander(answer_expression=answer_expression).expand(plan)


def regroup_beat_id(plan):
    """The single beat regroup stages its row cycle on, or None.

    The first organize beat that names the primary visual owns the walk;
    later organize beats fall through. Same discipline as
    `magnitude_sweep_beat_id`: pinning to one beat prevents a plan with two
    organize beats from double-staging the walk, and filtering by
    `beat.targets` keeps an organize beat that names only a supporting
    visual from restyling the primary.
    """
    if plan.strategy != "regroup":
        return None
    primary_ref = plan.primary_visual.ref
    for beat in plan.beats:
        if beat.kind != "organize":
            continue
        if any(target.visual_ref == primary_ref for target in beat.targets):
            return beat.id
    return None


def inverse_operation_beat_ids(plan):
    """Return `(partition_beat_id, divide_beat_id)` for an inverse_operation plan.

    The first derive/focus beat naming the primary owns the partition (peel
    off the constant, focus x); the second owns the per-x_part divide walk.
    Either may be `None` when the plan has fewer than that many
    focus/derive beats naming the primary. Non-inverse_operation plans
    return `(None, None)` so the expander branches short-circuit.
    """
    if plan.strategy != "inverse_operation":
        return None, None
    primary_ref = plan.primary_visual.ref
    matches = [
        beat.id for beat in plan.beats
        if beat.kind in {"focus", "derive"}
        and any(target.visual_ref == primary_ref for target in beat.targets)
    ]
    partition = matches[0] if matches else None
    divide = matches[1] if len(matches) >= 2 else None
    return partition, divide


def ray_shade_beat_ids(plan):
    """Return `(boundary_reveal_beat_id, ray_reveal_beat_id)` for ray_shade.

    Same selection rule as `inverse_operation_beat_ids`: the first two
    focus/derive beats naming the primary. The first reveals the boundary
    circle, the second reveals the shaded ray. `(None, None)` for other
    strategies.
    """
    if plan.strategy != "ray_shade":
        return None, None
    primary_ref = plan.primary_visual.ref
    matches = [
        beat.id for beat in plan.beats
        if beat.kind in {"focus", "derive"}
        and any(target.visual_ref == primary_ref for target in beat.targets)
    ]
    boundary = matches[0] if matches else None
    ray = matches[1] if len(matches) >= 2 else None
    return boundary, ray


def magnitude_sweep_beat_id(plan):
    """The single beat magnitude_comparison stages its sweep on, or None.

    The first focus/derive beat that names the primary visual owns the sweep;
    later focus/derive beats behave normally. Selecting one specific beat
    matters twice over:

    - The expander otherwise emits the sweep on EVERY focus/derive beat, so
      two derive beats double-stage the same segment-by-segment recolour.
    - `_slot_count` sizes the beat by the sweep's own action count; a beat
      that instead targets a supporting caption but happens to be a focus
      beat would inherit that sizing, and the caption's actions would land in
      the wrong slots.

    Picking by `beat.targets` filters those cases explicitly rather than
    relying on the plan author to write the beats in the right order.
    """
    if plan.strategy != "magnitude_comparison":
        return None
    primary_ref = plan.primary_visual.ref
    for beat in plan.beats:
        if beat.kind not in {"focus", "derive"}:
            continue
        if any(target.visual_ref == primary_ref for target in beat.targets):
            return beat.id
    return None


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


def _magnitude_indices(spec):
    """The walk order the magnitude sweep applies to `spec`'s parts.

    - `bar`: indices `0..value-1`. Walking `0..maximum-1` would teach the bar's
      capacity, not its actual magnitude. `value` is required to be a
      whole-number literal by `validate_strategy_compatibility`; a fractional or
      dynamic value cannot address specific segments at compile time.
    - `number_line`: marker indices sorted by resolved literal position. A plan
      may declare markers in any order, but a left-to-right sweep only reads
      correctly against the number line's own left-to-right axis.

    Returns an empty tuple when the walk is unbuildable (validation should have
    refused these earlier; the empty fallback avoids raising during expansion).
    """
    if spec.kind == "bar":
        value = _literal_int(spec.value)
        if value is None or value < 0:
            return ()
        return tuple(range(value))
    if spec.kind == "number_line":
        markers = list(enumerate(spec.markers))
        keyed = []
        for original_index, marker in markers:
            position = _literal_number(marker)
            if position is None:
                return ()
            keyed.append((position, original_index))
        keyed.sort()
        return tuple(original_index for _position, original_index in keyed)
    return ()


def _literal_number(expression):
    """A literal expression's value as a float, or None if not a literal.

    Bar/grid dimensions need whole numbers (see `_literal_int`), but a
    number-line marker's position is any numeric literal -- 2.5 sits between
    2 and 3 on the line and must sort accordingly.
    """
    if getattr(expression, "node", None) != "literal":
        return None
    return float(expression.value)
