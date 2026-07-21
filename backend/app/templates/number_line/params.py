from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.templates.number_line.guard import check_number_line_compatibility


class NumberLineStep(BaseModel):
    operation: Literal["add", "subtract"]
    amount: int = Field(gt=0)


class NumberLineParams(BaseModel):
    start: int = Field(
        description="first operand in the problem statement; never swap operand order"
    )
    steps: list[NumberLineStep] = Field(
        min_length=1,
        max_length=3,
        description="Operations for subsequent operands in source order",
    )

    @model_validator(mode="after")
    def _check_guard(self):
        check_number_line_compatibility(self)
        return self
