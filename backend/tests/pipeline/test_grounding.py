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
