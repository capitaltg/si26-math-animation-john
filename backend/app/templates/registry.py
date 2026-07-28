from app.models.scene import TemplateName
from app.templates.array_grid.params import ArrayGridParams, ChainedArrayGridParams
from app.templates.array_grid.scene import ArrayGridScene, ChainedArrayGridScene
from app.templates.balance_scale.params import BalanceScaleParams, ChainedBalanceScaleParams
from app.templates.balance_scale.scene import BalanceScaleScene, ChainedBalanceScaleScene
from app.templates.fraction_bar.params import ChainedFractionBarParams, FractionBarParams
from app.templates.fraction_bar.scene import ChainedFractionBarScene, FractionBarScene
from app.templates.fraction_of_whole.params import (
    ChainedFractionOfWholeParams,
    FractionOfWholeParams,
)
from app.templates.fraction_of_whole.scene import ChainedFractionOfWholeScene, FractionOfWholeScene
from app.templates.number_line.params import ChainedNumberLineParams, NumberLineParams
from app.templates.number_line.scene import ChainedNumberLineScene, NumberLineScene
from app.templates.text_card.params import TextCardParams
from app.templates.text_card.scene import TextCardScene

_REGISTRY = {
    TemplateName.NUMBER_LINE: (NumberLineScene, NumberLineParams),
    TemplateName.ARRAY_GRID: (ArrayGridScene, ArrayGridParams),
    TemplateName.TEXT_CARD: (TextCardScene, TextCardParams),
    TemplateName.FRACTION_BAR: (FractionBarScene, FractionBarParams),
    TemplateName.BALANCE_SCALE: (BalanceScaleScene, BalanceScaleParams),
    TemplateName.FRACTION_OF_WHOLE: (FractionOfWholeScene, FractionOfWholeParams),
}

_CHAINED_REGISTRY = {
    TemplateName.NUMBER_LINE: (ChainedNumberLineScene, ChainedNumberLineParams),
    TemplateName.ARRAY_GRID: (ChainedArrayGridScene, ChainedArrayGridParams),
    TemplateName.FRACTION_BAR: (ChainedFractionBarScene, ChainedFractionBarParams),
    TemplateName.BALANCE_SCALE: (ChainedBalanceScaleScene, ChainedBalanceScaleParams),
    TemplateName.FRACTION_OF_WHOLE: (ChainedFractionOfWholeScene, ChainedFractionOfWholeParams),
}


def get_template(name: TemplateName | str) -> tuple[type, type]:
    key = TemplateName(name)
    return _REGISTRY[key]


def get_chained_template(name: TemplateName | str) -> tuple[type, type]:
    key = TemplateName(name)
    return _CHAINED_REGISTRY[key]
