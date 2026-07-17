from unittest.mock import patch


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_validates_against_the_template_schema(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = {
        "start": 4,
        "steps": [{"operation": "add", "amount": 3}],
    }

    params = extract_params("Sarah has 4 apples and buys 3 more.", NumberLineParams)

    assert isinstance(params, NumberLineParams)
    assert params.start == 4
    assert params.steps[0].amount == 3
