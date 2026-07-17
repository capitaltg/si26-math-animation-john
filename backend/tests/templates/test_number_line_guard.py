import pytest
from pydantic import ValidationError


def test_valid_steps_pass_the_guard():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(start=4, steps=[NumberLineStep(operation="add", amount=3)])
    assert params.start == 4


def test_running_total_going_negative_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(start=2, steps=[NumberLineStep(operation="subtract", amount=5)])
