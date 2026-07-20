from unittest.mock import patch


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_validates_against_the_template_schema(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = {
        "start": 4,
        "steps": [
            {"operation": "add", "amount": 3},
            {"operation": "subtract", "amount": 2},
        ],
    }

    params = extract_params(
        "Sarah has 4 apples, buys 3 more, then gives 2 away.", NumberLineParams
    )

    assert isinstance(params, NumberLineParams)
    assert params.start == 4
    assert params.steps[0].amount == 3


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
