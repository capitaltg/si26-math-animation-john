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

    def __init__(self, tokens, derived_totals, string_tokens=None):
        self._tokens = tokens
        self._derived_totals = derived_totals
        self._string_tokens = string_tokens or []

    def grounding_number_tokens(self):
        return self._tokens

    def grounding_derived_totals(self):
        return self._derived_totals

    def grounding_string_tokens(self):
        return self._string_tokens


def test_derived_total_allowed_only_via_explicit_declaration():
    from app.pipeline.grounding import check_params_grounded

    # "7" is absent from the source but a template declares it as 3 + 4.
    # "5" is grounded literally, while the explicit subset declares 3+4 as 7.
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


def test_derived_product_total_is_allowed_when_its_components_are_grounded():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=["3", "4", "12"],
        derived_totals=[("12", ["3", "4"], "product")],
    )

    assert check_params_grounded(params, "3 × 4 = ?") == []


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


def test_array_grid_chain_grounds_start_and_factors_without_dimensions():
    from app.pipeline.grounding import check_params_grounded
    from app.templates.array_grid.params import ArrayGridParams, ArrayGridStep

    params = ArrayGridParams(
        start=24,
        steps=[
            ArrayGridStep(operation="divide", factor=3),
            ArrayGridStep(operation="multiply", factor=2),
        ],
    )

    assert check_params_grounded(
        params,
        "Start with 24 counters, divide by 3, then multiply by 2.",
    ) == []


def test_duplicate_param_token_requires_duplicate_source_occurrence():
    from app.pipeline.grounding import check_params_grounded

    # Source has one "3"; params want two.
    params = _StubParams(tokens=["3", "3"], derived_totals=[])
    assert check_params_grounded(
        params,
        "A box has 3 red balls and 5 blue balls.",
    ) == ["3"]


# ---------------------------------------------------------------------------
# Multiset + occurrence-binding coverage (spec 2026-08-06)
# ---------------------------------------------------------------------------


def test_two_source_occurrences_allow_two_duplicate_params():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["3", "3"], derived_totals=[])
    assert check_params_grounded(params, "3 red balls and 3 blue balls") == []


def test_single_param_still_grounded_against_single_source_occurrence():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["3"], derived_totals=[])
    assert check_params_grounded(params, "A box has 3 red balls and 5 blue balls.") == []


def test_out_of_order_param_tokens_still_ground():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["5", "3"], derived_totals=[])
    assert check_params_grounded(params, "3 red balls and 5 blue balls") == []


def test_derived_total_uses_fresh_multiset_independent_of_literal_pass():
    from app.pipeline.grounding import check_params_grounded

    # Literal pass consumes the source 3 and 5; the derived total's
    # components must still ground because the derived pass uses a fresh copy.
    params = _StubParams(
        tokens=["3", "5", "8"],
        derived_totals=[("8", ["3", "5"])],
    )
    assert check_params_grounded(params, "3 red balls and 5 blue balls") == []


def test_duplicated_component_in_derived_total_requires_two_source_occurrences():
    from app.pipeline.grounding import check_params_grounded

    # Abuse case: `[3, 3, 6]` with derived `6 <- [3, 3]` against a source
    # that has one 3. Literal consumes source 3, second param 3 stays
    # ungrounded. Derived total's components need two source 3s — fresh
    # multiset has one — so `6` cannot be vouched for as a derived total.
    params = _StubParams(
        tokens=["3", "3", "6"],
        derived_totals=[("6", ["3", "3"])],
    )
    assert check_params_grounded(params, "3 red balls and 5 blue balls") == ["3", "6"]


def test_derived_product_total_grounds_when_components_do():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=["2", "3", "6"],
        derived_totals=[("6", ["2", "3"], "product")],
    )
    assert check_params_grounded(params, "2 rows and 3 columns") == []


def test_source_with_extra_occurrence_grounds_repeated_components_and_total():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=["3", "3", "6"],
        derived_totals=[("6", ["3", "3"])],
    )
    assert check_params_grounded(params, "3 and 3 more give what, out of 5?") == []


def test_integer_and_float_forms_of_same_value_collide():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["3"], derived_totals=[])
    assert check_params_grounded(params, "The mass is 3.0 kilograms.") == []


def test_half_as_fraction_and_decimal_collide():
    from app.pipeline.grounding import check_params_grounded

    params_frac_source = _StubParams(tokens=["0.5"], derived_totals=[])
    assert check_params_grounded(params_frac_source, "One 1/2 remains.") == []

    params_decimal_source = _StubParams(tokens=["1/2"], derived_totals=[])
    assert check_params_grounded(params_decimal_source, "One 0.5 remains.") == []


