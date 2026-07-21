import pytest
from pydantic import ValidationError


def test_same_denominator_addition_passes():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="add", numerator=1),
        ],
    )
    assert params.denominator == 4


def test_running_total_going_negative_is_rejected():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    with pytest.raises(ValidationError):
        FractionBarParams(
            denominator=4,
            start_numerator=1,
            steps=[
                FractionStep(operation="subtract", numerator=3),
                FractionStep(operation="add", numerator=1),
            ],
        )


def test_total_over_renderable_bound_is_rejected():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    with pytest.raises(ValidationError):
        FractionBarParams(
            denominator=4,
            start_numerator=4,
            steps=[
                FractionStep(operation="add", numerator=8),
                FractionStep(operation="add", numerator=8),
            ],
        )


def test_denominator_of_one_is_rejected():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    with pytest.raises(ValidationError):
        FractionBarParams(
            denominator=1,
            start_numerator=0,
            steps=[
                FractionStep(operation="add", numerator=1),
                FractionStep(operation="add", numerator=1),
            ],
        )


@pytest.mark.parametrize("step_count", [0, 1, 4])
def test_step_count_outside_two_to_three_is_rejected(step_count):
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    steps = [FractionStep(operation="add", numerator=1) for _ in range(step_count)]
    with pytest.raises(ValidationError):
        FractionBarParams(denominator=4, start_numerator=0, steps=steps)
