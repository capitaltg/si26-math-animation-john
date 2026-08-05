import pytest
from pydantic import ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode, FractionNode, LiteralNode
from app.meta.dsl.guard import DivisibleByPredicate, GuardDocument, PositivePredicate, compile_guard
from app.meta.dsl.params import (
    ArrayFieldSpec,
    DecimalFieldSpec,
    EnumFieldSpec,
    IntegerFieldSpec,
    ParamsDocument,
    StringFieldSpec,
    compile_template_params,
    field_contract_for,
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


def test_decimal_field_spec_rejects_nan_minimum():
    with pytest.raises(ValidationError):
        DecimalFieldSpec(
            name="ratio", label="Ratio", description="", minimum=float("nan"), maximum=1.0,
        )


def test_decimal_field_spec_rejects_infinite_maximum():
    with pytest.raises(ValidationError):
        DecimalFieldSpec(
            name="ratio", label="Ratio", description="", minimum=0.0, maximum=float("inf"),
        )


def test_decimal_field_spec_rejects_infinite_default():
    with pytest.raises(ValidationError):
        DecimalFieldSpec(
            name="ratio", label="Ratio", description="",
            required=False, default=float("-inf"), minimum=0.0, maximum=1.0,
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


def test_grounding_number_tokens_includes_a_field_ref_fraction_pair():
    from app.meta.dsl.guard import GuardDocument, RangePredicate
    from app.meta.dsl.expression import LiteralNode

    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="Numerator", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="denominator", label="Denominator", description="", minimum=1, maximum=20),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            RangePredicate(
                value=FractionNode(
                    operands=[FieldRefNode(field="numerator"), FieldRefNode(field="denominator")]
                ),
                minimum=LiteralNode(value=0),
                maximum=LiteralNode(value=1),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"numerator", "denominator"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(numerator=3, denominator=4)
    tokens = params.grounding_number_tokens()

    assert "3/4" in tokens
    assert "3" in tokens
    assert "4" in tokens


def test_grounding_derived_totals_covers_sum_equals_predicates():
    from app.meta.dsl.guard import GuardDocument, SumEqualsPredicate

    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="b", label="B", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="total", label="Total", description="", minimum=1, maximum=40),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
                total=FieldRefNode(field="total"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"a", "b", "total"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=3, b=4, total=7)
    totals = params.grounding_derived_totals()

    assert totals == [("7", ["3", "4"])]


def test_grounding_derived_totals_covers_product_equals_predicates():
    from app.meta.dsl.guard import GuardDocument, ProductEqualsPredicate

    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="b", label="B", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="total", label="Total", description="", minimum=1, maximum=400),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            ProductEqualsPredicate(
                factors=[FieldRefNode(field="a"), FieldRefNode(field="b")],
                total=FieldRefNode(field="total"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"a", "b", "total"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=3, b=4, total=12)
    totals = params.grounding_derived_totals()

    assert totals == [("12", ["3", "4"], "product")]


def test_grounding_derived_totals_skips_predicates_with_compound_total():
    from app.meta.dsl.guard import GuardDocument, SumEqualsPredicate

    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="b", label="B", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="denominator", label="D", description="", minimum=1, maximum=20),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
                total=FractionNode(
                    operands=[FieldRefNode(field="numerator"), FieldRefNode(field="denominator")]
                ),
            ),
        ],
    )
    compiled_guard = compile_guard(
        guard_document, known_fields=frozenset({"a", "b", "numerator", "denominator"})
    )
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=3, b=4, numerator=14, denominator=2)
    totals = params.grounding_derived_totals()

    assert totals == []


