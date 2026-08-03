import pytest

from app.meta.dsl.guard import GuardDocument, compile_guard
from app.meta.dsl.params import (
    ArrayFieldSpec, IntegerFieldSpec, ParamsDocument, StringFieldSpec, field_contract_for,
)
from app.meta.draft_generation import ProposedFixture
from app.meta.fixture_mutation import (
    drop_ungrounded_positive_fixtures,
    ensure_guard_predicate_witnesses,
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


def _coverage_documents():
    """Four predicates whose witnesses cannot all come from field bounds.

    `positive(length)` and `positive(width)` fall out of a below-minimum
    mutation, but `divisible_by(length, 2)` needs an odd length and
    `not_equals(length, width)` needs the two fields made equal -- which no
    single field's bounds suggest.
    """
    params = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="length", label="L", description="", minimum=2, maximum=50),
            IntegerFieldSpec(name="width", label="W", description="", minimum=2, maximum=50),
        ],
    )
    guard = GuardDocument(predicates=[
        {"predicate": "positive", "value": {"node": "field_ref", "field": "length"}},
        {"predicate": "positive", "value": {"node": "field_ref", "field": "width"}},
        {"predicate": "divisible_by",
         "value": {"node": "field_ref", "field": "length"},
         "divisor": {"node": "literal", "value": 2}},
        {"predicate": "not_equals",
         "left": {"node": "field_ref", "field": "length"},
         "right": {"node": "field_ref", "field": "width"}},
    ])
    return params, guard


def _witnessed_indexes(guard, params_document, fixtures):
    # Shapes, not names -- the same distinction the code under test needs.
    compiled = compile_guard(guard, field_contract_for(params_document))
    covered = set()
    for fixture in fixtures:
        if fixture.expected_outcome != "reject":
            continue
        try:
            result = compiled.check(fixture.params)
        except Exception:
            continue
        covered.update(entry.index for entry in result.predicate_results if not entry.passed)
    return covered


def test_guard_witnesses_are_synthesized_for_every_uncovered_predicate():
    """Every guard predicate needs a fixture that independently rejects on it.

    `ensure_negative_fixtures` could only ever witness one: it returns the
    fixtures untouched when any negative already exists, and
    `mutate_to_violate_bounds` returns after the first numeric field it finds. A
    guard may hold up to 20 predicates, so witnesses for the rest could only come
    from the model -- which failed three attempts running, reporting "missing
    predicate indexes: 2, 3".
    """
    params_document, guard = _coverage_documents()
    fixtures = [
        ProposedFixture(kind="positive", expected_outcome="accept",
                        observation_id="obs-1", params={"length": 8, "width": 3}),
        ProposedFixture(kind="negative", expected_outcome="reject",
                        params={"length": 0, "width": 3}),
        ProposedFixture(kind="negative", expected_outcome="reject",
                        params={"length": 8, "width": 0}),
    ]
    assert _witnessed_indexes(guard, params_document, fixtures) == {0, 1}, (
        "the fixture set under test must start with predicates 2 and 3 uncovered"
    )

    repaired = ensure_guard_predicate_witnesses(params_document, guard, fixtures)

    assert _witnessed_indexes(guard, params_document, repaired) == {0, 1, 2, 3}
    # The originals are kept, and every addition is a rejecting negative.
    assert repaired[:len(fixtures)] == fixtures
    for fixture in repaired[len(fixtures):]:
        assert fixture.kind == "negative"
        assert fixture.expected_outcome == "reject"
        assert fixture.observation_id is None


def test_guard_witness_repair_is_a_no_op_when_coverage_is_already_complete():
    params_document, guard = _coverage_documents()
    fixtures = [
        ProposedFixture(kind="positive", expected_outcome="accept",
                        observation_id="obs-1", params={"length": 8, "width": 3}),
        ProposedFixture(kind="negative", expected_outcome="reject",
                        params={"length": 0, "width": 3}),
        ProposedFixture(kind="negative", expected_outcome="reject",
                        params={"length": 8, "width": 0}),
        ProposedFixture(kind="negative", expected_outcome="reject",
                        params={"length": 7, "width": 3}),
        ProposedFixture(kind="negative", expected_outcome="reject",
                        params={"length": 8, "width": 8}),
    ]

    assert ensure_guard_predicate_witnesses(params_document, guard, fixtures) == fixtures


def _array_coverage_documents():
    """A guard whose predicates read scalars inside array items."""
    params = ParamsDocument(
        params_version=1,
        fields=[ArrayFieldSpec(
            name="scores", label="Scores", description="", min_items=2, max_items=7,
            item_fields=[IntegerFieldSpec(
                name="value", label="V", description="", minimum=1, maximum=99,
            )],
        )],
    )
    def ref(index):
        return {"node": "field_ref", "field": "scores", "index": index, "item_field": "value"}
    guard = GuardDocument(predicates=[
        {"predicate": "positive", "value": ref(0)},
        {"predicate": "ordered", "direction": "non_decreasing", "terms": [ref(0), ref(1)]},
    ])
    return params, guard


def test_array_item_guards_still_get_synthesized_witnesses():
    """The repair must compile against field SHAPES, not bare names.

    It built its contract as `frozenset(field.name ...)`, so an `item_field`
    reference looked like an item field on a scalar -- `compile_guard` raised
    `unexpected_item_field`, the bare `except DslValidationError` swallowed it,
    and the function returned the fixtures untouched. Every draft whose guard
    reads an array item therefore got no witnesses at all, silently, and failed
    the publish gate on coverage it could have satisfied.
    """
    params_document, guard = _array_coverage_documents()
    fixtures = [ProposedFixture(
        kind="positive", expected_outcome="accept", observation_id="obs-1",
        params={"scores": [{"value": 3}, {"value": 8}]},
    )]

    repaired = ensure_guard_predicate_witnesses(params_document, guard, fixtures)

    assert _witnessed_indexes(guard, params_document, repaired) == {0, 1}
    for fixture in repaired[len(fixtures):]:
        # A witness must keep the array shape the params document declares.
        assert isinstance(fixture.params["scores"], list)
        assert all(isinstance(item, dict) for item in fixture.params["scores"])


def test_a_synthesized_array_witness_leaves_the_other_items_alone():
    params_document, guard = _array_coverage_documents()
    fixtures = [ProposedFixture(
        kind="positive", expected_outcome="accept", observation_id="obs-1",
        params={"scores": [{"value": 3}, {"value": 8}]},
    )]

    repaired = ensure_guard_predicate_witnesses(params_document, guard, fixtures)

    added = repaired[len(fixtures):]
    assert added, "the uncovered predicates must produce witnesses"
    for fixture in added:
        assert len(fixture.params["scores"]) == 2
