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


def test_version_constants_identify_the_current_compiler_and_renderer_wave():
    # Both constants are part of every draft's artifact hash and of approval's
    # stale-runtime precondition, so a compiler or renderer change has to bump
    # them: a draft validated by an older compiler must not stay approvable under
    # a newer one. This is the tripwire that keeps the next compiler/renderer
    # change from forgetting the bump.
    #
    # 5 covers the pair-elimination legibility wave: the compiler emits an
    # outside-in dim to `neutral` from a collection born `structure`, drops the
    # `evaluated_answer` visual in favour of `answer_anchor`, and the renderer
    # builds each visual in its declared initial role.
    #
    # 6 covers `number_line` labelling each marker and reserving a strip below
    # the line for those labels, growing its measured height; and the line
    # itself moving to draw at its markers' y instead of at its label-padded
    # bounds' center, so it passes through its own dots again.
    assert DSL_COMPILER_VERSION == 5
    assert DYNAMIC_RENDERER_VERSION == 6
