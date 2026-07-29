from unittest.mock import patch

import pytest
from pydantic import ValidationError


@patch("app.pipeline.classification.call_with_tool")
def test_classify_preserves_ranked_options_and_appends_text_card(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "balance_scale", "rationale": "shows the equation as a balance"},
                {"template": "number_line", "rationale": "shows one forward jump"},
            ],
            "grade_level": 1,
            "ambiguous": False,
        },
    )

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

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "text_card", "rationale": "shows the original wording"},
                {"template": "number_line", "rationale": "shows one forward jump"},
            ],
            "grade_level": 1,
            "ambiguous": False,
        },
    )

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

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "number_line", "rationale": "best-ranked rationale"},
                {"template": "balance_scale", "rationale": "shows the equation"},
                {"template": "number_line", "rationale": "duplicate rationale"},
            ],
            "grade_level": 1,
            "ambiguous": False,
        },
    )

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

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [],
            "grade_level": 3,
            "ambiguous": True,
        },
    )

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

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [{"template": "hologram", "rationale": "looks impressive"}],
            "grade_level": 2,
            "ambiguous": False,
        },
    )

    # With widened template field, validation of membership happens downstream
    # in static_ref() which raises ValueError for unknown template names.
    # pydantic.ValidationError is a ValueError subclass, so a bare pytest.raises(ValueError)
    # would pass even if validation still happened at Pydantic construction time.
    # We assert NOT ValidationError to prove validation moved downstream.
    with pytest.raises(ValueError) as exc_info:
        classify_candidate("anything")
    assert not isinstance(exc_info.value, ValidationError)


@patch("app.pipeline.classification.call_with_tool")
def test_classification_prompt_requests_every_compatible_template_ranked(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "balance_scale", "rationale": "shows the equation"},
                {"template": "number_line", "rationale": "shows one jump"},
            ],
            "grade_level": 1,
            "ambiguous": False,
        },
    )

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


def test_array_grid_contract_requires_each_chain_state_to_fit_a_grid():
    from app.pipeline.classification import _TEMPLATE_CONTRACTS

    assert "source-stated starting total" in _TEMPLATE_CONTRACTS
    assert "renderable grid" in _TEMPLATE_CONTRACTS


@patch("app.pipeline.classification.call_with_tool")
def test_classification_prompt_excludes_static_plots_from_number_line(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = (
        "classify_problem",
        {"options": [], "grade_level": 3, "ambiguous": True},
    )

    classify_candidate("Plot 1/4 and 2/4 on the number line.")

    system_prompt = mock_call.call_args.kwargs["system_prompt"].lower()
    # number_line must require an operation, not accept static plotting tasks
    assert "requires an actual" in system_prompt
    assert "plotting" in system_prompt
    assert "no operation is performed" in system_prompt


def test_problem_kind_defaults_to_solvable():
    from app.pipeline.classification import ClassificationResult

    result = ClassificationResult(grade_level=3)
    assert result.problem_kind == "solvable"


@patch("app.pipeline.classification.call_with_tool")
def test_classify_stamps_the_static_version_id_on_every_option(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate
    from app.templates.registry import static_ref

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "number_line", "rationale": "shows one jump"},
            ],
            "grade_level": 1,
            "ambiguous": False,
        },
    )

    result = classify_candidate("6 + 3 = ?")

    number_line_option = next(o for o in result.options if o.template == TemplateName.NUMBER_LINE)
    assert number_line_option.version_id == static_ref(TemplateName.NUMBER_LINE).version_id
    text_card_option = next(o for o in result.options if o.template == TemplateName.TEXT_CARD)
    assert text_card_option.version_id == static_ref(TemplateName.TEXT_CARD).version_id


def test_template_option_version_id_defaults_to_empty_string():
    from app.models.scene import TemplateName
    from app.pipeline.classification import TemplateOption

    option = TemplateOption(template=TemplateName.NUMBER_LINE, rationale="x")
    assert option.version_id == ""


