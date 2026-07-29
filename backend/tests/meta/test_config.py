from app.config import Settings


def test_meta_approval_enabled_defaults_false():
    assert Settings().meta_approval_enabled is False


def test_meta_dynamic_classifier_enabled_defaults_to_false():
    from app.config import Settings

    assert Settings().meta_dynamic_classifier_enabled is False
