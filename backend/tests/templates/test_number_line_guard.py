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


def test_negative_start_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=-1,
            steps=[
                NumberLineStep(operation="add", amount=2),
                NumberLineStep(operation="add", amount=1),
            ],
        )


def test_number_line_span_over_twenty_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=0,
            steps=[
                NumberLineStep(operation="add", amount=21),
                NumberLineStep(operation="subtract", amount=1),
            ],
        )


def test_number_line_span_of_twenty_is_allowed():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=0,
        steps=[
            NumberLineStep(operation="add", amount=20),
            NumberLineStep(operation="subtract", amount=1),
        ],
    )

    assert params.start == 0


def test_single_step_is_allowed():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=6,
        steps=[NumberLineStep(operation="add", amount=3)],
    )

    assert len(params.steps) == 1


@pytest.mark.parametrize("step_count", [0, 4])
def test_step_count_outside_one_to_three_is_rejected(step_count):
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    steps = [NumberLineStep(operation="add", amount=1) for _ in range(step_count)]
    with pytest.raises(ValidationError):
        NumberLineParams(start=2, steps=steps)


def test_single_step_running_total_going_negative_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=2,
            steps=[NumberLineStep(operation="subtract", amount=3)],
        )


def test_single_step_span_over_twenty_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=0,
            steps=[NumberLineStep(operation="add", amount=21)],
        )


@pytest.mark.parametrize("amount", [0, -3])
def test_non_positive_step_amount_is_rejected(amount):
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=10,
            steps=[
                NumberLineStep(operation="add", amount=amount),
                NumberLineStep(operation="subtract", amount=1),
            ],
        )


def test_schema_exposes_step_constraints_to_bedrock():
    from app.templates.number_line.params import NumberLineParams

    schema = NumberLineParams.model_json_schema()

    assert schema["properties"]["steps"]["minItems"] == 1
    assert schema["properties"]["steps"]["maxItems"] == 3
    assert "first operand" in schema["properties"]["start"]["description"]
    assert "source order" in schema["properties"]["steps"]["description"]
    amount_schema = schema["$defs"]["NumberLineStep"]["properties"]["amount"]
    assert amount_schema["exclusiveMinimum"] == 0
