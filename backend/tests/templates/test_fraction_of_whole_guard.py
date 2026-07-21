import pytest
from pydantic import ValidationError


def test_valid_proper_fraction_passes():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    params = FractionOfWholeParams(numerator=1, denominator=2)

    assert params.numerator == 1
    assert params.denominator == 2


def test_exact_whole_passes():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    params = FractionOfWholeParams(numerator=4, denominator=4)

    assert params.numerator == 4
    assert params.denominator == 4


def test_improper_fraction_is_rejected():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    with pytest.raises(ValidationError):
        FractionOfWholeParams(numerator=5, denominator=4)


def test_numerator_of_zero_is_rejected():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    with pytest.raises(ValidationError):
        FractionOfWholeParams(numerator=0, denominator=4)


def test_denominator_of_zero_is_rejected():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    with pytest.raises(ValidationError):
        FractionOfWholeParams(numerator=1, denominator=0)


def test_denominator_of_one_is_rejected():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    with pytest.raises(ValidationError):
        FractionOfWholeParams(numerator=1, denominator=1)


def test_denominator_over_twelve_is_rejected():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    with pytest.raises(ValidationError):
        FractionOfWholeParams(numerator=1, denominator=13)


def test_schema_exposes_denominator_bound_to_bedrock():
    from app.templates.fraction_of_whole.params import FractionOfWholeParams

    properties = FractionOfWholeParams.model_json_schema()["properties"]

    assert properties["denominator"]["maximum"] == 12
