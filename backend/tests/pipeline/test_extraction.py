from fractions import Fraction
from unittest.mock import patch

from app.pipeline.extraction import extract_stated_answer


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_raises_when_model_declines(mock_call):
    import pytest

    from app.pipeline.extraction import TemplateMismatchError, extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "decline_extraction",
        {"reason": "no add or subtract sequence in the problem"},
    )

    with pytest.raises(TemplateMismatchError) as exc_info:
        extract_params("A word problem with no operands.", NumberLineParams)

    assert "no add or subtract sequence" in str(exc_info.value)


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_validates_against_the_template_schema(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "report_params",
        {
            "start": 4,
            "steps": [
                {"operation": "add", "amount": 3},
                {"operation": "subtract", "amount": 2},
            ],
        },
    )

    params = extract_params(
        "Sarah has 4 apples, buys 3 more, then gives 2 away.", NumberLineParams
    )

    assert isinstance(params, NumberLineParams)
    assert params.start == 4
    assert params.steps[0].amount == 3


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_ignores_labels_after_question_and_preserves_operand_order(
    mock_call,
):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "report_params",
        {"start": 6, "steps": [{"operation": "add", "amount": 3}]},
    )

    params = extract_params(
        "What is composed of 6 and 3? 9 6 3",
        NumberLineParams,
    )

    assert params.start == 6
    assert params.steps[0].amount == 3
    assert mock_call.call_args.kwargs["user_message"] == (
        "What is composed of 6 and 3?"
    )
    system_prompt = mock_call.call_args.kwargs["system_prompt"]
    assert "Preserve operand order" in system_prompt
    assert "composed of A and B" in system_prompt
    assert "answer choices" in system_prompt


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_keeps_text_through_the_last_question_mark(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "report_params",
        {"start": 6, "steps": [{"operation": "add", "amount": 3}]},
    )

    extract_params(
        "Ready? What is composed of 6 and 3? 9 6 3",
        NumberLineParams,
    )

    assert mock_call.call_args.kwargs["user_message"] == (
        "Ready? What is composed of 6 and 3?"
    )


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_rejects_truncated_array_grid(mock_call):
    import pytest

    from app.pipeline.extraction import TemplateMismatchError, extract_params
    from app.templates.array_grid.params import ArrayGridParams

    mock_call.return_value = ("report_params", {"rows": 2, "cols": 2})

    with pytest.raises(TemplateMismatchError):
        extract_params("Multiply (2.4) · (1.3).", ArrayGridParams)


