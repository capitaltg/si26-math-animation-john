import hashlib
from functools import lru_cache
from pathlib import Path

from app.models.scene import (
    TemplateArtifactMismatchError,
    TemplateName,
    TemplateRef,
    TemplateVersionMismatchError,
)
from app.templates.array_grid.params import ArrayGridParams, ChainedArrayGridParams
from app.templates.array_grid.scene import (
    ArrayGridScene,
    ChainedArrayGridScene,
    CONTRACT_VERSION as _ARRAY_GRID_CONTRACT_VERSION,
)
from app.templates.balance_scale.params import BalanceScaleParams, ChainedBalanceScaleParams
from app.templates.balance_scale.scene import (
    BalanceScaleScene,
    ChainedBalanceScaleScene,
    CONTRACT_VERSION as _BALANCE_SCALE_CONTRACT_VERSION,
)
from app.templates.fraction_bar.params import ChainedFractionBarParams, FractionBarParams
from app.templates.fraction_bar.scene import (
    ChainedFractionBarScene,
    FractionBarScene,
    CONTRACT_VERSION as _FRACTION_BAR_CONTRACT_VERSION,
)
from app.templates.fraction_of_whole.params import (
    ChainedFractionOfWholeParams,
    FractionOfWholeParams,
)
from app.templates.fraction_of_whole.scene import (
    ChainedFractionOfWholeScene,
    FractionOfWholeScene,
    CONTRACT_VERSION as _FRACTION_OF_WHOLE_CONTRACT_VERSION,
)
from app.templates.number_line.params import ChainedNumberLineParams, NumberLineParams
from app.templates.number_line.scene import (
    ChainedNumberLineScene,
    NumberLineScene,
    CONTRACT_VERSION as _NUMBER_LINE_CONTRACT_VERSION,
)
from app.templates.text_card.params import TextCardParams
from app.templates.text_card.scene import (
    TextCardScene,
    CONTRACT_VERSION as _TEXT_CARD_CONTRACT_VERSION,
)

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

_CONTRACT_VERSIONS = {
    TemplateName.NUMBER_LINE: _NUMBER_LINE_CONTRACT_VERSION,
    TemplateName.ARRAY_GRID: _ARRAY_GRID_CONTRACT_VERSION,
    TemplateName.TEXT_CARD: _TEXT_CARD_CONTRACT_VERSION,
    TemplateName.FRACTION_BAR: _FRACTION_BAR_CONTRACT_VERSION,
    TemplateName.BALANCE_SCALE: _BALANCE_SCALE_CONTRACT_VERSION,
    TemplateName.FRACTION_OF_WHOLE: _FRACTION_OF_WHOLE_CONTRACT_VERSION,
}

_TEMPLATES_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def _artifact_hash(name: TemplateName) -> str:
    return _compute_artifact_hash(name)


def _compute_artifact_hash(name: TemplateName) -> str:
    digest = hashlib.sha256()
    source_files = sorted((_TEMPLATES_DIR / name.value).glob("*.py"))
    for path in source_files:
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def static_ref(name: TemplateName | str) -> TemplateRef:
    key = TemplateName(name)
    return TemplateRef(
        name=key,
        version_id=str(_CONTRACT_VERSIONS[key]),
        artifact_hash=_artifact_hash(key),
    )


def resolve_static_ref(name: TemplateName | str, version_id: str) -> TemplateRef:
    current = static_ref(name)
    if version_id != current.version_id:
        raise TemplateVersionMismatchError(
            f"Template {current.name.value!r} version {version_id!r} is no longer loadable; "
            f"the current contract version is {current.version_id!r}"
        )
    return current


def _resolve_key(ref: TemplateName | str | TemplateRef) -> TemplateName:
    if isinstance(ref, TemplateRef):
        current = static_ref(ref.name)
        if ref.version_id != current.version_id:
            raise TemplateVersionMismatchError(
                f"TemplateRef for {ref.name.value!r} has version_id {ref.version_id!r}, "
                f"but the current contract version is {current.version_id!r}"
            )
        actual_hash = _compute_artifact_hash(ref.name)
        if ref.artifact_hash != actual_hash:
            raise TemplateArtifactMismatchError(
                f"TemplateRef for {ref.name.value!r} has artifact_hash {ref.artifact_hash!r}, "
                f"but the template's current source hashes to {actual_hash!r}"
            )
        return ref.name
    return TemplateName(ref)


def get_template(name: TemplateName | str | TemplateRef) -> tuple[type, type]:
    return _REGISTRY[_resolve_key(name)]


def get_chained_template(name: TemplateName | str | TemplateRef) -> tuple[type, type]:
    return _CHAINED_REGISTRY[_resolve_key(name)]
