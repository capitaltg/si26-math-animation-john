from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.templates.fraction_bar.guard import check_fraction_bar_compatibility


class FractionStep(BaseModel):
    operation: Literal["add", "subtract"]
    numerator: int = Field(gt=0)


class FractionBarParams(BaseModel):
    denominator: int = Field(gt=1)
    start_numerator: int = Field(ge=0)
    steps: list[FractionStep] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _check_guard(self):
        check_fraction_bar_compatibility(self)
        return self

    def grounding_number_tokens(self) -> list[str]:
        tokens = [f"{self.start_numerator}/{self.denominator}"]
        tokens += [f"{step.numerator}/{self.denominator}" for step in self.steps]
        return tokens
