import pytest

from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument, StringFieldSpec
from app.meta.draft_generation import ProposedFixture
from app.meta.fixture_mutation import (
    drop_ungrounded_positive_fixtures,
    ensure_negative_fixtures,
    mutate_to_violate_bounds,
)


def _params_document():
    return ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="numerator", label="N", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="denominator", label="D", description="", minimum=1, maximum=20),
        ],
    )


def test_mutate_to_violate_bounds_goes_below_minimum():
    mutated = mutate_to_violate_bounds(_params_document(), {"numerator": 3, "denominator": 4})
    assert mutated["numerator"] == 0  # minimum(1) - 1
    assert mutated["denominator"] == 4  # untouched


def test_mutate_to_violate_bounds_raises_without_numeric_field():
    document = ParamsDocument(
        params_version=1,
        fields=[StringFieldSpec(name="label", label="L", description="", max_length=10)],
    )
    with pytest.raises(ValueError, match="no integer/decimal field"):
        mutate_to_violate_bounds(document, {"label": "x"})


def test_ensure_negative_fixtures_appends_mutation_when_none_proposed():
    fixtures = [
        ProposedFixture(kind="positive", expected_outcome="accept", params={"numerator": 3, "denominator": 4}),
    ]
    result = ensure_negative_fixtures(_params_document(), fixtures)
    assert len(result) == 2
    negative = result[1]
    assert negative.kind == "negative"
    assert negative.expected_outcome == "reject"
    assert negative.generation_method == "mutated"
    assert negative.params["numerator"] == 0


def test_ensure_negative_fixtures_is_a_noop_when_negative_already_present():
    fixtures = [
        ProposedFixture(kind="positive", expected_outcome="accept", params={"numerator": 3, "denominator": 4}),
        ProposedFixture(kind="negative", expected_outcome="reject", params={"numerator": -1, "denominator": 4}),
    ]
    result = ensure_negative_fixtures(_params_document(), fixtures)
    assert result == fixtures


def test_ensure_negative_fixtures_is_a_noop_without_a_positive_fixture():
    fixtures = [ProposedFixture(kind="boundary", expected_outcome="accept", params={"numerator": 1, "denominator": 1})]
    result = ensure_negative_fixtures(_params_document(), fixtures)
    assert result == fixtures


def test_drop_ungrounded_positive_fixtures_keeps_only_grounded_positives():
    grounded = ProposedFixture(
        kind="positive", expected_outcome="accept",
        observation_id="obs-1", params={"numerator": 3, "denominator": 4},
    )
    ungrounded = ProposedFixture(
        kind="positive", expected_outcome="accept",
        observation_id=None, params={"numerator": 5, "denominator": 6},
    )
    boundary = ProposedFixture(
        kind="boundary", expected_outcome="accept",
        observation_id=None, params={"numerator": 1, "denominator": 1},
    )
    negative = ProposedFixture(
        kind="negative", expected_outcome="reject",
        observation_id=None, params={"numerator": 0, "denominator": 4},
    )
    result = drop_ungrounded_positive_fixtures([grounded, ungrounded, boundary, negative])
    # The ungrounded positive is gone; the grounded positive and the (legitimately
    # observation-less) guard cases survive.
    assert result == [grounded, boundary, negative]


def test_drop_ungrounded_positive_fixtures_deduplicates_observations():
    first = ProposedFixture(
        kind="positive", expected_outcome="accept",
        observation_id="obs-1", params={"numerator": 3, "denominator": 4},
    )
    duplicate = ProposedFixture(
        kind="positive", expected_outcome="accept",
        observation_id="obs-1", params={"numerator": 6, "denominator": 8},
    )

    assert drop_ungrounded_positive_fixtures([first, duplicate]) == [first]
