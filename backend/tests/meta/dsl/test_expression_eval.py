from fractions import Fraction

import pytest

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import (
    AddNode,
    DivideNode,
    FieldRefNode,
    FractionNode,
    LiteralNode,
    MultiplyNode,
    SubtractNode,
    compile_expression,
)


def test_arithmetic_is_exact_rational():
    node = FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=3)])
    compiled = compile_expression(node, known_fields=frozenset())
    assert compiled.evaluate({}) == Fraction(1, 3)


def test_field_ref_and_array_projection():
    node = AddNode(
        operands=[FieldRefNode(field="terms", index=0), FieldRefNode(field="terms", index=1)]
    )
    compiled = compile_expression(node, known_fields=frozenset({"terms"}))
    assert compiled.evaluate({"terms": [2, 5]}) == Fraction(7)


def test_nested_arithmetic():
    node = MultiplyNode(
        operands=[
            SubtractNode(operands=[LiteralNode(value=10), LiteralNode(value=4)]),
            LiteralNode(value=3),
        ]
    )
    compiled = compile_expression(node, known_fields=frozenset())
    assert compiled.evaluate({}) == Fraction(18)


def test_divide_by_zero_raises_structured_error():
    node = DivideNode(operands=[LiteralNode(value=1), LiteralNode(value=0)])
    compiled = compile_expression(node, known_fields=frozenset())
    with pytest.raises(DslValidationError) as exc:
        compiled.evaluate({})
    assert exc.value.code == "divide_by_zero"


def test_overflow_raises_structured_error():
    node = MultiplyNode(operands=[LiteralNode(value=1e9), LiteralNode(value=1e9)])
    compiled = compile_expression(node, known_fields=frozenset())
    with pytest.raises(DslValidationError) as exc:
        compiled.evaluate({})
    assert exc.value.code == "overflow"


@pytest.mark.parametrize(
    ("node", "values"),
    [
        (LiteralNode(value=1e13), {}),
        (FieldRefNode(field="x"), {"x": 1e13}),
    ],
)
def test_terminal_values_larger_than_the_numeric_limit_are_rejected(node, values):
    compiled = compile_expression(node, known_fields=frozenset({"x"}))
    with pytest.raises(DslValidationError) as exc:
        compiled.evaluate(values)
    assert exc.value.code == "overflow"


def test_non_finite_runtime_value_rejected():
    node = FieldRefNode(field="x")
    compiled = compile_expression(node, known_fields=frozenset({"x"}))
    with pytest.raises(DslValidationError) as exc:
        compiled.evaluate({"x": float("nan")})
    assert exc.value.code == "non_finite_value"
