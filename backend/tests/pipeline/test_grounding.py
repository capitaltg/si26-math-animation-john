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


class _StubParams:
    """Minimal params exposing the grounding hooks directly."""

    def __init__(self, tokens, derived_totals):
        self._tokens = tokens
        self._derived_totals = derived_totals

    def grounding_number_tokens(self):
        return self._tokens

    def grounding_derived_totals(self):
        return self._derived_totals


def test_derived_total_allowed_only_via_explicit_declaration():
    from app.pipeline.grounding import check_params_grounded

    # "7" is absent from the source but a template declares it as 3 + 4.
    # "5" is grounded literally, so the OLD global-sum heuristic (3+4+5=12)
    # would have rejected "7"; the explicit subset declaration accepts it.
    params = _StubParams(
        tokens=["3", "4", "5", "7"],
        derived_totals=[("7", ["3", "4"])],
    )

    assert check_params_grounded(params, "3 4 5") == []


def test_global_sum_without_declaration_is_rejected():
    from app.pipeline.grounding import check_params_grounded

    # "7" equals 3 + 4 but NO template vouches for it -> strict literal-only.
    params = _StubParams(tokens=["7", "3", "4"], derived_totals=[])

    assert check_params_grounded(params, "3 + 4 = ?") == ["7"]


def test_derived_total_rejected_when_a_component_is_not_grounded():
    from app.pipeline.grounding import check_params_grounded

    # "3" is absent, so the declared total "7" cannot be vouched for either.
    params = _StubParams(tokens=["3", "4", "7"], derived_totals=[("7", ["3", "4"])])

    assert check_params_grounded(params, "4 = ?") == ["3", "7"]


def test_derived_total_rejected_when_value_does_not_equal_component_sum():
    from app.pipeline.grounding import check_params_grounded

    # Declared total "8" does not equal 3 + 4, so it stays ungrounded.
    params = _StubParams(tokens=["3", "4", "8"], derived_totals=[("8", ["3", "4"])])

    assert check_params_grounded(params, "3 4") == ["8"]


def test_balance_scale_declares_right_total_as_derived():
    from app.pipeline.grounding import check_params_grounded
    from app.templates.balance_scale.params import BalanceScaleParams

    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)

    # "7" is absent from the source but the template vouches for it as 3 + 4.
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
