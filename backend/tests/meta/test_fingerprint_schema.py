import pytest
from pydantic import ValidationError

from app.meta.fingerprint import Fingerprint, canonical_fingerprint_key


def _fp(**overrides):
    base = dict(
        fingerprint_version=1,
        operation_family="compose",
        representation_family="bar",
        number_domain="fraction",
        operand_arity=2,
        step_count=1,
        grade_band="3-5",
    )
    base.update(overrides)
    return Fingerprint(**base)


def test_canonical_key_is_fixed_order_and_stable():
    key = canonical_fingerprint_key(_fp())
    assert key == (
        "fingerprint_version=1|operation_family=compose|representation_family=bar|"
        "number_domain=fraction|operand_arity=2|step_count=1|grade_band=3-5"
    )
    # Same fields, different dict insertion order → identical key.
    reordered = Fingerprint.model_validate(
        {
            "grade_band": "3-5",
            "step_count": 1,
            "operand_arity": 2,
            "number_domain": "fraction",
            "representation_family": "bar",
            "operation_family": "compose",
            "fingerprint_version": 1,
        }
    )
    assert canonical_fingerprint_key(reordered) == key


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Fingerprint.model_validate({**_fp().model_dump(), "extra": "nope"})


def test_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        _fp(operand_arity=0)
    with pytest.raises(ValidationError):
        _fp(step_count=99)
    with pytest.raises(ValidationError):
        _fp(operation_family="teleport")
