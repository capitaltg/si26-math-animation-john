from app.meta.dsl.scene_program import TimedAction
from app.meta.dsl.v3_common import MAX_ACTION_SECONDS, MIN_ACTION_SECONDS


def schedule_beats(expanded_beats):
    """Allocate beat time without letting minimum action lengths overrun a beat.

    Actions in a batch start together.  This preserves grouped semantic changes
    when a beat has too many actions to place sequentially at the minimum action
    duration.
    """
    minimum = sum(beat.minimum_seconds for beat in expanded_beats)
    conclusion_floor = 1.5
    target = min(12.0, max(6.0, minimum + conclusion_floor))
    extra = target - minimum
    total_weight = sum(beat.weight for beat in expanded_beats)
    cursor = 0.0
    entries = []

    for beat in expanded_beats:
        beat_seconds = beat.minimum_seconds + extra * beat.weight / total_weight
        actions = beat.actions
        if not actions:
            cursor += beat_seconds
            continue

        # A sequential slot must be at least the document minimum.  If there
        # are more actions than slots, split them into concurrent batches.
        slot_count = 1 if _contains_answer_reveal(actions) else min(
            len(actions), max(1, int(beat_seconds / MIN_ACTION_SECONDS)),
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


def _contains_answer_reveal(actions):
    return any(
        action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in action.targets)
        for action in actions
    )
