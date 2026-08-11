import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

StyleRole = Literal["neutral", "structure", "focus", "conclusion", "constraint"]
AnchorName = Literal["center", "top", "bottom", "left", "right"]

MIN_PLAN_BEATS = 3
MAX_PLAN_BEATS = 5
MIN_SCENE_SECONDS = 12.0
MAX_SCENE_SECONDS = 24.0
MIN_ACTION_SECONDS = 0.3
MAX_ACTION_SECONDS = 4.0
MAX_SIMPLE_STAGGER_SECONDS = 0.3
MIN_CONCLUSION_HOLD_SECONDS = 3.0

# Legacy floors preserved so `SceneProgramDocument.model_validate_json` still
# accepts scene programs published under the pre-2x pace (6-12s scenes, actions
# down to 0.15s). New drafts are held to the current `MIN_*` values by
# `schedule_beats`/`check_conclusion_hold`/`check_rendered_duration`, but stored
# programs deserialized in `dynamic_templates.load` must not be rejected here.
LEGACY_MIN_SCENE_SECONDS = 6.0
LEGACY_MIN_ACTION_SECONDS = 0.15

# Rules that hold for every generated string, whether it names a reference or is
# shown to a learner. Nothing here can appear in legitimate K-8 math wording.
_SHARED_TEXT_RULES = (
    (re.compile(r"(?:https?|ftp)://|\bwww\.", re.IGNORECASE), "URLs"),
    (re.compile(r"\b(?:from\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s+import|import\s+[A-Za-z_])"), "imports"),
    (re.compile(
        r"\b(?:scene|self)\s*\.\s*(?:play|add|remove|wait|construct)\s*\(|"
        r"\b(?:FadeIn|FadeOut|Create|Transform|MoveToTarget|Write|GrowFromCenter)\s*\("
    ), "Python or Manim calls"),
    (re.compile(r"(?<!\w)(?:\.\.?[\\/]|[\\/])[^\s]+"), "paths"),
    (re.compile(
        r"\b(?:position|coordinate(?:s)?|point|vector)\s*[:=]\s*[\(\[]\s*[^()[\]]+[,;][^()[\]]+[\)\]]"
        r"|(?<!\w)[\(\[]\s*[-+]?\d+(?:\.\d+)?(?:\s*,\s*[-+]?\d+(?:\.\d+)?){1,3}\s*[\)\]]"
    ), "raw coordinates"),
    (re.compile(
        r"#[0-9a-f]{3,8}\b|\b(?:color|fill_color|stroke_color)\s*[:=]|"
        r"(?<![A-Za-z])(?:BLUE|RED|GREEN|YELLOW|ORANGE|PURPLE|PINK|WHITE|BLACK|GRAY|GREY|TEAL|MAROON)(?![A-Za-z])"
    ), "raw colors"),
    (re.compile(
        r"\b(?:easing|ease|rate_func|interpolation|interpolate)\s*[:=]"
        r"|\b(?:easeIn|easeOut|easeInOut|linear|smooth)\s*\("
    ), "easing directives"),
    (re.compile(r"\b(?:eval|exec|compile|__import__)\s*\("), "executable Python"),
)

# Extra rules for identifier-shaped strings (refs, ids, seeds). These reject any
# `name = ...` or `Name(...)` shape outright. They are deliberately NOT applied to
# learner-facing prose, where "P = 2 x (length + width)" and "Area (square units)"
# are the content, not code. Prose is passed to Manim as a runtime string value
# (see app/meta/v3/renderer.py) and is never compiled or evaluated.
_IDENTIFIER_TEXT_RULES = _SHARED_TEXT_RULES + (
    (re.compile(r"\b[A-Z][A-Za-z0-9_]*\s*\("), "Python or Manim calls"),
    (re.compile(r"(?<!\w)[A-Za-z_]\w*\s*=(?!=)"), "Python assignments"),
)


def _validate_against(value: str, rules) -> str:
    for pattern, category in rules:
        if pattern.search(value):
            raise ValueError(f"generated text contains prohibited {category}")
    return value


def validate_generated_text(value: str) -> str:
    return _validate_against(value, _IDENTIFIER_TEXT_RULES)


def validate_prose_text(value: str) -> str:
    return _validate_against(value, _SHARED_TEXT_RULES)


#: Every character `str.splitlines()` treats as a line break. Manim's
#: `Text` renders each of these as a new line too, so any of them in a
#: callout label would push extra lines past the fixed rendered envelope
#: sized for a single line. Includes U+2028 and U+2029 (LINE / PARAGRAPH
#: SEPARATOR), which a plain `"\n" in value` check would let through.
_LINE_SEPARATORS = frozenset((
    "\n", "\r", "\v", "\f",
    "\x1c", "\x1d", "\x1e", "\x85",
    " ", " ",
))


def validate_single_line_callout_text(value: str) -> str:
    """Callout labels ride a fixed-height rendered envelope (see layout's
    `CALLOUT_ENVELOPE`) sized for a single line of `FONT_SIZES["label"]`
    text. A line break in the label renders extra lines below the anchor
    that the layout has not reserved room for, so the callout would overrun
    into whatever sits below it. Reject at schema time rather than
    discovering the overflow at render.
    """
    if any(sep in value for sep in _LINE_SEPARATORS):
        raise ValueError("callout text must be a single line (no line breaks)")
    return value


GeneratedText = Annotated[str, AfterValidator(validate_generated_text)]
ProseText = Annotated[str, AfterValidator(validate_prose_text)]
CalloutText = Annotated[
    str,
    AfterValidator(validate_prose_text),
    AfterValidator(validate_single_line_callout_text),
]


class TargetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    part: GeneratedText | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    index: int | None = Field(default=None, ge=0, le=63)

    @model_validator(mode="after")
    def index_requires_part(self):
        if self.index is not None and self.part is None:
            raise ValueError("index requires a semantic part")
        return self


class AnchorRef(TargetRef):
    anchor: AnchorName


class CompileContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_family: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    grade_band: Literal["K-2", "3-5", "6-8"]