def test_negative_values_ground_against_negative_source():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["-3", "5"], derived_totals=[])
    assert check_params_grounded(params, "Start at -3 and add 5.") == []


def test_two_negative_params_need_two_negative_source_occurrences():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["-3", "-3"], derived_totals=[])
    assert check_params_grounded(params, "Start at -3 and add 5.") == ["-3"]


def test_unicode_minus_sign_normalizes_to_ascii_hyphen():
    from app.pipeline.grounding import check_params_grounded, tokenize_for_grounding

    assert tokenize_for_grounding("Start at −3 and add 5.") == ["start", "at", "-3", "and", "add", "5"]

    params = _StubParams(tokens=["-3", "5"], derived_totals=[])
    assert check_params_grounded(params, "Start at −3 and add 5.") == []


def test_distinct_fractions_ground_against_matching_source():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["1/2", "1/4"], derived_totals=[])
    assert check_params_grounded(params, "Combine 1/2 and 1/4.") == []


def test_duplicate_fraction_param_requires_duplicate_source():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["1/2", "1/2"], derived_totals=[])
    assert check_params_grounded(params, "Combine 1/2 and 1/4.") == ["1/2"]


def test_atomic_decimal_grounds_end_to_end():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["3.14"], derived_totals=[])
    assert check_params_grounded(params, "The value is 3.14 exactly.") == []


def test_cross_problem_boundary_is_documented_not_prevented():
    """Multiset alone cannot separate two problems that share numbers on
    the same excerpt. This test pins the current limit; solving it fully
    would require shape/cell coord binding (see spec's Future work).
    """
    from app.pipeline.grounding import check_params_grounded

    # Excerpt contains both problems. Params for Problem A ask for four
    # tokens; source multiset has 2×3 + 1×5 + 1×7 = four occurrences, so
    # they all bind. The binding is not necessarily to Problem A's numbers.
    params = _StubParams(tokens=["3", "5", "3", "7"], derived_totals=[])
    assert check_params_grounded(
        params,
        "Problem A: 3 + 5. Problem B: 3 + 7.",
    ) == []


def test_word_token_falls_through_canonical_key_untouched():
    from app.pipeline.grounding import _canonical_key

    # Word tokens key on themselves and cannot collide with numeric canonicals.
    assert _canonical_key("three") == "three"
    assert _canonical_key("three") != _canonical_key("3")


def test_unspaced_hyphen_between_digits_stays_operator_and_operand():
    from app.pipeline.grounding import tokenize_for_grounding

    # Regression: unspaced hyphens between digits must stay as separate tokens
    # (operator + operand), not collapse into a single negative number token.
    # This protects range notation "10-20" and subtraction "5-3" in discovery.py
    # and other callsites.
    assert tokenize_for_grounding("5-3") == ["5", "-", "3"]
    assert tokenize_for_grounding("10-20") == ["10", "-", "20"]


def test_unspaced_hyphen_after_letter_stays_operator_and_operand():
    from app.pipeline.grounding import tokenize_for_grounding

    # Regression: the digit-only lookbehind let a preceding LETTER through,
    # so "x-5" tokenized as ['x', '-5'] instead of ['x', '-', '5']. Widening
    # the lookbehind to exclude any word char or "." fixes this while
    # preserving the digit-digit and negative-number behavior above.
    assert tokenize_for_grounding("x-5") == ["x", "-", "5"]
    assert tokenize_for_grounding("grade-3") == ["grade", "-", "3"]


def test_legitimate_repeated_value_written_once_is_rejected_by_design():
    """Multiset semantics cannot distinguish 'source legitimately repeats a
    value the extractor also legitimately repeats, but the source text only
    spells it out once' from a hallucinated duplicate operand. This is an
    accepted false-positive: the security goal (reject params claiming more
    occurrences than the source contains) takes priority. See spec's Risk
    table / migration audit for the intended mitigation path.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=["3", "3", "6"],
        derived_totals=[("6", ["3", "3"])],
    )
    # Source text says "3" once even though two boxes of 3 pounds are meant.
    # "6" grounds literally (source has "6-pound" once); the derived-total
    # pass for 6 <- [3, 3] needs a fresh copy with two "3"s but only finds
    # one, so it is not vouched for as a derived total either. Only the
    # second "3" is left ungrounded.
    assert check_params_grounded(
        params,
        "Two boxes of 3 pounds each balance a 6-pound box.",
    ) == ["3"]


def test_negative_decimal_and_fraction_forms_collide():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["-0.5"], derived_totals=[])
    assert check_params_grounded(params, "The change is -1/2 a unit.") == []


def test_duplicate_derived_total_claim_is_not_multiset_checked():
    """allowed_totals is a set of canonical keys, not a multiset — claiming
    the same derived total twice both ground even though only one component
    pair exists in the source. Accepted: derived totals are computed values,
    not literal source quotes, so multiset-binding doesn't apply to them."""
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=["8", "8"],
        derived_totals=[("8", ["3", "5"])],
    )
    assert check_params_grounded(params, "3 apples and 5 oranges.") == []


