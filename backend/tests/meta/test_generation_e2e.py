from datetime import datetime, timezone
from unittest.mock import patch

from app.meta.draft_generation import propose_template_draft
from app.meta.fingerprint import Fingerprint
from app.meta.models import FallbackObservation


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1,
        operation_family="compose",
        representation_family="bar",
        number_domain="fraction",
        operand_arity=2,
        step_count=1,
        grade_band="3-5",
    )


def _observation():
    return FallbackObservation(
        id="obs-1",
        candidate_id="cand-1",
        source_excerpt="Find the perimeter of a rectangle that is 6 cm by 4 cm.",
        grade_level=4,
        observation_kind="unsupported_shape",
        excluded=False,
        created_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )


def _proposal_response():
    field = lambda name: {"node": "field_ref", "field": name}
    return {
        "params_document": {
            "params_version": 1,
            "fields": [
                {"type": "integer", "name": "length", "label": "Length", "description": "", "minimum": 1, "maximum": 20},
                {"type": "integer", "name": "width", "label": "Width", "description": "", "minimum": 1, "maximum": 20},
            ],
        },
        "guard_document": {
            "guard_version": 1,
            "predicates": [{"predicate": "positive", "value": field("length")}],
        },
        "answer_expression": {
            "node": "add",
            "operands": [
                {"node": "multiply", "operands": [{"node": "literal", "value": 2}, field("length")]},
                {"node": "multiply", "operands": [{"node": "literal", "value": 2}, field("width")]},
            ],
        },
        "teaching_plan_document": {
            "plan_version": 3,
            "learning_objective": "Find a rectangle perimeter from its dimensions.",
            "primary_visual": {
                "kind": "rectangle_measurement", "ref": "rectangle",
                "length": field("length"), "width": field("width"), "unit": "cm",
            },
            "supporting_visuals": [],
            "strategy": "boundary_trace",
            "beats": [
                {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "rectangle"}], "intent": "show the measured rectangle", "custom_actions": []},
                {"id": "trace", "kind": "focus", "targets": [{"visual_ref": "rectangle"}], "intent": "trace all four edges", "custom_actions": []},
                {"id": "derive", "kind": "derive", "targets": [{"visual_ref": "rectangle"}], "intent": "map opposite edges to twice length plus width", "custom_actions": []},
                {"id": "answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}], "intent": "state the evaluated perimeter", "custom_actions": []},
            ],
            "variation_seed": "perimeter-demo",
        },
        "classifier_bullet": "Use for rectangle perimeter from measured dimensions.",
        "fixtures": [{"kind": "positive", "expected_outcome": "accept", "observation_id": "obs-1", "params": {"length": 6, "width": 4}}],
    }


@patch("app.meta.draft_generation.call_with_tool")
def test_generation_repair_returns_v3_teaching_intent_with_structured_quality_feedback(mock_call):
    mock_call.side_effect = [
        ("propose_template_draft", _proposal_response()),
        ("propose_template_draft", _proposal_response()),
    ]
    fingerprint = _fingerprint()
    observations = [_observation()]

    initial = propose_template_draft(fingerprint, observations)
    repaired = propose_template_draft(
        fingerprint,
        observations,
        prior_proposal=initial,
        reviewer_feedback={
            "code": "serial_simple_reveal",
            "path": "timeline",
            "hint": "reveal values together",
        },
    )

    assert repaired.teaching_plan_document.plan_version == 3
    second_message = mock_call.call_args_list[1].kwargs["user_message"]
    assert '"teaching_plan_document"' in second_message
    assert '"code":"serial_simple_reveal"' in second_message
    assert "Traceback" not in second_message
