from typing import Literal

from pydantic import BaseModel, model_validator

from app.templates.number_line.guard import check_number_line_compatibility


class NumberLineStep(BaseModel):
    operation: Literal["add", "subtract"]
    amount: int


class NumberLineParams(BaseModel):
    start: int
    steps: list[NumberLineStep]

    @model_validator(mode="after")
    def _check_guard(self):
        check_number_line_compatibility(self)
        return self
