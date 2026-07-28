import pytest
from pydantic import ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode, LiteralNode
from app.meta.dsl.guard import (
    GuardDocument,
    OrderedPredicate,
    PositivePredicate,
    RangePredicate,
    SumEqualsPredicate,
    compile_guard,
)


def test_valid_guard_document_compiles():
    document = GuardDocument(
        guard_version=1,
        predicates=[
            PositivePredicate(value=FieldRefNode(field="a")),
            RangePredicate(
                value=FieldRefNode(field="a"),
                minimum=LiteralNode(value=1),
                maximum=LiteralNode(value=20),
            ),
        ],
    )
    compiled = compile_guard(document, known_fields=frozenset({"a"}))
    assert compiled.document is document


def test_unknown_field_in_predicate_rejected():
    document = GuardDocument(
        guard_version=1,
        predicates=[PositivePredicate(value=FieldRefNode(field="ghost"))],
    )
    with pytest.raises(DslValidationError) as exc:
        compile_guard(document, known_fields=frozenset({"a"}))
    assert exc.value.code == "unknown_field"


def test_sum_equals_term_bounds_enforced():
    with pytest.raises(ValidationError):
        SumEqualsPredicate(terms=[LiteralNode(value=1)], total=LiteralNode(value=1))


def test_ordered_direction_is_closed_enum():
    with pytest.raises(ValidationError):
        OrderedPredicate(
            terms=[LiteralNode(value=1), LiteralNode(value=2)], direction="sideways"
        )


def test_predicate_count_limit_enforced():
    with pytest.raises(ValidationError):
        GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=LiteralNode(value=1))] * 25,
        )


def test_unknown_predicate_key_rejected():
    with pytest.raises(ValidationError):
        PositivePredicate.model_validate({"predicate": "positive", "value": {"node": "literal", "value": 1}, "sneaky": True})
