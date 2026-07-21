from app.models.scene import TemplateName
from app.templates.array_grid.params import ArrayGridParams
from app.templates.array_grid.scene import ArrayGridScene
from app.templates.number_line.params import NumberLineParams
from app.templates.number_line.scene import NumberLineScene
from app.templates.text_card.params import TextCardParams
from app.templates.text_card.scene import TextCardScene

_REGISTRY = {
    TemplateName.NUMBER_LINE: (NumberLineScene, NumberLineParams),
    TemplateName.ARRAY_GRID: (ArrayGridScene, ArrayGridParams),
    TemplateName.TEXT_CARD: (TextCardScene, TextCardParams),
}


def get_template(name: TemplateName | str) -> tuple[type, type]:
    key = TemplateName(name)
    return _REGISTRY[key]