def test_grounding_derived_totals_formats_decimal_total_like_default_number_tokens():
    from app.meta.dsl.guard import GuardDocument, SumEqualsPredicate

    document = ParamsDocument(
        params_version=1,
        fields=[
            DecimalFieldSpec(name="a", label="A", description="", minimum=0.0, maximum=20.0),
            IntegerFieldSpec(name="b", label="B", description="", minimum=0, maximum=20),
            DecimalFieldSpec(name="total", label="Total", description="", minimum=0.0, maximum=50.0),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
                total=FieldRefNode(field="total"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"a", "b", "total"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=3.5, b=4, total=7.5)
    totals = params.grounding_derived_totals()

    # Must match how default_number_tokens (str(value)) would stringify these
    # same field values -- not the bare-fraction "15/2" / "7/2" form.
    assert totals == [("7.5", ["3.5", "4"])]


def test_grounding_derived_totals_formats_whole_number_decimal_total_with_trailing_zero():
    from app.meta.dsl.guard import GuardDocument, SumEqualsPredicate

    document = ParamsDocument(
        params_version=1,
        fields=[
            DecimalFieldSpec(name="a", label="A", description="", minimum=0.0, maximum=20.0),
            DecimalFieldSpec(name="b", label="B", description="", minimum=0.0, maximum=20.0),
            DecimalFieldSpec(name="total", label="Total", description="", minimum=0.0, maximum=50.0),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
                total=FieldRefNode(field="total"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"a", "b", "total"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=3.0, b=4.0, total=7.0)
    totals = params.grounding_derived_totals()

    # default_number_tokens would render the decimal "total" field as "7.0"
    # (str(7.0)), not the fraction formatter's "7" -- must agree with that.
    assert totals == [("7.0", ["3.0", "4.0"])]


def test_grounding_derived_totals_accepts_decimal_and_fraction_spellings_for_literal_terms():
    from app.meta.dsl.guard import GuardDocument, SumEqualsPredicate

    document = ParamsDocument(
        params_version=1,
        fields=[
            DecimalFieldSpec(name="a", label="A", description="", minimum=0.0, maximum=20.0),
            DecimalFieldSpec(name="total", label="Total", description="", minimum=0.0, maximum=50.0),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), LiteralNode(value=2.5)],
                total=FieldRefNode(field="total"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"a", "total"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=5.0, total=7.5)
    totals = params.grounding_derived_totals()

    assert totals == [
        ("7.5", ["5.0", "2.5"]),
        ("7.5", ["5.0", "5/2"]),
    ]


def test_grounding_derived_total_accepts_fraction_spelling_for_decimal_literal():
    from app.meta.dsl.guard import GuardDocument, SumEqualsPredicate
    from app.pipeline.grounding import check_params_grounded

    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="a", label="A", description="", minimum=0, maximum=20),
            DecimalFieldSpec(name="total", label="Total", description="", minimum=0.0, maximum=50.0),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), LiteralNode(value=0.5)],
                total=FieldRefNode(field="total"),
            ),
        ],
    )
    compiled_guard = compile_guard(guard_document, known_fields=frozenset({"a", "total"}))
    Params = compile_template_params(document, compiled_guard)

    params = Params(a=1, total=1.5)

    assert check_params_grounded(params, "Add 1 and 1/2.") == []


def test_grounding_number_tokens_falls_back_to_default_stringification_without_fraction_predicates():
    Params = compile_template_params(
        ParamsDocument(
            params_version=1,
            fields=[
                IntegerFieldSpec(name="rows", label="Rows", description="", minimum=1, maximum=20),
            ],
        ),
        _guard_for("rows"),
    )
    params = Params(rows=5)
    assert params.grounding_number_tokens() == ["5"]


def test_a_guard_predicate_can_read_a_scalar_inside_an_array_item():
    """An array field must be usable by the guard, not merely declarable.

    `ArrayFieldSpec.item_fields` makes each element an object, so `model_dump()`
    hands the guard a list of dicts. Before `item_field` addressing existed, the
    only way to reference one was `scores[0]` -- the dict itself -- which
    `_to_fraction` rejected with `unsupported_type: <class 'dict'>` at validation
    time, reported to an operator as a fixture that "expected accept, got reject".
    """
    params = ParamsDocument(params_version=1, fields=[
        ArrayFieldSpec(
            name="scores", label="Scores", description="",
            min_items=2, max_items=7,
            item_fields=[IntegerFieldSpec(
                name="value", label="V", description="", minimum=0, maximum=100,
            )],
        ),
    ])
    guard = GuardDocument(predicates=[
        {"predicate": "positive",
         "value": {"node": "field_ref", "field": "scores", "index": 0,
                   "item_field": "value"}},
    ])
    contract = field_contract_for(params)
    params_cls = compile_template_params(params, compile_guard(guard, contract))

    accepted = params_cls(scores=[{"value": 5}, {"value": 9}])

    assert accepted.guard_result().passed is True
    with pytest.raises(ValidationError, match="guard predicate failed"):
        params_cls(scores=[{"value": 0}, {"value": 9}])


