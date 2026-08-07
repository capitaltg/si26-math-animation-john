from fractions import Fraction

from app.templates.array_grid.params import (
    ArrayGridParams,
    ArrayGridStep,
    ChainedArrayGridParams,
)
from app.templates.balance_scale.params import (
    BalanceScaleParams,
    ChainedBalanceScaleParams,
)
from app.templates.fraction_bar.params import (
    ChainedFractionBarParams,
    FractionBarParams,
    FractionStep,
)
from app.templates.fraction_of_whole.params import (
    ChainedFractionOfWholeParams,
    FractionOfWholeParams,
)
from app.templates.number_line.params import (
    ChainedNumberLineParams,
    NumberLineParams,
    NumberLineStep,
)
from app.templates.text_card.params import TextCardParams


def test_number_line_add_only():
    params = NumberLineParams(
        start=3, steps=[NumberLineStep(operation="add", amount=5)]
    )
    assert params.compute_answer() == Fraction(8)


def test_number_line_mixed_ops():
    params = NumberLineParams(
        start=10,
        steps=[
            NumberLineStep(operation="add", amount=2),
            NumberLineStep(operation="subtract", amount=5),
        ],
    )
    assert params.compute_answer() == Fraction(7)


def test_chained_number_line_uses_last_item():
    a = NumberLineParams(start=1, steps=[NumberLineStep(operation="add", amount=1)])
    b = NumberLineParams(start=5, steps=[NumberLineStep(operation="add", amount=3)])
    chained = ChainedNumberLineParams(items=[a, b])
    assert chained.compute_answer() == Fraction(8)


def test_array_grid_static():
    params = ArrayGridParams(rows=3, cols=4)
    assert params.compute_answer() == Fraction(12)


def test_array_grid_chain_multiply():
    params = ArrayGridParams(
        start=6, steps=[ArrayGridStep(operation="multiply", factor=2)]
    )
    assert params.compute_answer() == Fraction(12)


def test_chained_array_grid_uses_last():
    a = ArrayGridParams(rows=2, cols=2)
    b = ArrayGridParams(rows=3, cols=3)
    chained = ChainedArrayGridParams(items=[a, b])
    assert chained.compute_answer() == Fraction(9)


def test_fraction_bar_add():
    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=1),
            FractionStep(operation="add", numerator=1),
        ],
    )
    assert params.compute_answer() == Fraction(3, 4)


def test_fraction_bar_subtract_reduces():
    params = FractionBarParams(
        denominator=6,
        start_numerator=5,
        steps=[
            FractionStep(operation="subtract", numerator=1),
            FractionStep(operation="subtract", numerator=1),
        ],
    )
    assert params.compute_answer() == Fraction(1, 2)


def test_chained_fraction_bar_uses_last():
    a = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=1),
            FractionStep(operation="add", numerator=1),
        ],
    )
    b = FractionBarParams(
        denominator=8,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=1),
            FractionStep(operation="add", numerator=1),
        ],
    )
    chained = ChainedFractionBarParams(items=[a, b])
    assert chained.compute_answer() == Fraction(3, 8)


def test_balance_scale():
    params = BalanceScaleParams(left_terms=[3, 5], right_total=8)
    assert params.compute_answer() == Fraction(8)


def test_chained_balance_scale_uses_last():
    a = BalanceScaleParams(left_terms=[1, 2], right_total=3)
    b = BalanceScaleParams(left_terms=[4, 5], right_total=9)
    chained = ChainedBalanceScaleParams(items=[a, b])
    assert chained.compute_answer() == Fraction(9)


def test_fraction_of_whole_returns_none():
    params = FractionOfWholeParams(numerator=1, denominator=4)
    assert params.compute_answer() is None


def test_chained_fraction_of_whole_returns_none():
    a = FractionOfWholeParams(numerator=1, denominator=4)
    b = FractionOfWholeParams(numerator=1, denominator=2)
    chained = ChainedFractionOfWholeParams(items=[a, b])
    assert chained.compute_answer() is None


def test_text_card_returns_none():
    params = TextCardParams(headline="Hi", lines=["Hello"])
    assert params.compute_answer() is None
