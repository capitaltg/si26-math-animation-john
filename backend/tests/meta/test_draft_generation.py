import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.meta.draft_generation import DraftProposal, ProposedFixture, propose_template_draft
from app.meta.fingerprint import Fingerprint
from app.meta.models import FallbackObservation


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1, operation_family="compose", representation_family="bar",
        number_domain="fraction", operand_arity=2, step_count=1, grade_band="3-5",
    )


def _observation(obs_id="obs-1"):
    return FallbackObservation(
        id=obs_id, candidate_id="cand-1", source_excerpt="3/4 of the bar is shaded",
        grade_level=4, observation_kind="unsupported_shape", excluded=False,
        created_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )


def _raw_proposal(observation_id="obs-1"):
    return {
        "params_document": {
            "params_version": 1,
            "fields": [
                {"type": "integer", "name": "numerator", "label": "Numerator",
                 "description": "", "minimum": 1, "maximum": 20},
                {"type": "integer", "name": "denominator", "label": "Denominator",
                 "description": "", "minimum": 1, "maximum": 20},
            ],
        },
        "guard_document": {
            "guard_version": 1,
            "predicates": [
                {"predicate": "positive", "value": {"node": "field_ref", "field": "denominator"}},
            ],
        },
        "answer_expression": {
            "node": "fraction",
            "operands": [
                {"node": "field_ref", "field": "numerator"},
                {"node": "field_ref", "field": "denominator"},
            ],
        },
        "teaching_plan_document": {
            "plan_version": 3,
            "learning_objective": "Find a rectangle perimeter from its dimensions.",
            "primary_visual": {
                "kind": "rectangle_measurement",
                "ref": "rectangle",
                "length": {"node": "field_ref", "field": "length"},
                "width": {"node": "field_ref", "field": "width"},
                "unit": "cm",
            },
            "supporting_visuals": [],
            "strategy": "boundary_trace",
            "beats": [
                {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "rectangle"}],
                 "intent": "show the measured rectangle", "custom_actions": []},
                {"id": "trace", "kind": "focus", "targets": [{"visual_ref": "rectangle"}],
                 "intent": "trace all four edges", "custom_actions": []},
                {"id": "derive", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
                 "intent": "map opposite edges to twice length plus width", "custom_actions": []},
                {"id": "answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
                 "intent": "state the evaluated perimeter", "custom_actions": []},
            ],
            "variation_seed": "perimeter-demo",
        },
        "classifier_bullet": "Use for shading a fraction of one bar.",
        "fixtures": [
            {
                "kind": "positive", "expected_outcome": "accept",
                "observation_id": observation_id,
                "params": {"numerator": 3, "denominator": 4},
            },
        ],
    }


@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_validates_bedrock_response(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal())
    proposal = propose_template_draft(_fingerprint(), [_observation()])
    assert isinstance(proposal, DraftProposal)
    assert proposal.params_document.fields[0].name == "numerator"
    assert proposal.fixtures[0].observation_id == "obs-1"
    mock_call.assert_called_once()
    _, kwargs = mock_call.call_args
    assert kwargs["tools"][0]["name"] == "propose_template_draft"


@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_rejects_non_v3_teaching_plan(mock_call):
    proposal = _raw_proposal()
    proposal["teaching_plan_document"]["plan_version"] = 2
    mock_call.return_value = ("propose_template_draft", proposal)
    with pytest.raises(ValidationError):
        propose_template_draft(_fingerprint(), [_observation()])


@patch("app.meta.draft_generation.call_with_tool")
def test_generation_prompt_requires_semantic_teaching_plan(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal())

    propose_template_draft(_fingerprint(), [_observation()])

    _, kwargs = mock_call.call_args
    prompt = kwargs["system_prompt"].lower()
    assert "three to five teaching beats" in prompt
    assert "prefer semantic strategy over custom actions" in prompt
    assert "only inside their owning beat" in prompt
    assert "answer-related visuals start neutral" in prompt
    assert "introduced only during conclude" in prompt
    assert "simple collections reveal together" in prompt
    assert "perimeter explanations use boundary_trace" in prompt
    assert "median ordered values use item-specific targets" in prompt
    assert "positions, durations beyond requested bounded actions, colors, code, renderer objects, or manim concepts" in prompt
    assert "urls" in prompt
    assert "raw controls" in prompt