# ---------------------------------------------------------------------------
# String/enum grounding (P0: dynamic string/enum params were invisible)
# ---------------------------------------------------------------------------


def test_wrong_unit_is_ungrounded():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["3"], derived_totals=[], string_tokens=["meters"])
    assert check_params_grounded(params, "A 3 kilometer path has oranges.") == ["meters"]


def test_wrong_object_label_is_ungrounded():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=["3"], derived_totals=[], string_tokens=["apples"])
    assert check_params_grounded(params, "A 3 kilometer path has oranges.") == ["apples"]


def test_correct_unit_and_object_ground():
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=["3"], derived_totals=[], string_tokens=["kilometer", "oranges"]
    )
    assert check_params_grounded(params, "A 3 kilometer path has oranges.") == []


def test_string_token_case_and_whitespace_normalize():
    from app.pipeline.grounding import check_params_grounded

    # Casing and surrounding whitespace differ from the source spelling but
    # the word itself is unchanged, so it still grounds.
    params = _StubParams(tokens=[], derived_totals=[], string_tokens=["  Kilometer  "])
    assert check_params_grounded(params, "A 3 kilometer path.") == []


def test_plural_mismatch_does_not_silently_ground():
    from app.pipeline.grounding import check_params_grounded

    # No stemming: "apple" and "apples" are distinct tokens, so a param
    # claiming the singular against a plural-only source is caught, not
    # silently accepted as "close enough".
    params = _StubParams(tokens=[], derived_totals=[], string_tokens=["apple"])
    assert check_params_grounded(params, "Sarah has apples.") == ["apple"]


def test_multi_word_string_requires_ordered_contiguous_phrase():
    """A source-owned multi-word value must bind to the exact ordered
    phrase in one contiguous run of source tokens — never as two
    independent word matches. That was the P0: `red balloon` used to
    ground against "The balloon is beside the red box." because both words
    exist, even though the phrase does not.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=[], derived_totals=[], string_tokens=["red balloon"])
    assert check_params_grounded(params, "Sarah has a red balloon.") == []


def test_multi_word_string_rejects_separated_words():
    """The exact release-blocker repro: both words are in the source, but
    not as one adjacent phrase in that order. Independent-word matching
    would accept this; ordered-phrase matching must reject it.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=[], derived_totals=[], string_tokens=["red balloon"])
    assert (
        check_params_grounded(params, "The balloon is beside the red box.")
        == ["red balloon"]
    )


def test_multi_word_string_rejects_reverse_order():
    """Adjacency alone is not enough — the tokens must appear in the
    phrase's declared order. "balloon red" is not "red balloon".
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=[], derived_totals=[], string_tokens=["red balloon"])
    assert check_params_grounded(params, "A blue balloon and red kite.") == ["red balloon"]


def test_multi_word_string_duplicate_value_needs_two_source_spans():
    """A duplicated source-owned phrase (declared twice) must find two
    non-overlapping source spans. One source occurrence cannot cover both.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=[], derived_totals=[], string_tokens=["red balloon", "red balloon"]
    )
    # Only one source occurrence of the phrase — second declaration ungrounded.
    assert (
        check_params_grounded(params, "Sarah has a red balloon.") == ["red balloon"]
    )
    # Two source occurrences — both bind, each to its own span.
    assert (
        check_params_grounded(
            params, "One red balloon floated up while another red balloon popped."
        )
        == []
    )


def test_overlapping_phrase_values_share_source_tokens_via_reassignment():
    """When two source-owned phrases can each match at more than one source
    span, a greedy first-fit walker would strand the harder-to-place
    phrase. `["red", "red balloon"]` against "red balloon red" is fully
    groundable — "red balloon" takes the leading two tokens and "red"
    takes the trailing one — so the solver must find that assignment
    instead of giving "red" the first token and leaving "red balloon"
    without adjacent tokens.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=[], derived_totals=[], string_tokens=["red", "red balloon"]
    )
    assert check_params_grounded(params, "red balloon red") == []


def test_overlapping_phrase_values_report_only_the_unreachable_one():
    """Two phrases, only one source occurrence they could share: the
    solver assigns the span to whichever phrase has no other viable spot
    and reports the other. `["red balloon", "red"]` against
    "sarah has a red balloon" — "red balloon" is grounded (only one
    valid span) and "red" is ungrounded because the only "red" token is
    already consumed.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=[], derived_totals=[], string_tokens=["red balloon", "red"]
    )
    assert check_params_grounded(params, "sarah has a red balloon.") == ["red"]


