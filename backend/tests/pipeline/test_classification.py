# backend/tests/pipeline/test_classification.py
from unittest.mock import patch

import pytest
from pydantic import ValidationError


@patch("app.pipeline.classification.call_with_tool")
def test_classify_returns_template_and_grade(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {"template": "number_line", "grade_level": 2, "ambiguous": False}

    result = classify_candidate("Sarah has 4 apples and buys 3 more.")

    assert result.template == TemplateName.NUMBER_LINE
    assert result.grade_level == 2
    assert result.ambiguous is False


@patch("app.pipeline.classification.call_with_tool")
def test_classify_can_report_ambiguous_with_no_template(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {"template": None, "grade_level": 3, "ambiguous": True}

    result = classify_candidate("There are some red and some green apples.")

    assert result.template is None
    assert result.ambiguous is True


@patch("app.pipeline.classification.call_with_tool")
def test_classify_rejects_an_unknown_template(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {"template": "hologram", "grade_level": 2, "ambiguous": False}

    with pytest.raises(ValidationError):
        classify_candidate("anything")
