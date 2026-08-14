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
    conclusion_floor = 3.0
    if minimum > MAX_SCENE_SECONDS:
        raise V3ValidationError(V3Failure(
            code="timeline_over_budget",
            path="timeline",
            expected=f"minimum timeline at or below {MAX_SCENE_SECONDS:g} seconds",
            observed=f"{minimum:g} seconds",
            hint="simplify beats so the conclusion keeps its minimum hold",
        ))
    target = min(24.0, max(12.0, minimum + conclusion_floor))
    extra = target - minimum
    total_weight = sum(beat.weight for beat in expanded_beats)
    cursor = 0.0
    entries = []
    # Co-start conclusion actions so the final state reads as one thing and each
    # action can clear `MIN_CONCLUSION_HOLD_SECONDS`, which `check_conclusion_hold`
    # requires of every final-beat action individually.
    #
    # Key on the last beat with actions, matching `check_conclusion_hold`'s use of
    # `program.timeline[-1].beat_id`; actionless beats never enter the timeline.
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
