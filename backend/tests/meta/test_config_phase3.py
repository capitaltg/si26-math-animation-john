from pathlib import Path

from app.config import Settings, get_settings
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION


def test_meta_artifact_root_defaults_under_backend_var(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("META_ARTIFACT_ROOT", raising=False)
    settings = Settings()
    assert settings.meta_artifact_root.is_absolute()
    assert settings.meta_artifact_root.parts[-2:] == ("var", "meta_artifacts")


def test_meta_artifact_root_resolves_relative_path(monkeypatch, tmp_path):
    monkeypatch.setenv("META_ARTIFACT_ROOT", "relative/artifacts")
    get_settings.cache_clear()
    try:
        settings = Settings()
        assert settings.meta_artifact_root.is_absolute()
        assert settings.meta_artifact_root.name == "artifacts"
    finally:
        get_settings.cache_clear()


def test_meta_draft_max_refinements_default():
    assert Settings().meta_draft_max_refinements == 5


def test_version_constants_are_positive_ints():
    assert isinstance(DSL_COMPILER_VERSION, int) and DSL_COMPILER_VERSION >= 1
    assert isinstance(DYNAMIC_RENDERER_VERSION, int) and DYNAMIC_RENDERER_VERSION >= 1
