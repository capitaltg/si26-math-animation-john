from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class TemplateName(str, Enum):
    NUMBER_LINE = "number_line"
    ARRAY_GRID = "array_grid"


class Scene(BaseModel):
    scene_id: str
    candidate_id: str | None = None
    manual_source_text: str | None = None
    template: TemplateName | None = None
    grade_level: int
    grade_overridden: bool = False
    params: dict = Field(default_factory=dict)
    stated_answer: Fraction | None = None
    status: Literal["pending_review", "approved", "rejected", "fallback"] = "pending_review"
    fallback_reason: str | None = None
    thumbnail_path: Path | None = None
    render_path: Path | None = None
