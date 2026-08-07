import pytest

from app.templates._shared.chain_math import (
    format_operation_caption,
    run_additive_chain,
    run_multiplicative_chain,
)


def test_run_additive_chain_applies_add_and_subtract_in_order():
    assert run_additive_chain(1, [("add", 2), ("subtract", 1)]) == [1, 3, 2]


def test_run_additive_chain_with_no_ops_returns_just_the_start():
    assert run_additive_chain(5, []) == [5]


def test_run_multiplicative_chain_applies_multiply_and_exact_divide():
    assert run_multiplicative_chain(4, [("multiply", 6), ("divide", 3)]) == [4, 24, 8]


def test_run_multiplicative_chain_rejects_non_exact_division():
    with pytest.raises(ValueError):
        run_multiplicative_chain(10, [("divide", 3)])


def test_run_multiplicative_chain_rejects_zero_divisor():
    with pytest.raises(
        ValueError,
        match=r"^Division by zero: 10 / 0 is not a whole number$",
    ):
        run_multiplicative_chain(10, [("divide", 0)])


def test_run_multiplicative_chain_rejects_non_positive_start():
    with pytest.raises(ValueError):
        run_multiplicative_chain(0, [("multiply", 5)])


def test_format_operation_caption_with_ints():
    assert format_operation_caption(17, "add", 4, 21) == "17 + 4 = 21"


def test_format_operation_caption_with_fraction_strings():
    assert format_operation_caption("3/8", "add", "2/8", "5/8") == "3/8 + 2/8 = 5/8"


def test_format_operation_caption_uses_multiplication_and_division_symbols():
    assert format_operation_caption(24, "divide", 3, 8) == "24 ÷ 3 = 8"
    assert format_operation_caption(4, "multiply", 6, 24) == "4 × 6 = 24"


