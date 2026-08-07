from fractions import Fraction
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

    def compute_answer(self) -> Fraction:
        total = self.start
        for step in self.steps:
            if step.operation == "add":
                total += step.amount
            else:
                total -= step.amount
        return Fraction(total)


class ChainedNumberLineParams(BaseModel):
    items: list[NumberLineParams] = Field(min_length=2, max_length=4)

    def compute_answer(self) -> Fraction:
        return self.items[-1].compute_answer()
