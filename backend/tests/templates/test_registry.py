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
