from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TemplateName(str, Enum):
    NUMBER_LINE = "number_line"
    ARRAY_GRID = "array_grid"
    TEXT_CARD = "text_card"
    FRACTION_BAR = "fraction_bar"
    BALANCE_SCALE = "balance_scale"
    FRACTION_OF_WHOLE = "fraction_of_whole"


class Scene(BaseModel):
    scene_id: str
    candidate_id: str | None = None
    candidate_ids: list[str] | None = None
    manual_source_text: str | None = None
    template: TemplateName | None = None
    grade_level: int = Field(ge=0, le=8)
    grade_overridden: bool = False
    params: dict = Field(default_factory=dict)
    stated_answer: Fraction | None = None
    status: Literal["pending_review", "approved", "rejected", "fallback"] = "pending_review"
    fallback_reason: str | None = None
    thumbnail_path: Path | None = None
    render_path: Path | None = None

    @model_validator(mode="after")
    def _check_workflow_invariants(self):
        has_candidate = bool(self.candidate_id and self.candidate_id.strip())
        has_candidate_group = bool(self.candidate_ids)
        has_manual_source = bool(
            self.manual_source_text and self.manual_source_text.strip()
        )
        source_count = sum([has_candidate, has_candidate_group, has_manual_source])
        if source_count != 1:
            raise ValueError(
                "Scene requires exactly one source: candidate_id, candidate_ids, or manual_source_text"
            )

        has_fallback_reason = bool(
            self.fallback_reason and self.fallback_reason.strip()
        )
        if self.status == "fallback" and not has_fallback_reason:
            raise ValueError("Fallback scenes require a nonblank fallback_reason")
        if self.status != "fallback" and self.fallback_reason is not None:
            raise ValueError("Only fallback scenes may include fallback_reason")
        return self
