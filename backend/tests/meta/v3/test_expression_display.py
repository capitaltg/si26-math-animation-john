from fractions import Fraction

import pytest

from app.meta.dsl.expression import (
    AddNode, DivideNode, FieldRefNode, FractionNode, LiteralNode,
    MultiplyNode, SubtractNode,
)
from app.meta.v3.expression_display import (
    expression_display, format_number, has_operation,
)


def _literal(value):
    return LiteralNode(value=value)


def _field(name):
    return FieldRefNode(field=name)


@pytest.mark.parametrize(
    "value,expected",
    [
        (Fraction(2750), "2750"),
        (Fraction(11, 4), "2.75"),
        (Fraction(0), "0"),
        (Fraction(-7, 2), "-3.5"),
        (Fraction(1, 8), "0.125"),
        # A denominator with a prime factor other than 2 or 5 has no terminating
        # decimal, so it stays a fraction rather than being silently rounded.
        (Fraction(1, 3), "1/3"),
        (Fraction(2, 7), "2/7"),
    ],
)
def test_format_number_prefers_a_terminating_decimal(value, expected):
    assert format_number(value) == expected


def test_a_field_reference_shows_its_value_as_a_decimal():
    # `resolver._format_value` would render this Fraction as "11/4"; a lesson
    # about 2.75 kilometres has to say 2.75.
    node = _field("distance_km")
    assert expression_display(node, {"distance_km": Fraction(11, 4)}) == "2.75"


def test_the_kilometers_conversion_reads_as_one_multiplication():
    node = MultiplyNode(operands=[_field("distance_km"), _literal(1000)])
    values = {"distance_km": Fraction(11, 4)}
    assert expression_display(node, values) == "2.75 × 1000"


def test_a_looser_child_is_parenthesised():
    # "2 + 3 × 4" would evaluate to 14; the tree means 20.
    node = MultiplyNode(operands=[AddNode(operands=[_literal(2), _literal(3)]), _literal(4)])
    assert expression_display(node, {}) == "(2 + 3) × 4"


def test_a_tighter_child_needs_no_parentheses():
    node = AddNode(operands=[MultiplyNode(operands=[_literal(2), _literal(3)]), _literal(4)])
    assert expression_display(node, {}) == "2 × 3 + 4"


def test_the_right_operand_of_a_nested_subtraction_is_parenthesised():
    # Equal precedence, so a tier comparison alone would omit these parentheses
    # and turn 7 into 3.
    node = SubtractNode(operands=[_literal(10), SubtractNode(operands=[_literal(5), _literal(2)])])
    assert expression_display(node, {}) == "10 - (5 - 2)"


def test_the_right_operand_of_a_nested_division_is_parenthesised():
    node = DivideNode(operands=[_literal(100), DivideNode(operands=[_literal(10), _literal(2)])])
    assert expression_display(node, {}) == "100 ÷ (10 ÷ 2)"


def test_the_left_operand_of_a_nested_subtraction_needs_no_parentheses():
    node = SubtractNode(operands=[SubtractNode(operands=[_literal(10), _literal(5)]), _literal(2)])
    assert expression_display(node, {}) == "10 - 5 - 2"


def test_a_fraction_renders_as_a_ratio():
    node = FractionNode(operands=[_literal(1), _literal(3)])
    assert expression_display(node, {}) == "1/3"


def test_a_nested_fraction_denominator_is_parenthesised():
    node = FractionNode(operands=[
        _literal(1), FractionNode(operands=[_literal(2), _literal(3)]),
    ])
    assert expression_display(node, {}) == "1/(2/3)"


def test_a_four_operand_sum_joins_every_operand():
    node = AddNode(operands=[_literal(1), _literal(2), _literal(3), _literal(4)])
    assert expression_display(node, {}) == "1 + 2 + 3 + 4"


@pytest.mark.parametrize(
    "node,expected",
    [
        (LiteralNode(value=5), False),
        (FieldRefNode(field="distance_km"), False),
        (MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)]), True),
        (FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=3)]), True),
    ],
)
def test_has_operation_reports_whether_there_is_work_to_show(node, expected):
    assert has_operation(node) is expected
