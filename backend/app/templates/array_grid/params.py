from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.templates.array_grid.guard import check_array_grid_compatibility


class ArrayGridStep(BaseModel):
    operation: Literal["multiply", "divide"]
    factor: int = Field(gt=0)


class ArrayGridParams(BaseModel):
    rows: int = Field(gt=0, le=12)
    cols: int = Field(gt=0, le=12)
    steps: list[ArrayGridStep] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _check_guard(self):
        check_array_grid_compatibility(self)
        return self


class ChainedArrayGridParams(BaseModel):
    items: list[ArrayGridParams] = Field(min_length=2, max_length=4)
