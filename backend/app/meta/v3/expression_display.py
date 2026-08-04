"""Render an answer expression as one line of learner-facing text.

The expression tree is unambiguous; a one-line string is not. So flattening has
to add the parentheses the tree implies -- and only those, since a K-8 lesson
should read like a textbook rather than like a parser's output.
"""

from collections.abc import Mapping
from decimal import Decimal, localcontext
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

#: Enough digits for any terminating decimal this DSL can produce.
#: `_to_fraction` caps denominators at 10**9, so at most ~30 decimal places.
_DECIMAL_PRECISION = 40


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
    """
    remainder = value.denominator
    for factor in (2, 5):
        while remainder % factor == 0:
            remainder //= factor
    if remainder != 1:
        return f"{value.numerator}/{value.denominator}"
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        return str(Decimal(value.numerator) / Decimal(value.denominator))


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
