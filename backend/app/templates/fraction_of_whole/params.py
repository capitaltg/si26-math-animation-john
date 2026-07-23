from pydantic import BaseModel, Field, model_validator

from app.templates.fraction_of_whole.guard import check_fraction_of_whole_compatibility


class FractionOfWholeParams(BaseModel):
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=1, le=12)

    @model_validator(mode="after")
    def _check_guard(self):
        check_fraction_of_whole_compatibility(self)
        return self

    def grounding_number_tokens(self) -> list[str]:
        return [f"{self.numerator}/{self.denominator}"]
