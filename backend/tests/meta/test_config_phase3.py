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
    # DSL_COMPILER_VERSION 5 covers the pair-elimination legibility wave: the
    # compiler emits an outside-in dim to `neutral` from a collection born
    # `structure`, drops the `evaluated_answer` visual in favour of
    # `answer_anchor`, and the renderer builds each visual in its declared
    # initial role.
    #
    # DSL_COMPILER_VERSION 6 adds the `unit_tape` visual kind and the
    # `unit_substitution` strategy to `dsl/teaching_plan.py` and
    # `dsl/scene_program.py`.
    #
    # DSL_COMPILER_VERSION 7 pairs `unit_tape` with `unit_rate`: the compiler
    # stages a per-one focus on box[0] at the reveal beat (preserving generic
    # role changes for other targets), rejects a plan whose tape value is not
    # guaranteed >= 1, and the quality gate rejects any active whole-tape
    # focus through the reveal.
    #
    # DYNAMIC_RENDERER_VERSION 6 covers `number_line` labelling each marker and
    # reserving a strip below the line for those labels, growing its measured
    # height; and the line itself moving to draw at its markers' y instead of
    # at its label-padded bounds' center, so it passes through its own dots
    # again.
    #
    # DSL_COMPILER_VERSION 8 adds the `coordinate_plane` visual kind and the
    # matching `CoordinatePlaneProgramVisual`; a version-7 compiler cannot
    # recognise the new kind, so a report stamped 7 must go stale.
    #
    # DYNAMIC_RENDERER_VERSION 7 covers rendering the new `coordinate_plane`
    # visual kind (axes through the projected zero, plotted points with
    # labels, whole-number ticks); a version-6 renderer cannot deserialize the
    # new frozen visual.
    #
    # DSL_COMPILER_VERSION 8 adds the optional `grid` flag on
    # `CoordinatePlaneVisual` (issue #108 acceptance); a plan requesting a
    # grid cannot be validated against the version-7 model, which forbids
    # extra fields.
    #
    # DYNAMIC_RENDERER_VERSION 8 covers optional grid lines, per-point
    # `label_dx`/`label_dy` quadrant offsets, and skipping tick labels the
    # measurer suppressed to avoid overlapping a point label -- a version-7
    # renderer would overlay glyphs the newer measurer already resolved.
    #
    # DSL_COMPILER_VERSION 9 adds the `data_display` visual kind (M19: single
    # kind with a `display_style` variant selector covering bar_graph,
    # line_plot, dot_plot, histogram, box_plot). A version-8 compiler cannot
    # deserialize the new kind.
    #
    # DYNAMIC_RENDERER_VERSION 9 covers building each of the five
    # `data_display` styles as a rendered visual -- a version-8 renderer has
    # no branch for the new kind.
    #
    # DSL_COMPILER_VERSION 10 adds the `inverse_operation` strategy on `bar`
    # (M11: one-/two-step equation solving on a tape-diagram bar) and the
    # `ray_shade` strategy on `number_line` (M11: inequality boundary + ray).
    # A version-9 compiler rejects the new strategy literals as unknown enum
    # values.
    #
    # DSL_COMPILER_VERSION 11 introduces the equation-partition DSL fields
    # (`BarVisual.constant` / `.coefficient` and `NumberLineVisual.boundary`
    # / `.boundary_kind` / `.ray_direction`) and the compiler branches that
    # stage x_region / constant_region / x_part role changes for
    # `inverse_operation` and boundary-circle / shaded-ray reveals for
    # `ray_shade`. A version-10 compiler rejects the new fields as unknown.
    #
    # DYNAMIC_RENDERER_VERSION 10 draws the bar's partition dividers and the
    # number_line's open/closed boundary circle plus shaded ray -- primitives
    # a version-9 renderer has no branch for.
    #
    # DSL_COMPILER_VERSION 12 adds the `equivalence_align` and
    # `common_denominator_bridge` strategies on `partition`; a version-11
    # compiler rejects the new strategy literals, so a plan that carries
    # them cannot be validated against the older model.
    assert DSL_COMPILER_VERSION == 12
    assert DYNAMIC_RENDERER_VERSION == 10
