from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.templates.array_grid.guard import check_array_grid_compatibility


class ArrayGridStep(BaseModel):
    operation: Literal["multiply", "divide"]
    factor: int = Field(gt=0)


class ArrayGridParams(BaseModel):
    rows: int | None = Field(
        default=None,
        gt=0,
        le=12,
        description="Rows explicitly stated for a static or legacy array; omit for a chain with start",
    )
    cols: int | None = Field(
        default=None,
        gt=0,
        le=12,
        description="Columns explicitly stated for a static or legacy array; omit for a chain with start",
    )
    start: int | None = Field(
        default=None,
        gt=0,
        description="Source-stated starting total for a multiply/divide chain; omit for a static rows-by-cols array",
    )
    steps: list[ArrayGridStep] = Field(default_factory=list, max_length=3)

    def starting_total(self) -> int:
        if self.start is not None:
            return self.start
        if self.rows is None or self.cols is None:
            raise ValueError("Array grid requires both rows and cols")
        return self.rows * self.cols

    @model_validator(mode="after")
    def _check_guard(self):
        has_rows = self.rows is not None
        has_cols = self.cols is not None
        if has_rows != has_cols:
            raise ValueError("Array grid requires both rows and cols together")
        if self.steps:
            if self.start is None and not has_rows:
                raise ValueError("Array grid chain requires start or legacy rows and cols")
            if self.start is not None and has_rows:
                raise ValueError("Array grid chain cannot combine start with rows and cols")
        elif self.start is not None or not has_rows:
            raise ValueError("Static array grid requires rows and cols and no start")

        check_array_grid_compatibility(self)
        return self


class ChainedArrayGridParams(BaseModel):
    items: list[ArrayGridParams] = Field(min_length=2, max_length=4)
