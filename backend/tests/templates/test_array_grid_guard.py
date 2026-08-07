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
    row_schema = next(item for item in properties["rows"]["anyOf"] if item["type"] == "integer")
    col_schema = next(item for item in properties["cols"]["anyOf"] if item["type"] == "integer")

    assert row_schema["maximum"] == 12
    assert col_schema["maximum"] == 12


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

    # rows*cols=6, ×2 -> 12, ÷4 -> 3 — each state has a deterministic
    # renderable factor pair within the per-axis bound.
    params = ArrayGridParams(
        rows=2,
        cols=3,
        steps=[
            ArrayGridStep(operation="multiply", factor=2),
            ArrayGridStep(operation="divide", factor=4),
        ],
    )
    assert len(params.steps) == 2


def test_non_exact_division_in_chain_is_allowed():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    # Non-exact divisions are now allowed and handled as fractions in compute_answer
    params = ArrayGridParams(
        rows=2, cols=3, steps=[ArrayGridStep(operation="divide", factor=4)]
    )
    assert params is not None


def test_chain_total_can_reflow_away_from_fixed_cols():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    params = ArrayGridParams(
        rows=2, cols=4, steps=[ArrayGridStep(operation="divide", factor=8)]
    )

    assert params.starting_total() == 8


def test_chain_intermediate_exceeding_axis_bound_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    with pytest.raises(ValidationError):
        ArrayGridParams(
            rows=2, cols=2, steps=[ArrayGridStep(operation="multiply", factor=50)]
        )


def test_chain_intermediate_without_bounded_factor_pair_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    with pytest.raises(ValidationError, match="no renderable factor pair"):
        ArrayGridParams(
            start=1,
            steps=[ArrayGridStep(operation="multiply", factor=13)],
        )


def test_chain_accepts_grounded_start_without_display_dimensions():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    params = ArrayGridParams(
        start=24,
        steps=[
            ArrayGridStep(operation="divide", factor=3),
            ArrayGridStep(operation="multiply", factor=2),
        ],
    )

    assert params.starting_total() == 24
    assert params.rows is None
    assert params.cols is None


def test_legacy_chain_uses_rows_times_cols_as_start():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    params = ArrayGridParams(
        rows=2,
        cols=3,
        steps=[ArrayGridStep(operation="divide", factor=3)],
    )

    assert params.starting_total() == 6


def test_exact_division_can_change_both_grid_dimensions():
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep
    from app.templates.array_grid.guard import check_array_grid_compatibility
    from app.templates.array_grid.layout import grid_dimensions

    params = ArrayGridParams(
        rows=2,
        cols=3,
        steps=[ArrayGridStep(operation="divide", factor=3)],
    )

    check_array_grid_compatibility(params)
    assert grid_dimensions(params.starting_total()) == (2, 3)
    assert grid_dimensions(2) == (1, 2)


@pytest.mark.parametrize(
    ("total", "expected"),
    [(24, (4, 6)), (8, (2, 4)), (16, (4, 4)), (2, (1, 2))],
)
def test_grid_dimensions_choose_near_square_renderable_pair(total, expected):
    from app.templates.array_grid.layout import grid_dimensions

    assert grid_dimensions(total) == expected


def test_grid_dimensions_reject_total_without_bounded_factor_pair():
    from app.templates.array_grid.layout import grid_dimensions

    with pytest.raises(ValueError, match="no renderable factor pair"):
        grid_dimensions(13)


@pytest.mark.parametrize(
    "payload",
    [
        {"rows": 2},
        {"cols": 3},
        {"start": 24},
        {"start": 24, "rows": 4, "cols": 6, "steps": [{"operation": "divide", "factor": 3}]},
        {"steps": [{"operation": "divide", "factor": 3}]},
    ],
)
def test_array_grid_rejects_incomplete_or_conflicting_modes(payload):
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams.model_validate(payload)
