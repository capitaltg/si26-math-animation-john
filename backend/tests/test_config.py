# backend/tests/test_config.py
from app.config import get_settings


def test_settings_load_defaults():
    settings = get_settings()
    assert settings.aws_region == "us-east-1"
    assert "claude" in settings.bedrock_model_id.lower()


def test_meta_settings_defaults():
    from app.config import Settings

    settings = Settings(_env_file=None)
    assert settings.meta_templates_enabled is False
    assert settings.meta_codegen_enabled is False
    assert settings.fingerprint_observation_threshold == 5
    assert settings.fingerprint_tagger_prompt_version == "v1"
    assert settings.fingerprint_tagger_max_attempts == 2
    assert settings.fingerprint_tagger_backoff_seconds == 1.0
    assert settings.job_lease_seconds == 300
    assert settings.job_backoff_base_seconds == 60
    assert settings.job_max_attempts == 5
    assert settings.meta_db_path.name == "meta.db"


def test_relative_meta_db_path_resolves_from_backend_root():
    from pathlib import Path

    from app.config import BACKEND_ROOT, Settings

    settings = Settings(_env_file=None, meta_db_path=Path("custom/meta.db"))
    assert settings.meta_db_path == (BACKEND_ROOT / "custom/meta.db").resolve()
