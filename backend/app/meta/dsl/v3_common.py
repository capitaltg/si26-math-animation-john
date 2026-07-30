from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StyleRole = Literal["neutral", "structure", "focus", "conclusion", "constraint"]
AnchorName = Literal["center", "top", "bottom", "left", "right"]

MIN_PLAN_BEATS = 3
MAX_PLAN_BEATS = 5
MIN_SCENE_SECONDS = 6.0
MAX_SCENE_SECONDS = 12.0
MIN_ACTION_SECONDS = 0.15
MAX_ACTION_SECONDS = 2.0
MAX_SIMPLE_STAGGER_SECONDS = 0.15
MIN_CONCLUSION_HOLD_SECONDS = 1.5


class TargetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    part: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
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
    concept_family: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    grade_band: Literal["K-2", "3-5", "6-8"]
