"""Held-out rotation problem variants for the RC eval.

Each entry is a DemoLesson shaped like ROTATION_LESSON but carrying a
different source excerpt, a different iteration count in both the
params/answer and the rotation_iterations literal on the teaching plan,
and a unique template_name so the approved versions do not collide when
the eval runs several in the same session.

Held-out means: not seen by the RC during development. The excerpts
below are paraphrases the demo lesson does NOT use, exercising the
"same-shape different-phrasing" contract of the rotation strategy. They
are intentionally short so a follow-up ticket can add more without
having to re-derive teaching-plan structure.

If you add or change a lesson here, run
    .venv/bin/pytest backend/tests/eval -q
locally and inspect the artifacts under ``var/meta_artifacts/`` before
freezing an RC.
"""

from __future__ import annotations

from app.meta.fingerprint import Fingerprint

from tests.meta.test_demo_end_to_end import DemoLesson


def _rotation_lesson(
    *,
    template_name: str,
    source_excerpt: str,
    turns: int,
    second_turns: int,
    grade_band: str = "6-8",
) -> DemoLesson:
    """Build a rotation-shape DemoLesson with matching iteration wiring.

    `turns` doubles as: the verified positive fixture parameter, the
    verified answer, the ``rotation_iterations`` literal on the teaching
    plan, and the fingerprint's ``step_count`` (so the fingerprint stays
    a truthful shape descriptor rather than a copy of the demo). Every
    other field mirrors ROTATION_LESSON, since rotation shares one
    teaching_plan skeleton and one guard document across variants.
    """
    return DemoLesson(
        template_name=template_name,
        source_excerpt=source_excerpt,
        fingerprint=Fingerprint(
            fingerprint_version=1,
            operation_family="transform",
            representation_family="coordinate",
            number_domain="whole",
            operand_arity=1,
            step_count=turns,
            grade_band=grade_band,
        ),
        params_document={
            "params_version": 1,
            "fields": [
                {
                    "type": "integer", "name": "turns", "label": "Number of turns",
                    "description": "How many times the triangle is rotated",
                    "minimum": 1, "maximum": 4,
                },
            ],
        },
        guard_document={
            "guard_version": 1,
            "predicates": [
                {"predicate": "positive", "value": {"node": "field_ref", "field": "turns"}},
            ],
        },
        answer_expression={"node": "field_ref", "field": "turns"},
        teaching_plan={
            "plan_version": 3,
            "learning_objective": (
                f"Rotate a triangle 90 degrees about the origin {turns} time"
                f"{'s' if turns != 1 else ''}."
            ),
            "primary_visual": {
                "kind": "coordinate_plane", "ref": "plane",
                "x_min": {"node": "literal", "value": -5},
                "x_max": {"node": "literal", "value": 5},
                "y_min": {"node": "literal", "value": -5},
                "y_max": {"node": "literal", "value": 5},
                "polygons": [{
                    "ref": "tri",
                    "vertices": [
                        {"x": {"node": "literal", "value": 1}, "y": {"node": "literal", "value": 0}},
                        {"x": {"node": "literal", "value": 3}, "y": {"node": "literal", "value": 0}},
                        {"x": {"node": "literal", "value": 2}, "y": {"node": "literal", "value": 2}},
                    ],
                }],
                "pivot": {"x": {"node": "literal", "value": 0}, "y": {"node": "literal", "value": 0}},
                "rotation_angle_deg": 90,
                "rotation_iterations": turns,
            },
            "strategy": "rotation",
            "beats": [
                {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "plane"}],
                 "intent": "Show the triangle at its starting position."},
                {"id": "derive", "kind": "derive", "targets": [{"visual_ref": "plane"}],
                 "intent": (
                    f"Rotate the triangle 90 degrees about the origin, "
                    f"{turns} time{'s' if turns != 1 else ''}."
                 )},
                {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "plane"}],
                 "intent": "Land on the final rotated image."},
            ],
            "variation_seed": f"heldout-rotation-{turns}",
        },
        classifier_bullet="Rotate a polygon about a fixed point a whole number of times.",
        primary_visual_ref="plane",
        expected_beat_ids=["reveal", "derive", "conclude"],
        verified_params={"turns": turns},
        verified_answer=turns,
        # `positive` fails on 0, so a single negative witnesses the whole guard.
        negative_params=[{"turns": 0}],
        second_params={"turns": second_turns},
        second_answer=second_turns,
    )


# The excerpts are held out from the demo runbook -- they are NOT copied
# from any slide in eval/fixtures/*. When curating a real RC deck later,
# replace these with anonymized paraphrases pulled from real teacher
# decks (a JSON file loaded here would let curation happen outside code
# review, but the current three-entry inline list keeps the change small
# for the initial harness). If you add a variant, keep `template_name`
# unique -- approve_draft_service refuses two published versions to share
# a name in the same session's DB.
HELDOUT_ROTATION_LESSONS: list[DemoLesson] = [
    # Grounding requires the rotation_iterations literal to appear as a
    # token in the excerpt (e.g. "3 times" for iterations=3) -- word forms
    # like "once" or "twice" are not accepted by the phrase binder. The
    # pivot at (0, 0) and 90 degree angle can be phrased as "the origin"
    # or "90°" since those bind by literal or by named-anchor.
    _rotation_lesson(
        template_name="heldout_rotate_once",
        source_excerpt=(
            "A triangle rotates 90 degrees about the origin, 1 time. "
            "Where does the image land?"
        ),
        turns=1,
        second_turns=2,
    ),
    _rotation_lesson(
        template_name="heldout_rotate_twice",
        source_excerpt=(
            "Rotate the triangle 90° about the point (0, 0), 2 times. "
            "Where does it end up?"
        ),
        turns=2,
        second_turns=3,
    ),
    # `iterations * angle_deg` must not be a multiple of 360 (the polygon
    # would return to its start pose and the rotation strategy refuses to
    # generate a trivial animation). At 90 degrees that rules out 4 turns
    # -- three is the natural third variant that still yields a distinct
    # final pose.
    _rotation_lesson(
        template_name="heldout_rotate_three_times",
        source_excerpt=(
            "Turn the shape 90 degrees around (0, 0), 3 times. "
            "What is the final position?"
        ),
        turns=3,
        second_turns=1,
    ),
]
