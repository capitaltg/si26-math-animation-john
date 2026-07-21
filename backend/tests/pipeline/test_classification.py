from unittest.mock import patch

import pytest
from pydantic import ValidationError


@patch("app.pipeline.classification.call_with_tool")
def test_classify_preserves_ranked_options_and_appends_text_card(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "balance_scale", "rationale": "shows the equation as a balance"},
            {"template": "number_line", "rationale": "shows one forward jump"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    result = classify_candidate("6 + 3 = ?")

    assert [option.template for option in result.options] == [
        TemplateName.BALANCE_SCALE,
        TemplateName.NUMBER_LINE,
        TemplateName.TEXT_CARD,
    ]
    assert result.options[1].rationale == "shows one forward jump"
    assert result.options[-1].rationale == "always-compatible fallback"
    assert result.grade_level == 1
    assert result.ambiguous is False


@patch("app.pipeline.classification.call_with_tool")
def test_classify_does_not_duplicate_an_existing_text_card(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "text_card", "rationale": "shows the original wording"},
            {"template": "number_line", "rationale": "shows one forward jump"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    result = classify_candidate("6 + 3 = ?")

    assert [option.template for option in result.options] == [
        TemplateName.NUMBER_LINE,
        TemplateName.TEXT_CARD,
    ]
    assert result.options[-1].rationale == "shows the original wording"


@patch("app.pipeline.classification.call_with_tool")
def test_classify_stably_deduplicates_structural_templates(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "number_line", "rationale": "best-ranked rationale"},
            {"template": "balance_scale", "rationale": "shows the equation"},
            {"template": "number_line", "rationale": "duplicate rationale"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    result = classify_candidate("6 + 3 = ?")

    assert [option.template for option in result.options] == [
        TemplateName.NUMBER_LINE,
        TemplateName.BALANCE_SCALE,
        TemplateName.TEXT_CARD,
    ]
    assert result.options[0].rationale == "best-ranked rationale"


@patch("app.pipeline.classification.call_with_tool")
def test_ambiguous_result_exposes_only_text_card_fallback(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [],
        "grade_level": 3,
        "ambiguous": True,
    }

    result = classify_candidate("There are some red and some green apples.")

    assert result.ambiguous is True
    assert [option.template for option in result.options] == [TemplateName.TEXT_CARD]


def test_model_accepts_ambiguous_empty_structural_options_payload():
    from app.pipeline.classification import ClassificationResult

    result = ClassificationResult(options=[], grade_level=3, ambiguous=True)

    assert result.options == []
    assert result.ambiguous is True


@patch("app.pipeline.classification.call_with_tool")
def test_classify_rejects_an_unknown_template(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [{"template": "hologram", "rationale": "looks impressive"}],
        "grade_level": 2,
        "ambiguous": False,
    }

    with pytest.raises(ValidationError):
        classify_candidate("anything")


@patch("app.pipeline.classification.call_with_tool")
def test_classification_prompt_requests_every_compatible_template_ranked(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "balance_scale", "rationale": "shows the equation"},
            {"template": "number_line", "rationale": "shows one jump"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    classify_candidate("6 + 3 = ?")

    system_prompt = mock_call.call_args.kwargs["system_prompt"]
    for template in (
        "number_line",
        "array_grid",
        "balance_scale",
        "fraction_bar",
        "fraction_of_whole",
        "text_card",
    ):
        assert template in system_prompt
    assert "every template" in system_prompt.lower()
    assert "ranked best-first" in system_prompt.lower()
    assert "one-phrase rationale" in system_prompt.lower()
    assert "1 to 3" in system_prompt
    assert "single operation" in system_prompt.lower()
