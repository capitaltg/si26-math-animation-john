from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class StyleRecipe:
    palette: str
    composition: str
    motion_variant: str


def resolve_style_recipe(
    *, seed: str, visual_kind: str, strategy: str,
    concept_family: str, grade_band: str, content_density: str,
) -> StyleRecipe:
    key = ":".join((
        seed, visual_kind, strategy, concept_family, grade_band, content_density,
    ))
    digest = hashlib.sha256(key.encode()).digest()
    palettes = ("ocean", "violet", "teal")
    motion = ("smooth", "crisp")
    return StyleRecipe(
        palette=palettes[digest[0] % len(palettes)],
        composition="vertical_lesson",
        motion_variant=motion[digest[1] % len(motion)],
    )