def test_phrase_assignment_finishes_fast_when_many_identical_phrases_share_few_spans():
    """The DSL caps source-owned string arrays at 12 values, so a schema-
    valid params object can declare the same phrase 12 times. The prior
    per-phrase backtracking was O(candidates^phrases), which for
    12 identical values against 6 matching source tokens took seconds and
    ran on every extraction/validation call. Collapsing identical phrases
    into one capacity-tracked slot keeps the DP polynomial; this test
    guards against reintroducing the exponential shape.
    """
    import time

    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(
        tokens=[], derived_totals=[], string_tokens=["red"] * 12
    )
    started = time.perf_counter()
    result = check_params_grounded(params, "red red red red red red")
    elapsed = time.perf_counter() - started

    # Six source spans satisfy six of the twelve declarations; the other
    # six report ungrounded and the value string appears once per unmet
    # declaration.
    assert result == ["red"] * 6
    assert elapsed < 0.5, f"phrase assignment took {elapsed:.3f}s"


def test_phrase_assignment_grounds_over_thirteen_declarations_with_shared_tokens():
    """The full reviewer counterexample: three phrases share the source
    tokens (``a b``, ``b``, ``b a``) alongside ten single-word fillers. A
    fewest-alternatives greedy without backtracking strands ``b a``
    because giving ``a b`` its first source occurrence blocks both of
    ``b a``'s spans; the correct assignment (``b a`` → tokens 0..1,
    ``a b`` → tokens 3..4, ``b`` → token 2) needs the search to reconsider
    ``a b``'s choice. The solver must find that assignment.
    """
    from app.pipeline.grounding import check_params_grounded

    filler = list("cdefghijkl")
    params = _StubParams(
        tokens=[],
        derived_totals=[],
        string_tokens=["a b", "b", "b a", *filler],
    )
    source_text = "b a b a b " + " ".join(filler)

    assert check_params_grounded(params, source_text) == []


def test_phrase_assignment_finishes_fast_when_many_distinct_phrases_declared():
    """The interval DP's state grows as Product(cap_i + 1); with many
    distinct single-cap slots the exponent hits the request path (22
    distinct values took ~6s locally). The solver falls back to a
    length-descending greedy above _PHRASE_SOLVER_MAX_DISTINCT_SLOTS so an
    adversarial params object cannot drag the exponential shape onto every
    extraction call. This test guards the fallback threshold.
    """
    import time

    from app.pipeline.grounding import check_params_grounded

    distinct_words = [f"word{n:02d}" for n in range(24)]
    params = _StubParams(
        tokens=[], derived_totals=[], string_tokens=distinct_words
    )
    source_text = " ".join(distinct_words)

    started = time.perf_counter()
    result = check_params_grounded(params, source_text)
    elapsed = time.perf_counter() - started

    assert result == []
    assert elapsed < 0.5, f"phrase assignment took {elapsed:.3f}s"


def test_string_token_respects_source_token_boundaries():
    """The phrase tokenizer emits whole words, so a short phrase cannot
    bind inside a longer source word. `cat` must not ground against
    `concatenate` — the source token there is `concatenate`, not `cat`.
    """
    from app.pipeline.grounding import check_params_grounded

    params = _StubParams(tokens=[], derived_totals=[], string_tokens=["cat"])
    assert check_params_grounded(params, "concatenate the string.") == ["cat"]


def test_derived_total_allowance_does_not_launder_a_coincidentally_numeric_string_token():
    from app.pipeline.grounding import check_params_grounded

    # A numeric derived total (7 <- 3 + 4) is unrelated to a source-owned
    # string/enum field whose value happens to be the digit string "7".
    # Derived-total allowance is a numeric-only concept; it must not exempt
    # a string token merely because it shares a canonical key with an
    # allowed numeric total.
    params = _StubParams(
        tokens=["3", "4"],
        derived_totals=[("7", ["3", "4"])],
        string_tokens=["7"],
    )
    assert check_params_grounded(params, "3 and 4 make what?") == ["7"]