@patch("app.pipeline.extraction.call_with_tool")
def test_grounding_ignores_numbers_after_the_question_mark(mock_call):
    import pytest

    from app.pipeline.extraction import TemplateMismatchError, extract_params
    from app.templates.array_grid.params import ArrayGridParams

    # The model only sees "What is 2.4 times 1.3?"; the "2" lives in the answer
    # choices AFTER the "?", which the model never saw. A fabricated 2x2 grid must
    # NOT be grounded by that trailing "2".
    mock_call.return_value = ("report_params", {"rows": 2, "cols": 2})

    with pytest.raises(TemplateMismatchError):
        extract_params("What is 2.4 times 1.3? Options: 2, 3, 4.", ArrayGridParams)


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_rejects_invented_number_line_operation(mock_call):
    import pytest

    from app.pipeline.extraction import TemplateMismatchError, extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "report_params",
        {"start": 1, "steps": [{"operation": "subtract", "amount": 1}]},
    )

    with pytest.raises(TemplateMismatchError):
        extract_params("Show 1/2, 3/6, 4/8, 2/4 are equivalent.", NumberLineParams)


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_accepts_grounded_number_line(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "report_params",
        {"start": 4, "steps": [{"operation": "add", "amount": 3}, {"operation": "subtract", "amount": 2}]},
    )

    params = extract_params(
        "Sarah has 4 apples, buys 3 more, then gives 2 away.", NumberLineParams
    )

    assert params.start == 4


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_accepts_balance_scale_with_derived_total(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.balance_scale.params import BalanceScaleParams

    mock_call.return_value = ("report_params", {"left_terms": [3, 4], "right_total": 7})

    params = extract_params("3 + 4 = ?", BalanceScaleParams)

    assert params.right_total == 7


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_accepts_grounded_fraction_bar(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.fraction_bar.params import FractionBarParams

    # Two steps (min_length=2 per FractionBarParams.steps); running totals
    # 3 -> 4 -> 6 stay within the guard's [0, denominator * 4] = [0, 24] bound.
    mock_call.return_value = (
        "report_params",
        {
            "denominator": 6,
            "start_numerator": 3,
            "steps": [
                {"operation": "add", "numerator": 1},
                {"operation": "add", "numerator": 2},
            ],
        },
    )

    params = extract_params("3/6 + 1/6 + 2/6 = ?", FractionBarParams)

    assert params.denominator == 6


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_accepts_generic_grounded_array_grid_chain(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.array_grid.params import ArrayGridParams

    mock_call.return_value = (
        "report_params",
        {
            "start": 24,
            "steps": [
                {"operation": "divide", "factor": 3},
                {"operation": "multiply", "factor": 2},
            ],
        },
    )

    params = extract_params(
        "Start with 24 counters, divide by 3, then multiply by 2.",
        ArrayGridParams,
    )

    assert params.starting_total() == 24


@patch("app.pipeline.bedrock_client.get_bedrock_client")
@patch("app.pipeline.bedrock_client.get_settings")
def test_call_with_tool_offers_all_tools_and_returns_fired_name(mock_settings, mock_get_client):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.pipeline.bedrock_client import call_with_tool

    mock_settings.return_value = SimpleNamespace(bedrock_model_id="model-x")
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {"toolUse": {"name": "decline_extraction", "input": {"reason": "no fit"}}}
                ]
            }
        }
    }
    mock_get_client.return_value = client

    name, payload = call_with_tool(
        system_prompt="sys",
        user_message="msg",
        tools=[
            {"name": "report_params", "schema": {"type": "object"}},
            {"name": "decline_extraction", "schema": {"type": "object"}},
        ],
    )

    assert name == "decline_extraction"
    assert payload == {"reason": "no fit"}
    tool_config = client.converse.call_args.kwargs["toolConfig"]
    assert tool_config["toolChoice"] == {"any": {}}
    assert [t["toolSpec"]["name"] for t in tool_config["tools"]] == [
        "report_params",
        "decline_extraction",
    ]


@patch("app.pipeline.bedrock_client.boto3.client")
@patch("app.pipeline.bedrock_client.get_settings")
def test_bedrock_client_uses_credentials_loaded_from_settings(mock_settings, mock_client):
    from types import SimpleNamespace

    from app.pipeline.bedrock_client import get_bedrock_client

    mock_settings.return_value = SimpleNamespace(
        aws_region="us-east-1",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        aws_session_token=None,
    )
    get_bedrock_client.cache_clear()

    get_bedrock_client()

    mock_client.assert_called_once_with(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
    )
    get_bedrock_client.cache_clear()


def _dynamic_params_cls():
    from app.meta.dsl.expression import FieldRefNode
    from app.meta.dsl.guard import GuardDocument, PositivePredicate, compile_guard
    from app.meta.dsl.params import (
        DecimalFieldSpec, ParamsDocument, StringFieldSpec, compile_template_params,
    )

    document = ParamsDocument(
        params_version=1,
        fields=[
            DecimalFieldSpec(
                name="distance_km", label="Distance in kilometers",
                description="The length of the object in kilometers",
                minimum=0.1, maximum=9.99,
            ),
            StringFieldSpec(
                name="object_name", label="Object name",
                description="The name of the object being measured",
                max_length=60,
            ),
        ],
    )
    guard = compile_guard(
        GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="distance_km"))],
        ),
        known_fields=frozenset({"distance_km", "object_name"}),
    )
    return compile_template_params(document, guard)


