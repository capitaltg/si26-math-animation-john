import pytest
from pydantic import ValidationError

from app.meta.dsl.expression import FieldRefNode, LiteralNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate, RangePredicate, compile_guard
from app.meta.dsl.params import (
    ArrayFieldSpec,
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
