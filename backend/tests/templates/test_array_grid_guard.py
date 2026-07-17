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


@pytest.mark.parametrize(("rows", "cols"), [(1, 13), (13, 1)])
def test_overlong_single_axis_is_rejected(rows, cols):
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams(rows=rows, cols=cols)


def test_schema_exposes_axis_limits_to_bedrock():
    from app.templates.array_grid.params import ArrayGridParams

    properties = ArrayGridParams.model_json_schema()["properties"]

    assert properties["rows"]["maximum"] == 12
    assert properties["cols"]["maximum"] == 12
