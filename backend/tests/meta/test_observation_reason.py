from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult, TemplateOption
from app.meta.observations import TextCardReason, classify_text_card_reason


def _classification(options=(), ambiguous=False, problem_kind="solvable"):
    return ClassificationResult(
        options=[TemplateOption(template=t, rationale="r") for t in options],
        grade_level=3,
        ambiguous=ambiguous,
        problem_kind=problem_kind,
    )


def test_solvable_no_structural_fit_is_unsupported_shape():
    c = _classification(options=[TemplateName.TEXT_CARD])
    reason = classify_text_card_reason(c, TemplateName.TEXT_CARD, "pending_review")
    assert reason is TextCardReason.UNSUPPORTED_SHAPE


def test_reviewer_overrode_a_structural_option_is_manual():
    c = _classification(options=[TemplateName.ARRAY_GRID, TemplateName.TEXT_CARD])
    reason = classify_text_card_reason(c, TemplateName.TEXT_CARD, "pending_review")
    assert reason is TextCardReason.MANUAL_SELECTION


def test_ambiguous_or_non_problem():
    c = _classification(options=[TemplateName.TEXT_CARD], ambiguous=True)
    assert (
        classify_text_card_reason(c, TemplateName.TEXT_CARD, "pending_review")
        is TextCardReason.AMBIGUOUS_OR_NON_PROBLEM
    )
    c2 = _classification(options=[TemplateName.TEXT_CARD], problem_kind="not_a_problem")
    assert (
        classify_text_card_reason(c2, TemplateName.TEXT_CARD, "pending_review")
        is TextCardReason.AMBIGUOUS_OR_NON_PROBLEM
    )


def test_fallback_status_is_technical_failure():
    c = _classification(options=[TemplateName.ARRAY_GRID, TemplateName.TEXT_CARD])
    assert (
        classify_text_card_reason(c, TemplateName.ARRAY_GRID, "fallback")
        is TextCardReason.TECHNICAL_FAILURE
    )


def test_non_text_card_pick_returns_none():
    c = _classification(options=[TemplateName.ARRAY_GRID, TemplateName.TEXT_CARD])
    assert classify_text_card_reason(c, TemplateName.ARRAY_GRID, "pending_review") is None
