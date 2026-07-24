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


def test_steps_default_to_empty_for_single_fact_usage():
    from app.templates.array_grid.params import ArrayGridParams

    params = ArrayGridParams(rows=3, cols=4)
    assert params.steps == []


def test_non_positive_factor_is_rejected():
    from app.templates.array_grid.params import ArrayGridStep

    with pytest.raises(ValidationError):
        ArrayGridStep(operation="multiply", factor=0)


def test_valid_multiplicative_chain_passes():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    # rows*cols=6, ×2 -> 12 (4 rows), ÷4 -> 3 (1 row) — every intermediate
    # total stays divisible by the fixed cols=3, unlike ÷3 here which would
    # leave a total (4) that doesn't divide evenly by cols.
    params = ArrayGridParams(
        rows=2,
        cols=3,
        steps=[
            ArrayGridStep(operation="multiply", factor=2),
            ArrayGridStep(operation="divide", factor=4),
        ],
    )
    assert len(params.steps) == 2


def test_non_exact_division_in_chain_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    with pytest.raises(ValidationError):
        ArrayGridParams(
            rows=2, cols=3, steps=[ArrayGridStep(operation="divide", factor=4)]
        )


def test_chain_total_not_divisible_by_fixed_cols_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    with pytest.raises(ValidationError):
        ArrayGridParams(
            rows=2, cols=4, steps=[ArrayGridStep(operation="divide", factor=8)]
        )


def test_chain_intermediate_exceeding_axis_bound_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    with pytest.raises(ValidationError):
        ArrayGridParams(
            rows=2, cols=2, steps=[ArrayGridStep(operation="multiply", factor=20)]
        )
