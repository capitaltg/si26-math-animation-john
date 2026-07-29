def test_dynamic_template_mismatch_reason_exists_and_is_distinct():
    from app.meta.observations import TextCardReason

    assert TextCardReason.DYNAMIC_TEMPLATE_MISMATCH != TextCardReason.UNSUPPORTED_SHAPE
