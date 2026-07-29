def test_a_fallback_scene_is_technical_failure_regardless_of_which_template_was_picked():
    from app.meta.observations import TextCardReason, classify_text_card_reason
    from app.pipeline.classification import ClassificationResult, TemplateOption

    classification = ClassificationResult(
        options=[TemplateOption(template="decimal_comparison_grid", rationale="x", version_id="v1")],
        grade_level=3,
        ambiguous=False,
    )

    reason = classify_text_card_reason(
        classification,
        picked_template="decimal_comparison_grid",
        scene_status="fallback",
    )

    assert reason == TextCardReason.TECHNICAL_FAILURE
