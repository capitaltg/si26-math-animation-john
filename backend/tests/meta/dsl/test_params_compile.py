import pytest
from pydantic import ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import DivisibleByPredicate, GuardDocument, PositivePredicate, compile_guard
from app.meta.dsl.params import (
    ArrayFieldSpec,
    DecimalFieldSpec,
    EnumFieldSpec,
    IntegerFieldSpec,
    ParamsDocument,
    StringFieldSpec,
    compile_template_params,
)


def _guard_for(*field_names):
    document = GuardDocument(
        guard_version=1,
        predicates=[PositivePredicate(value=FieldRefNode(field=field_names[0]))],
    )
    return compile_guard(document, known_fields=frozenset(field_names))


def test_compiled_model_accepts_valid_params_and_exposes_guard_result():
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="Numerator", description="", minimum=1, maximum=20),
        ],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    instance = Params(numerator=5)
    assert instance.numerator == 5
    assert instance.guard_result().passed is True


def test_compiled_model_rejects_guard_failure():
    document = ParamsDocument(
        params_version=1,
        fields=[IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20)],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": -1})


def test_compiled_model_rejects_unknown_field():
    document = ParamsDocument(
        params_version=1,
        fields=[IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20)],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": 5, "sneaky": "x"})


def test_enum_field_is_closed():
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            EnumFieldSpec(name="shape", label="Shape", description="", choices=["circle", "square"]),
        ],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": 5, "shape": "triangle"})
    assert Params.model_validate({"numerator": 5, "shape": "circle"}).shape == "circle"


def test_array_field_bounds_items_and_forbids_nested_arrays():
    with pytest.raises(ValidationError):
        ArrayFieldSpec(
            name="terms",
            label="Terms",
            description="",
            min_items=1,
            max_items=4,
            item_fields=[{"type": "array", "name": "nested", "label": "x", "description": "", "min_items": 1, "max_items": 2, "item_fields": []}],
        )

    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            ArrayFieldSpec(
                name="terms",
                label="Terms",
                description="",
                min_items=1,
                max_items=3,
                item_fields=[IntegerFieldSpec(name="value", label="V", description="", minimum=0, maximum=99)],
            ),
        ],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    instance = Params.model_validate({"numerator": 5, "terms": [{"value": 1}, {"value": 2}]})
    assert [item.value for item in instance.terms] == [1, 2]
    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": 5, "terms": [{"value": 1}] * 4})


def test_string_field_length_bound():
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            StringFieldSpec(name="label", label="Label", description="", max_length=5),
        ],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": 5, "label": "way too long"})


def test_duplicate_field_names_rejected():
    with pytest.raises(ValidationError):
        ParamsDocument(
            params_version=1,
            fields=[
                IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=5),
                IntegerFieldSpec(name="a", label="A2", description="", minimum=1, maximum=5),
            ],
        )


def test_duplicate_item_field_names_rejected():
    with pytest.raises(ValidationError):
        ArrayFieldSpec(
            name="terms",
            label="Terms",
            description="",
            min_items=1,
            max_items=3,
            item_fields=[
                IntegerFieldSpec(name="value", label="V", description="", minimum=0, maximum=99),
                StringFieldSpec(name="value", label="V2", description="", max_length=5),
            ],
        )


def test_required_scalar_field_rejects_omission():
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
        ],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    assert Params.model_fields["numerator"].is_required() is True
    with pytest.raises(ValidationError):
        Params.model_validate({})


def test_required_array_field_rejects_omission():
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            ArrayFieldSpec(
                name="terms",
                label="Terms",
                description="",
                min_items=1,
                max_items=3,
                item_fields=[IntegerFieldSpec(name="value", label="V", description="", minimum=0, maximum=99)],
            ),
        ],
    )
    Params = compile_template_params(document, _guard_for("numerator"))
    assert Params.model_fields["terms"].is_required() is True
    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": 5})


def test_guard_evaluation_error_surfaces_as_validation_error_not_dsl_error():
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="divisor", label="D", description="", minimum=0, maximum=20),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            DivisibleByPredicate(
                value=FieldRefNode(field="numerator"),
                divisor=FieldRefNode(field="divisor"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"numerator", "divisor"}))
    Params = compile_template_params(document, compiled_guard)

    with pytest.raises(ValidationError):
        Params.model_validate({"numerator": 5, "divisor": 0})

    # Confirm the underlying DslValidationError is not what escapes.
    try:
        Params.model_validate({"numerator": 5, "divisor": 0})
    except ValidationError:
        pass
    except DslValidationError:
        pytest.fail("DslValidationError escaped model_validate instead of ValidationError")


def test_array_field_spec_rejects_min_items_greater_than_max_items():
    with pytest.raises(ValidationError):
        ArrayFieldSpec(
            name="terms",
            label="Terms",
            description="",
            min_items=5,
            max_items=2,
            item_fields=[IntegerFieldSpec(name="value", label="V", description="", minimum=0, maximum=99)],
        )


def test_integer_field_spec_rejects_minimum_greater_than_maximum():
    with pytest.raises(ValidationError):
        IntegerFieldSpec(name="a", label="A", description="", minimum=10, maximum=1)


def test_decimal_field_spec_rejects_minimum_greater_than_maximum():
    with pytest.raises(ValidationError):
        DecimalFieldSpec(name="a", label="A", description="", minimum=10.0, maximum=1.0)


def test_integer_field_spec_rejects_default_outside_bounds():
    with pytest.raises(ValidationError):
        IntegerFieldSpec(
            name="count", label="Count", description="", required=False, default=9999, minimum=1, maximum=10
        )


def test_decimal_field_spec_rejects_default_outside_bounds():
    with pytest.raises(ValidationError):
        DecimalFieldSpec(
            name="ratio", label="Ratio", description="", required=False, default=99.9, minimum=0.0, maximum=1.0
        )


def test_string_field_spec_rejects_default_longer_than_max_length():
    with pytest.raises(ValidationError):
        StringFieldSpec(
            name="label",
            label="Label",
            description="",
            required=False,
            default="way too long for five chars",
            max_length=5,
        )


def test_enum_field_spec_rejects_default_not_in_choices():
    with pytest.raises(ValidationError):
        EnumFieldSpec(
            name="shape",
            label="Shape",
            description="",
            required=False,
            default="triangle",
            choices=["circle", "square"],
        )


def test_array_field_spec_rejects_optional_with_min_items_positive():
    with pytest.raises(ValidationError):
        ArrayFieldSpec(
            name="terms",
            label="Terms",
            description="",
            required=False,
            min_items=1,
            max_items=3,
            item_fields=[IntegerFieldSpec(name="value", label="V", description="", minimum=0, maximum=99)],
        )
