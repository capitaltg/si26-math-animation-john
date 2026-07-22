import pytest


@pytest.mark.parametrize(
    ("text", "expected_present"),
    [
        ("(2.4) · (1.3)", ["2.4", "1.3"]),
        ("1/2, 3/6, 4/8, 2/4", ["1/2", "3/6", "4/8", "2/4"]),
        ("Sarah has 12 apples", ["12"]),
    ],
    ids=["decimals-atomic", "fractions-atomic", "integer-atomic"],
)
def test_tokenize_keeps_numbers_atomic(text, expected_present):
    from app.pipeline.grounding import tokenize_for_grounding

    tokens = tokenize_for_grounding(text)
    for token in expected_present:
        assert token in tokens
    # A decimal is never split into its digits or its dot.
    assert "2" not in tokenize_for_grounding("2.4")


def test_curly_quotes_and_apostrophes_normalized():
    from app.pipeline.grounding import tokenize_for_grounding

    # Curly apostrophe U+2019 is normalized to straight, keeping the word one token.
    assert tokenize_for_grounding("Sarah’s apples") == ["sarah's", "apples"]
    # Curly double quotes U+201C/U+201D are excluded, not emitted as tokens.
    assert tokenize_for_grounding("“hi”") == ["hi"]


def test_default_tokens_stringify_numeric_leaves():
    from app.pipeline.grounding import default_number_tokens
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=4,
        steps=[NumberLineStep(operation="add", amount=3)],
    )

    assert sorted(default_number_tokens(params)) == ["3", "4"]


def test_grounded_when_all_tokens_appear_in_source():
    from app.pipeline.grounding import check_params_grounded
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=4,
        steps=[NumberLineStep(operation="add", amount=3)],
    )

    assert check_params_grounded(params, "Sarah has 4 apples and buys 3 more.") == []


def test_ungrounded_token_is_reported():
    from app.pipeline.grounding import check_params_grounded
    from app.templates.array_grid.params import ArrayGridParams

    params = ArrayGridParams(rows=2, cols=2)

    # Source has 2.4 and 1.3 as atomic tokens; the bare "2" is nowhere.
    assert check_params_grounded(params, "(2.4) · (1.3)") == ["2", "2"]


def test_derived_total_is_allowed_when_it_equals_the_sum_of_grounded_numbers():
    from app.pipeline.grounding import check_params_grounded
    from app.templates.balance_scale.params import BalanceScaleParams

    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)

    # "7" is absent from the source but equals 3 + 4, both grounded.
    assert check_params_grounded(params, "3 + 4 = ?") == []


def test_fraction_bar_override_emits_fraction_strings():
    from app.pipeline.grounding import check_params_grounded
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    # Two steps (min_length=2 per FractionBarParams.steps); running totals
    # 3 -> 4 -> 6 stay within the guard's [0, denominator * 4] = [0, 24] bound.
    params = FractionBarParams(
        denominator=6,
        start_numerator=3,
        steps=[
            FractionStep(operation="add", numerator=1),
            FractionStep(operation="add", numerator=2),
        ],
    )

    assert check_params_grounded(params, "3/6 + 1/6 + 2/6 = ?") == []
