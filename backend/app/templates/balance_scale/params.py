from pydantic import BaseModel, Field, model_validator

from app.templates.balance_scale.guard import check_balance_scale_compatibility


class BalanceScaleParams(BaseModel):
    left_terms: list[int] = Field(min_length=2, max_length=2)
    right_total: int

    @model_validator(mode="after")
    def _check_guard(self):
        check_balance_scale_compatibility(self)
        return self
