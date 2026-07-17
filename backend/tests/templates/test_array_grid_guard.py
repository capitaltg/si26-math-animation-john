import pytest
from pydantic import ValidationError


def test_valid_grid_passes():
    from app.templates.array_grid.params import ArrayGridParams

    params = ArrayGridParams(rows=3, cols=4)
    assert params.rows == 3


def test_oversized_grid_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams(rows=20, cols=20)


def test_non_positive_dimensions_are_rejected():
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams(rows=0, cols=4)
