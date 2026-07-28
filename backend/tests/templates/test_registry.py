import pytest


def test_get_template_returns_scene_and_params_classes():
    from app.models.scene import TemplateName
    from app.templates.registry import get_template
    from app.templates.number_line.scene import NumberLineScene
    from app.templates.number_line.params import NumberLineParams

    scene_cls, params_cls = get_template(TemplateName.NUMBER_LINE)

    assert scene_cls is NumberLineScene
    assert params_cls is NumberLineParams


def test_get_template_accepts_a_plain_string():
    from app.templates.registry import get_template

    scene_cls, params_cls = get_template("array_grid")

    assert scene_cls.__name__ == "ArrayGridScene"
    assert params_cls.__name__ == "ArrayGridParams"


def test_get_template_returns_fraction_of_whole_scene_and_params():
    from app.models.scene import TemplateName
    from app.templates.registry import get_template
    from app.templates.fraction_of_whole.scene import FractionOfWholeScene
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    scene_cls, params_cls = get_template(TemplateName.FRACTION_OF_WHOLE)

    assert scene_cls is FractionOfWholeScene
    assert params_cls is FractionOfWholeParams


def test_get_chained_template_returns_chained_pairs():
    from app.models.scene import TemplateName
    from app.templates.registry import get_chained_template
    from app.templates.number_line.params import ChainedNumberLineParams
    from app.templates.number_line.scene import ChainedNumberLineScene

    scene_cls, params_cls = get_chained_template(TemplateName.NUMBER_LINE)

    assert scene_cls is ChainedNumberLineScene
    assert params_cls is ChainedNumberLineParams


def test_get_chained_template_rejects_text_card():
    from app.models.scene import TemplateName
    from app.templates.registry import get_chained_template

    with pytest.raises(KeyError):
        get_chained_template(TemplateName.TEXT_CARD)


def test_static_ref_is_stable_for_the_same_template():
    from app.models.scene import TemplateName
    from app.templates.registry import static_ref

    a = static_ref(TemplateName.NUMBER_LINE)
    b = static_ref(TemplateName.NUMBER_LINE)
    assert a == b
    assert a.name == TemplateName.NUMBER_LINE
    assert a.version_id == "1"
    assert a.artifact_hash.startswith("sha256:")


def test_static_ref_differs_across_templates():
    from app.models.scene import TemplateName
    from app.templates.registry import static_ref

    number_line = static_ref(TemplateName.NUMBER_LINE)
    array_grid = static_ref(TemplateName.ARRAY_GRID)
    assert number_line.artifact_hash != array_grid.artifact_hash


def test_get_template_accepts_a_matching_template_ref():
    from app.templates.registry import get_template, static_ref
    from app.templates.number_line.scene import NumberLineScene
    from app.templates.number_line.params import NumberLineParams

    ref = static_ref("number_line")
    scene_cls, params_cls = get_template(ref)
    assert scene_cls is NumberLineScene
    assert params_cls is NumberLineParams


def test_get_template_rejects_a_template_ref_with_a_stale_hash():
    from app.models.scene import TemplateArtifactMismatchError, TemplateName, TemplateRef
    from app.templates.registry import get_template

    stale = TemplateRef(
        name=TemplateName.NUMBER_LINE, version_id="1", artifact_hash="sha256:0000"
    )
    with pytest.raises(TemplateArtifactMismatchError):
        get_template(stale)


def test_get_template_rejects_a_template_ref_with_a_stale_version():
    from app.models.scene import TemplateVersionMismatchError
    from app.templates.registry import get_template, static_ref

    current = static_ref("number_line")
    stale = current.model_copy(update={"version_id": "stale"})
    with pytest.raises(TemplateVersionMismatchError):
        get_template(stale)


def test_get_template_recomputes_the_hash_when_verifying_a_ref(monkeypatch):
    from app.models.scene import TemplateArtifactMismatchError
    from app.templates import registry

    ref = registry.static_ref("number_line")
    monkeypatch.setattr(registry, "_compute_artifact_hash", lambda _name: "sha256:drift")
    with pytest.raises(TemplateArtifactMismatchError):
        registry.get_template(ref)


def test_get_chained_template_accepts_a_matching_template_ref():
    from app.templates.registry import get_chained_template, static_ref
    from app.templates.number_line.scene import ChainedNumberLineScene

    ref = static_ref("number_line")
    scene_cls, _ = get_chained_template(ref)
    assert scene_cls is ChainedNumberLineScene