@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_rejects_malformed_response(mock_call):
    bad = _raw_proposal()
    bad["fixtures"][0]["kind"] = "not_a_real_kind"
    mock_call.return_value = ("propose_template_draft", bad)
    with pytest.raises(ValidationError):
        propose_template_draft(_fingerprint(), [_observation()])


@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_leaves_json_like_classifier_bullet_as_string(mock_call):
    good = _raw_proposal()
    good["classifier_bullet"] = '["shade","3/4"]'
    mock_call.return_value = ("propose_template_draft", good)

    proposal = propose_template_draft(_fingerprint(), [_observation()])

    assert proposal.classifier_bullet == '["shade","3/4"]'


@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_rejects_fixture_for_unknown_observation(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal("unknown-observation"))

    with pytest.raises(ValueError, match="unknown observation_id"):
        propose_template_draft(_fingerprint(), [_observation()])


@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_coerces_stringified_nested_field(mock_call):
    bad = _raw_proposal()
    bad["teaching_plan_document"] = json.dumps(bad["teaching_plan_document"])
    mock_call.return_value = ("propose_template_draft", bad)

    proposal = propose_template_draft(_fingerprint(), [_observation()])

    assert proposal.teaching_plan_document.strategy == "boundary_trace"


@patch("app.meta.draft_generation.call_with_tool")
def test_refinement_call_includes_prior_teaching_plan_and_structured_quality_feedback(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal())
    prior = DraftProposal.model_validate(_raw_proposal())
    propose_template_draft(
        _fingerprint(), [_observation()],
        prior_proposal=prior,
        reviewer_feedback={
            "code": "serial_simple_reveal",
            "path": "timeline",
            "hint": "reveal values together",
            "traceback": "Traceback (most recent call last): secret internals",
        },
    )
    _, kwargs = mock_call.call_args
    assert '"code":"serial_simple_reveal"' in kwargs["user_message"]
    assert '"path":"timeline"' in kwargs["user_message"]
    assert '"hint":"reveal values together"' in kwargs["user_message"]
    assert "prior proposal" in kwargs["user_message"]
    assert '"teaching_plan_document"' in kwargs["user_message"]
    assert "Traceback" not in kwargs["user_message"]
    assert '"traceback"' not in kwargs["user_message"]
    assert "secret internals" not in kwargs["user_message"]


@patch("app.meta.draft_generation.call_with_tool")
def test_refinement_includes_feedback_when_prior_proposal_never_parsed(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal())

    propose_template_draft(
        _fingerprint(), [_observation()],
        reviewer_feedback={
            "code": "draft_schema_invalid",
            "path": "teaching_plan_document.beats.3.intent",
            "hint": "keep every field inside the tool schema",
        },
    )

    _, kwargs = mock_call.call_args
    assert '"code":"draft_schema_invalid"' in kwargs["user_message"]
    assert '"path":"teaching_plan_document.beats.3.intent"' in kwargs["user_message"]
    assert "prior proposal" not in kwargs["user_message"]


@patch("app.meta.draft_generation.call_with_tool")
def test_refinement_rejects_incomplete_structured_quality_feedback(mock_call):
    prior = DraftProposal.model_validate(_raw_proposal())

    with pytest.raises(ValueError, match="code, path, and hint"):
        propose_template_draft(
            _fingerprint(),
            [_observation()],
            prior_proposal=prior,
            reviewer_feedback={"code": "serial_simple_reveal", "path": "timeline"},
        )

    mock_call.assert_not_called()


def test_the_prompt_hands_answer_presentation_to_the_system():
    from app.meta.draft_generation import _DRAFT_SYSTEM_PROMPT

    assert "answer_unit" in _DRAFT_SYSTEM_PROMPT
    assert 'never put "?" in a label' in _DRAFT_SYSTEM_PROMPT
    # The old instruction is false now: the unresolved answer appears from the
    # first beat, and only its VALUE waits for conclude.
    assert "introduced only during\nconclude" not in _DRAFT_SYSTEM_PROMPT
    assert "the final evaluated answer is introduced only during" not in _DRAFT_SYSTEM_PROMPT
