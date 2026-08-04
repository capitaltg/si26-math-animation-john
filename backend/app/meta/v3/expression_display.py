"""Render an answer expression as one line of learner-facing text.

The expression tree is unambiguous; a one-line string is not. So flattening has
to add the parentheses the tree implies -- and only those, since a K-8 lesson
should read like a textbook rather than like a parser's output.
"""

from collections.abc import Mapping
from fractions import Fraction

from app.meta.dsl.expression import _evaluate

_ATOMS = frozenset({"literal", "field_ref"})

#: Higher binds tighter. `fraction` sits above the arithmetic operators because
#: it renders as a ratio with no separating spaces, so it never needs
#: parentheses of its own when it appears as an operand.
_PRECEDENCE = {"add": 1, "subtract": 1, "multiply": 2, "divide": 2, "fraction": 3}

_SYMBOLS = {"add": "+", "subtract": "-", "multiply": "×", "divide": "÷"}

#: Operators for which `a - (b - c)` differs from `a - b - c`. Their RIGHT
#: operand needs parentheses even at equal precedence, which a tier comparison
#: alone cannot detect: both nodes sit in the same tier.
_NON_ASSOCIATIVE = frozenset({"subtract", "divide", "fraction"})


def has_operation(node) -> bool:
    """Whether the expression contains work worth showing.

    A bare field reference or literal has no arithmetic to display, so its
    `work` stage would repeat the value it is about to resolve to.
    """
    return node.node not in _ATOMS


def format_number(value: Fraction) -> str:
    """A terminating decimal when the value has one, else `numerator/denominator`.

    `resolver._format_value` renders any non-integer as a ratio, so substituting
    2.75 into a displayed expression would print "11/4". A fraction terminates
    in base ten exactly when its reduced denominator's only prime factors are 2
    and 5, so test for that rather than rounding and hoping.

    Once that holds, the reduced denominator is `2**twos * 5**fives`, so
    `10**exponent` (with `exponent = max(twos, fives)`) is an exact multiple of
    it. Scaling the numerator by that multiple turns the division into an
    integer with no remainder, so the decimal expansion comes from string
    slicing, not from a rounding step with a precision constant that could be
    too small for a given value -- there is no such constant, at any fixed
    value, for every value this DSL's numerator/denominator limits allow.
    """
    remainder = value.denominator
    twos = fives = 0
    while remainder % 2 == 0:
        remainder //= 2
        twos += 1
    while remainder % 5 == 0:
        remainder //= 5
        fives += 1
    if remainder != 1:
        return f"{value.numerator}/{value.denominator}"

    exponent = max(twos, fives)
    scaled = abs(value.numerator) * (10**exponent // value.denominator)
    digits = str(scaled).zfill(exponent + 1)
    sign = "-" if value.numerator < 0 else ""
    if exponent == 0:
        return f"{sign}{digits}"
    integer_part, fractional_part = digits[:-exponent], digits[-exponent:].rstrip("0")
    if not fractional_part:
        return f"{sign}{integer_part}"
    return f"{sign}{integer_part}.{fractional_part}"


def expression_display(node, values: Mapping[str, object]) -> str:
    return _display(node, values, parent=None, is_right=False)


def _display(node, values, parent, is_right) -> str:
    if node.node in _ATOMS:
        return format_number(_evaluate(node, values))
    if node.node == "fraction":
        numerator, denominator = node.operands
        text = (
            f"{_display(numerator, values, node.node, False)}"
            f"/{_display(denominator, values, node.node, True)}"
        )
    else:
        separator = f" {_SYMBOLS[node.node]} "
        text = separator.join(
            _display(operand, values, node.node, index > 0)
            for index, operand in enumerate(node.operands)
        )
    if _needs_parentheses(node.node, parent, is_right):
        return f"({text})"
    return text


def _needs_parentheses(child, parent, is_right) -> bool:
    if parent is None:
        return False
    if _PRECEDENCE[child] < _PRECEDENCE[parent]:
        return True
    return (
        _PRECEDENCE[child] == _PRECEDENCE[parent]
        and is_right
        and parent in _NON_ASSOCIATIVE
    )
