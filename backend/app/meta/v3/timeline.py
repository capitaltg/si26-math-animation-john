from app.meta.dsl.scene_program import TimedAction
from app.meta.dsl.v3_common import MAX_ACTION_SECONDS, MAX_SCENE_SECONDS, MIN_ACTION_SECONDS
from app.meta.v3.errors import V3Failure, V3ValidationError


def schedule_beats(expanded_beats):
    """Allocate beat time without letting minimum action lengths overrun a beat.

    Actions in a batch start together.  This preserves grouped semantic changes
    when a beat has too many actions to place sequentially at the minimum action
    duration.
    """
    minimum = sum(beat.minimum_seconds for beat in expanded_beats)
    conclusion_floor = 1.5
    if minimum > MAX_SCENE_SECONDS:
        raise V3ValidationError(V3Failure(
            code="timeline_over_budget",
            path="timeline",
            expected=f"minimum timeline at or below {MAX_SCENE_SECONDS:g} seconds",
            observed=f"{minimum:g} seconds",
            hint="simplify beats so the conclusion keeps its minimum hold",
        ))
    target = min(12.0, max(6.0, minimum + conclusion_floor))
    extra = target - minimum
    total_weight = sum(beat.weight for beat in expanded_beats)
    cursor = 0.0
    entries = []
    # The conclusion holds everything it does at one instant, so the final state
    # the lesson leaves on screen reads as one thing rather than being assembled
    # in pieces -- and so each of those actions can clear
    # `MIN_CONCLUSION_HOLD_SECONDS`, which `quality.check_conclusion_hold`
    # requires of every final-beat action individually.
    #
    # Keyed on the last beat that ACTS, which is exactly the notion
    # `check_conclusion_hold` reads off `program.timeline[-1].beat_id`: a beat
    # with no actions contributes no timeline entry, so neither site can ever see
    # it as the conclusion. This used to key on a beat containing a `reveal` of
    # `evaluated_answer`, so the co-start was a side effect of the answer card --
    # and a lesson whose answer is one of its own values, declaring no card, had
    # its conclusion split into sequential slots the hold floor then rejected.
    conclusion = next((beat for beat in reversed(expanded_beats) if beat.actions), None)

    for beat in expanded_beats:
        beat_seconds = beat.minimum_seconds + extra * beat.weight / total_weight
        actions = beat.actions
        if not actions:
            cursor += beat_seconds
            continue

        # A sequential slot must be at least the document minimum.  If there
        # are more actions than slots, split them into concurrent batches.
        slot_count = 1 if beat is conclusion else min(
            len(actions),
            beat.slot_count or max(1, int(beat_seconds / MIN_ACTION_SECONDS)),
        )
        slot_seconds = beat_seconds / slot_count
        duration_seconds = min(MAX_ACTION_SECONDS, max(MIN_ACTION_SECONDS, slot_seconds))
        for batch_index in range(slot_count):
            start = batch_index * len(actions) // slot_count
            end = (batch_index + 1) * len(actions) // slot_count
            at_seconds = round(cursor + batch_index * slot_seconds, 9)
            for action in actions[start:end]:
                entries.append(TimedAction(
                    at_seconds=at_seconds,
                    duration_seconds=round(duration_seconds, 9),
                    beat_id=beat.beat_id,
                    action=action,
                ))
        cursor += beat_seconds

    return entries, target
