# backend/tests/test_config.py
from app.config import get_settings


def test_settings_load_defaults():
    settings = get_settings()
    assert settings.aws_region == "us-east-1"
    assert "claude" in settings.bedrock_model_id.lower()
