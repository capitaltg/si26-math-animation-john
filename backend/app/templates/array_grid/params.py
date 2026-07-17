from pydantic import BaseModel, Field, model_validator

from app.templates.array_grid.guard import check_array_grid_compatibility


class ArrayGridParams(BaseModel):
    rows: int = Field(gt=0, le=12)
    cols: int = Field(gt=0, le=12)

    @model_validator(mode="after")
    def _check_guard(self):
        check_array_grid_compatibility(self)
        return self
