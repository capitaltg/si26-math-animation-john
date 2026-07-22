from pydantic import BaseModel, Field, model_validator

from app.templates.balance_scale.guard import check_balance_scale_compatibility


class BalanceScaleParams(BaseModel):
    left_terms: list[int] = Field(min_length=2, max_length=2)
    right_total: int

    @model_validator(mode="after")
    def _check_guard(self):
        check_balance_scale_compatibility(self)
        return self

    def grounding_derived_totals(self):
        # right_total is a derived total: the guard enforces it equals the sum
        # of left_terms, so it need not appear literally in the source.
        components = [str(term) for term in self.left_terms]
        return [(str(self.right_total), components)]
