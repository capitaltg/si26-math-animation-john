from unittest.mock import patch


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

    # Repro 1: model truncates 2.4 x 1.3 to a 2x2 grid.
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

    # Repro 2: fraction-equivalence proof, model invents start=1, subtract 1.
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
