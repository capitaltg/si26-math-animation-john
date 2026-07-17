import pytest
from pydantic import ValidationError


def test_valid_steps_pass_the_guard():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=4,
        steps=[
            NumberLineStep(operation="add", amount=3),
            NumberLineStep(operation="subtract", amount=2),
        ],
    )
    assert params.start == 4


def test_running_total_going_negative_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=2,
            steps=[
                NumberLineStep(operation="subtract", amount=5),
                NumberLineStep(operation="add", amount=1),
            ],
        )


@pytest.mark.parametrize("step_count", [0, 1, 4])
def test_step_count_outside_two_to_three_is_rejected(step_count):
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    steps = [NumberLineStep(operation="add", amount=1) for _ in range(step_count)]
    with pytest.raises(ValidationError):
        NumberLineParams(start=2, steps=steps)


@pytest.mark.parametrize("amount", [0, -3])
def test_non_positive_step_amount_is_rejected(amount):
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=2,
            steps=[
                NumberLineStep(operation="add", amount=amount),
                NumberLineStep(operation="subtract", amount=1),
            ],
        )


def test_schema_exposes_step_constraints_to_bedrock():
    from app.templates.number_line.params import NumberLineParams

    schema = NumberLineParams.model_json_schema()

    assert schema["properties"]["steps"]["minItems"] == 2
    assert schema["properties"]["steps"]["maxItems"] == 3
    amount_schema = schema["$defs"]["NumberLineStep"]["properties"]["amount"]
    assert amount_schema["exclusiveMinimum"] == 0
