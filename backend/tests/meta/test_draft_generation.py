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
        "animation_document": {
            "animation_version": 2,
            "root": {
                "kind": "expression_label",
                "expression": {
                    "node": "fraction",
                    "operands": [
                        {"node": "field_ref", "field": "numerator"},
                        {"node": "field_ref", "field": "denominator"},
                    ],
                },
                "prefix": "Answer: ",
                "role": "answer",
            },
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
def test_propose_template_draft_rejects_legacy_animation_version(mock_call):
    proposal = _raw_proposal()
    proposal["animation_document"]["animation_version"] = 1
    mock_call.return_value = ("propose_template_draft", proposal)
    with pytest.raises(ValueError, match="animation_version 2"):
        propose_template_draft(_fingerprint(), [_observation()])


@patch("app.meta.draft_generation.call_with_tool")
def test_generation_prompt_requires_shared_spatial_layout(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal())

    propose_template_draft(_fingerprint(), [_observation()])

    _, kwargs = mock_call.call_args
    prompt = kwargs["system_prompt"]
    assert "sequence controls time, not spatial position" in prompt
    assert "one shared row, column, overlay, align, or padding layout tree" in prompt
    assert "answer-role expression_label must have its own ref and appear" in prompt
    assert "Never appear a producing layout and one of its descendants" in prompt


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
    bad["answer_expression"] = json.dumps(bad["answer_expression"])
    mock_call.return_value = ("propose_template_draft", bad)

    proposal = propose_template_draft(_fingerprint(), [_observation()])

    assert proposal.answer_expression.node == "fraction"


@patch("app.meta.draft_generation.call_with_tool")
def test_refinement_call_includes_prior_proposal_and_feedback(mock_call):
    mock_call.return_value = ("propose_template_draft", _raw_proposal())
    prior = DraftProposal.model_validate(_raw_proposal())
    propose_template_draft(
        _fingerprint(), [_observation()],
        prior_proposal=prior, reviewer_feedback="the guard is too permissive",
    )
    _, kwargs = mock_call.call_args
    assert "the guard is too permissive" in kwargs["user_message"]
    assert "prior proposal" in kwargs["user_message"]
