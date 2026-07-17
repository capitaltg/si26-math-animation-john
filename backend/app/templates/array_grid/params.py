from pydantic import BaseModel, model_validator

from app.templates.array_grid.guard import check_array_grid_compatibility


class ArrayGridParams(BaseModel):
    rows: int
    cols: int

    @model_validator(mode="after")
    def _check_guard(self):
        check_array_grid_compatibility(self)
        return self