def test_template_option_accepts_a_dynamic_template_name():
    from app.pipeline.classification import TemplateOption

    option = TemplateOption(template="decimal_comparison_grid", rationale="x")
    assert option.template == "decimal_comparison_grid"


@patch("app.pipeline.classification.call_with_tool")
def test_classify_includes_dynamic_options_when_flag_enabled_and_session_given(mock_call, monkeypatch):
    from app.config import get_settings
    from app.meta.dynamic_templates import DynamicSnapshotEntry, EnabledSnapshot
    from app.pipeline.classification import classify_candidate

    monkeypatch.setattr(get_settings(), "meta_dynamic_classifier_enabled", True)
    snapshot = EnabledSnapshot(
        _entries={
            "decimal_comparison_grid": DynamicSnapshotEntry(
                version_id="v1", artifact_hash="sha256:x",
                classifier_bullet="- decimal_comparison_grid: compares two decimals on a grid.",
            )
        }
    )
    monkeypatch.setattr(
        "app.pipeline.classification.load_enabled_snapshot", lambda session: snapshot
    )
    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "decimal_comparison_grid", "rationale": "compares two decimals"},
            ],
            "grade_level": 4,
            "ambiguous": False,
        },
    )

    result = classify_candidate("Compare 0.4 and 0.35", session=object())

    dynamic_option = next(o for o in result.options if o.template == "decimal_comparison_grid")
    assert dynamic_option.version_id == "v1"
    # The tool schema call included the dynamic bullet and a closed enum containing it.
    called_kwargs = mock_call.call_args.kwargs
    assert "decimal_comparison_grid" in called_kwargs["system_prompt"]
    schema = called_kwargs["tools"][0]["schema"]
    template_enum = schema["$defs"]["TemplateOption"]["properties"]["template"]["enum"]
    assert "decimal_comparison_grid" in template_enum
    assert "number_line" in template_enum


@patch("app.pipeline.classification.call_with_tool")
def test_classify_drops_an_option_outside_the_snapshot(mock_call, monkeypatch):
    from app.config import get_settings
    from app.meta.dynamic_templates import EnabledSnapshot
    from app.pipeline.classification import classify_candidate

    monkeypatch.setattr(get_settings(), "meta_dynamic_classifier_enabled", True)
    monkeypatch.setattr(
        "app.pipeline.classification.load_enabled_snapshot",
        lambda session: EnabledSnapshot(_entries={}),
    )
    mock_call.return_value = (
        "classify_problem",
        {
            "options": [
                {"template": "hallucinated_template", "rationale": "made this up"},
                {"template": "number_line", "rationale": "shows one forward jump"},
            ],
            "grade_level": 1,
            "ambiguous": False,
        },
    )

    result = classify_candidate("6 + 3 = ?", session=object())

    names = [o.template for o in result.options]
    assert "hallucinated_template" not in names
    assert "number_line" in names


@patch("app.pipeline.classification.call_with_tool")
def test_classify_without_a_session_ignores_dynamic_templates_even_if_flag_enabled(mock_call, monkeypatch):
    from app.config import get_settings
    from app.pipeline.classification import classify_candidate

    monkeypatch.setattr(get_settings(), "meta_dynamic_classifier_enabled", True)
    mock_call.return_value = (
        "classify_problem",
        {"options": [], "grade_level": 1, "ambiguous": False},
    )

    classify_candidate("6 + 3 = ?")  # no session passed

    called_kwargs = mock_call.call_args.kwargs
    schema = called_kwargs["tools"][0]["schema"]
    # No session was passed, so the snapshot was never loaded and the schema
    # is left completely unpatched -- byte-identical to today's schema, which
    # has no "enum" constraint on the (already-widened-to-str) template field.
    template_property = schema["$defs"]["TemplateOption"]["properties"]["template"]
    assert "enum" not in template_property
