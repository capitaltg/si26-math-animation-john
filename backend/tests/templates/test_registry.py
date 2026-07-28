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