@patch("app.pipeline.extraction.call_with_tool")
def test_dynamic_template_extraction_is_not_judged_by_static_schema_criteria(mock_call):
    """A dynamic schema must not be offered the static templates' decline criteria.

    The static prompt tells the model to decline when there is "no add or subtract
    sequence for a step-based schema" or "non-whole operands for a whole-number
    schema". A dynamic schema has neither notion, and a km-conversion template was
    declined on both grounds -- the model quoted them back as its reason -- for a
    problem whose values sat plainly in the text and inside the declared range.
    """
    from app.pipeline.extraction import extract_params

    mock_call.return_value = (
        "report_params",
        {"distance_km": 2.75, "object_name": "hiking trail"},
    )

    extract_params(
        "A hiking trail is 2.75 kilometers long. How many meters long is the trail?",
        _dynamic_params_cls(),
    )

    prompt = mock_call.call_args.kwargs["system_prompt"]
    assert "add or subtract sequence" not in prompt
    assert "whole-number schema" not in prompt
    assert "operand" not in prompt


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_rejects_duplicated_operand_not_in_source(mock_call):
    """LLM emitting a duplicated numeric that the source only has once
    must now raise TemplateMismatchError instead of silently passing."""
    import pytest

    from app.pipeline.extraction import TemplateMismatchError, extract_params
    from app.templates.balance_scale.params import BalanceScaleParams

    mock_call.return_value = ("report_params", {"left_terms": [3, 3], "right_total": 6})

    with pytest.raises(TemplateMismatchError, match="not grounded"):
        extract_params(
            "A box has 3 red balls and 5 blue balls. How many balls?",
            BalanceScaleParams,
        )


@patch("app.pipeline.extraction.call_with_tool")
def test_static_template_extraction_keeps_its_tuned_prompt(mock_call):
    """The six static templates keep the prompt their extraction was tuned against."""
    from app.pipeline.extraction import _EXTRACTION_SYSTEM_PROMPT, extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = (
        "report_params",
        {"start": 4, "steps": [{"operation": "add", "amount": 3}]},
    )

    extract_params("Sarah has 4 apples and buys 3 more.", NumberLineParams)

    assert mock_call.call_args.kwargs["system_prompt"] == _EXTRACTION_SYSTEM_PROMPT


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_stated_answer_integer(mock_call):
    mock_call.return_value = ("report_stated_answer", {"value": "9", "source_span": "= 9"})
    result = extract_stated_answer("What is 3 + 5? Answer: = 9")
    assert result == (Fraction(9), "= 9")


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_stated_answer_fraction(mock_call):
    mock_call.return_value = (
        "report_stated_answer",
        {"value": "3/4", "source_span": "3/4"},
    )
    result = extract_stated_answer("1/4 + 2/4 = 3/4")
    assert result == (Fraction(3, 4), "3/4")


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_stated_answer_decline(mock_call):
    mock_call.return_value = ("decline_stated_answer", {"reason": "no answer"})
    assert extract_stated_answer("What is 3 + 5?") is None


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_stated_answer_span_not_in_source(mock_call):
    mock_call.return_value = (
        "report_stated_answer",
        {"value": "9", "source_span": "= 9"},
    )
    assert extract_stated_answer("What is 3 + 5?") is None


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_stated_answer_bedrock_raises(mock_call):
    mock_call.side_effect = RuntimeError("bedrock down")
    assert extract_stated_answer("1/4 + 2/4 = 3/4") is None


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_stated_answer_invalid_fraction(mock_call):
    mock_call.return_value = (
        "report_stated_answer",
        {"value": "not-a-number", "source_span": "not-a-number"},
    )
    assert extract_stated_answer("blah not-a-number blah") is None
