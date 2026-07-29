from app.config import Settings


def test_meta_approval_enabled_defaults_false():
    assert Settings().meta_approval_enabled is False
