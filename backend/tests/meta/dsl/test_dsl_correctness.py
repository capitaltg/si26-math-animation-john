from fractions import Fraction

import pytest

from app.meta.dsl.expression import (
    AddNode, DivideNode, FieldRefNode, FractionNode, LiteralNode, MultiplyNode, SubtractNode,
    compile_expression,
)
from app.meta.dsl.guard import (
    DivisibleByPredicate, EqualsPredicate, GuardDocument, NotEqualsPredicate, OrderedPredicate,
    PositivePredicate, ProductEqualsPredicate, RangePredicate, SumEqualsPredicate, compile_guard,
)


@pytest.mark.parametrize(
    "node,values,expected",
    [
        (AddNode(operands=[LiteralNode(value=2), LiteralNode(value=3)]), {}, Fraction(5)),
        (SubtractNode(operands=[LiteralNode(value=2), LiteralNode(value=3)]), {}, Fraction(-1)),
        (MultiplyNode(operands=[LiteralNode(value=4), LiteralNode(value=0)]), {}, Fraction(0)),
        (DivideNode(operands=[LiteralNode(value=1), LiteralNode(value=4)]), {}, Fraction(1, 4)),
        (FractionNode(operands=[LiteralNode(value=3), LiteralNode(value=4)]), {}, Fraction(3, 4)),
    ],
)
def test_arithmetic_boundary_values(node, values, expected):
    compiled = compile_expression(node, known_fields=frozenset())
    assert compiled.evaluate(values) == expected


@pytest.mark.parametrize(
    "predicate,values,expected",
    [
        (PositivePredicate(value=FieldRefNode(field="a")), {"a": 1}, True),
        (PositivePredicate(value=FieldRefNode(field="a")), {"a": 0}, False),
        (PositivePredicate(value=FieldRefNode(field="a")), {"a": -1}, False),
        (RangePredicate(value=FieldRefNode(field="a"), minimum=LiteralNode(value=1), maximum=LiteralNode(value=5)), {"a": 1}, True),
        (RangePredicate(value=FieldRefNode(field="a"), minimum=LiteralNode(value=1), maximum=LiteralNode(value=5)), {"a": 5}, True),
        (RangePredicate(value=FieldRefNode(field="a"), minimum=LiteralNode(value=1), maximum=LiteralNode(value=5)), {"a": 6}, False),
        (EqualsPredicate(left=FieldRefNode(field="a"), right=LiteralNode(value=4)), {"a": 4}, True),
        (NotEqualsPredicate(left=FieldRefNode(field="a"), right=LiteralNode(value=4)), {"a": 4}, False),
        (DivisibleByPredicate(value=FieldRefNode(field="a"), divisor=LiteralNode(value=3)), {"a": 9}, True),
        (DivisibleByPredicate(value=FieldRefNode(field="a"), divisor=LiteralNode(value=3)), {"a": 10}, False),
        (SumEqualsPredicate(terms=[FieldRefNode(field="a"), FieldRefNode(field="b")], total=LiteralNode(value=10)), {"a": 4, "b": 6}, True),
        (SumEqualsPredicate(terms=[FieldRefNode(field="a"), FieldRefNode(field="b")], total=LiteralNode(value=10)), {"a": 4, "b": 5}, False),
        (ProductEqualsPredicate(factors=[FieldRefNode(field="a"), FieldRefNode(field="b")], total=LiteralNode(value=12)), {"a": 3, "b": 4}, True),
        (ProductEqualsPredicate(factors=[FieldRefNode(field="a"), FieldRefNode(field="b")], total=LiteralNode(value=12)), {"a": 3, "b": 5}, False),
        (OrderedPredicate(terms=[FieldRefNode(field="a", index=0), FieldRefNode(field="a", index=1)], direction="strictly_increasing"), {"a": [1, 2]}, True),
        (OrderedPredicate(terms=[FieldRefNode(field="a", index=0), FieldRefNode(field="a", index=1)], direction="strictly_increasing"), {"a": [2, 2]}, False),
        (OrderedPredicate(terms=[FieldRefNode(field="a", index=0), FieldRefNode(field="a", index=1)], direction="non_decreasing"), {"a": [2, 2]}, True),
    ],
)
def test_every_predicate_positive_negative_and_boundary(predicate, values, expected):
    document = GuardDocument(guard_version=1, predicates=[predicate])
    fields = {"a", "b"} & (set(values.keys()))
    compiled = compile_guard(document, known_fields=frozenset(fields))
    assert compiled.check(values).passed is expected


def test_self_consistent_but_mathematically_wrong_guard_fails_independent_check():
    # This guard is internally self-consistent: 2 + 2 really does equal the literal
    # the author (Bedrock, in Phase 3) wrote as the "total". The compiler has no way
    # to know the *intended* mathematics is "2 + 3 = 5" for the source problem it was
    # generated from — it only proves the predicate holds for the value asserted.
    wrong_guard = GuardDocument(
        guard_version=1,
        predicates=[
            SumEqualsPredicate(
                terms=[FieldRefNode(field="a"), FieldRefNode(field="b")],
                total=LiteralNode(value=4),  # should be 5 for a=2, b=3
            )
        ],
    )
    compiled = compile_guard(wrong_guard, known_fields=frozenset({"a", "b"}))

    # The self-consistent (but wrong) fixture the guard was written to accept:
    assert compiled.check({"a": 2, "b": 2}).passed is True

    # An independently computed expected result for the *actual* source problem
    # ("2 + 3") does not match what this guard accepts — this is exactly the check
    # spec §5 requires a human reviewer to perform in Phase 3; the compiler's job
    # (proven here) ends at "predicates are internally consistent," not "predicates
    # describe the intended mathematics."
    independently_expected_sum = 2 + 3
    assert compiled.check({"a": 2, "b": 3}).passed is False
    assert independently_expected_sum != 4