def test_a_guard_predicate_naming_an_array_without_an_item_field_fails_to_compile():
    params = ParamsDocument(params_version=1, fields=[
        ArrayFieldSpec(
            name="scores", label="Scores", description="",
            min_items=2, max_items=7,
            item_fields=[IntegerFieldSpec(
                name="value", label="V", description="", minimum=0, maximum=100,
            )],
        ),
    ])
    guard = GuardDocument(predicates=[
        {"predicate": "positive",
         "value": {"node": "field_ref", "field": "scores", "index": 0}},
    ])

    with pytest.raises(DslValidationError) as exc_info:
        compile_guard(guard, field_contract_for(params))

    assert exc_info.value.code == "array_item_field_required"
    assert "value" in str(exc_info.value)


def test_compiled_schema_carries_each_field_description():
    """The extraction model is told what a field holds, not just its name.

    A params document's `description` is the only thing that says what belongs in
    a field -- `object_name` alone reads as "some object" and the model guessed at
    it, declining a problem it could have extracted. Auto-derived titles do not
    carry that; the description has to reach the JSON schema.
    """
    document = ParamsDocument(
        params_version=1,
        fields=[
            DecimalFieldSpec(
                name="distance_km", label="Distance in kilometers",
                description="The length of the hiking trail in kilometers",
                minimum=0.1, maximum=9.99,
            ),
            StringFieldSpec(
                name="object_name", label="Object name",
                description="The name of the object being measured",
                max_length=60,
            ),
        ],
    )
    schema = compile_template_params(document, _guard_for("distance_km")).model_json_schema()

    assert schema["properties"]["distance_km"]["description"] == (
        "The length of the hiking trail in kilometers"
    )
    assert schema["properties"]["object_name"]["description"] == (
        "The name of the object being measured"
    )


def test_compiled_schema_carries_descriptions_for_array_item_fields():
    document = ParamsDocument(
        params_version=1,
        fields=[
            ArrayFieldSpec(
                name="rows", label="Rows", description="One row per measurement",
                min_items=1, max_items=4,
                item_fields=[
                    IntegerFieldSpec(
                        name="count", label="Count",
                        description="How many objects this row holds",
                        minimum=1, maximum=20,
                    ),
                ],
            ),
        ],
    )
    schema = compile_template_params(document, _guard_for("rows")).model_json_schema()

    assert schema["properties"]["rows"]["description"] == "One row per measurement"
    item_schema = schema["$defs"]["_rows_Item"]
    assert item_schema["properties"]["count"]["description"] == (
        "How many objects this row holds"
    )


def test_field_contract_omits_scalar_minimum_for_optional_numeric_fields():
    """An optional numeric field's schema accepts None, so exposing its
    `minimum` as a scalar guarantee would let a caller trust `minimum >= 1`
    and then crash when the accepted null value flows through expression
    evaluation (`unsupported_type: NoneType`). Only required fields carry
    the guarantee; optional ones must be reported as minimum-unknown."""
    document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(
                name="required_count", label="Count", description="",
                minimum=1, maximum=10, required=True,
            ),
            DecimalFieldSpec(
                name="optional_rate", label="Rate", description="",
                minimum=1.0, maximum=5.0, required=False, default=None,
            ),
        ],
    )

    contract = field_contract_for(document)

    assert "required_count" in contract.scalar_minimums
    assert "optional_rate" not in contract.scalar_minimums
