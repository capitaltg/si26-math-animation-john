from fractions import Fraction

import pytest

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode, LiteralNode
from app.meta.dsl.guard import (
    GuardDocument,
    PositivePredicate,
    ProductEqualsPredicate,
    RangePredicate,
    SumEqualsPredicate,
    compile_guard,
    derive_literal_operands,
    derive_permitted_derived_totals,
)


def _document(*predicates):
    return GuardDocument(guard_version=1, predicates=list(predicates))


def test_check_passes_when_all_predicates_hold():
    document = _document(
        PositivePredicate(value=FieldRefNode(field="a")),
        RangePredicate(
            value=FieldRefNode(field="a"), minimum=LiteralNode(value=1), maximum=LiteralNode(value=10)
        ),
    )
    compiled = compile_guard(document, known_fields=frozenset({"a"}))
    result = compiled.check({"a": 5})
    assert result.passed is True
    assert all(r.passed for r in result.predicate_results)


def test_check_reports_which_predicate_failed():
    document = _document(PositivePredicate(value=FieldRefNode(field="a")))
    compiled = compile_guard(document, known_fields=frozenset({"a"}))
    result = compiled.check({"a": -3})
    assert result.passed is False
    assert result.predicate_results[0].passed is False
    assert result.predicate_results[0].predicate_type == "positive"


def test_sum_equals_and_product_equals_evaluate_correctly():
    document = _document(
        SumEqualsPredicate(
            terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
            total=FieldRefNode(field="total"),
        ),
        ProductEqualsPredicate(
            factors=[FieldRefNode(field="a"), FieldRefNode(field="b")],
            total=LiteralNode(value=12),
        ),
    )
    compiled = compile_guard(document, known_fields=frozenset({"a", "b", "total"}))
    result = compiled.check({"a": 3, "b": 4, "total": 7})
    assert result.passed is True


def test_divisible_by_zero_divisor_raises_structured_error():
    from app.meta.dsl.guard import DivisibleByPredicate

    document = _document(
        DivisibleByPredicate(value=FieldRefNode(field="a"), divisor=LiteralNode(value=0))
    )
    compiled = compile_guard(document, known_fields=frozenset({"a"}))
    with pytest.raises(DslValidationError) as exc:
        compiled.check({"a": 10})
    assert exc.value.code == "divide_by_zero"


def test_ordered_predicate_directions():
    from app.meta.dsl.guard import OrderedPredicate

    document = _document(
        OrderedPredicate(
            terms=[FieldRefNode(field="a", index=0), FieldRefNode(field="a", index=1), FieldRefNode(field="a", index=2)],
            direction="strictly_increasing",
        )
    )
    compiled = compile_guard(document, known_fields=frozenset({"a"}))
    assert compiled.check({"a": [1, 2, 3]}).passed is True
    assert compiled.check({"a": [1, 1, 3]}).passed is False


def test_derive_literal_operands_collects_every_literal():
    document = _document(
        RangePredicate(
            value=FieldRefNode(field="a"), minimum=LiteralNode(value=1), maximum=LiteralNode(value=20)
        ),
        SumEqualsPredicate(
            terms=[FieldRefNode(field="a"), LiteralNode(value=5)], total=LiteralNode(value=20)
        ),
    )
    literals = derive_literal_operands(document)
    assert literals == {Fraction(1), Fraction(20), Fraction(5)}


def test_derive_permitted_derived_totals_evaluates_totals_against_values():
    document = _document(
        SumEqualsPredicate(
            terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
            total=FieldRefNode(field="total"),
        )
    )
    totals = derive_permitted_derived_totals(document, {"a": 3, "b": 4, "total": 7})
    assert totals == {Fraction(7)}
