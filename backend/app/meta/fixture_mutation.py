from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.guard import GuardDocument, compile_guard, predicate_expressions
from app.meta.dsl.params import ParamsDocument, field_contract_for
from app.meta.draft_generation import ProposedFixture


def drop_ungrounded_positive_fixtures(fixtures: list[ProposedFixture]) -> list[ProposedFixture]:
    """Keep at most one grounded ``positive`` fixture per real observation.

    A positive fixture is the one artifact a reviewer must hand-verify: it must
    carry a ``source_excerpt`` (which only comes from an ``observation_id``) both
    to be grounded against real course content and to count toward the publish
    gate. A proposed positive with ``observation_id is None`` can never do either,
    and repeated fixtures for one observation are still only one independent
    example. Dropping ungrounded and duplicate positives at creation means the
    reviewer only sees fixtures that can contribute once to approval.
    Negative/boundary fixtures are system-generated guard cases and legitimately
    carry no observation, so they are left untouched.
    """
    result = []
    positive_observation_ids: set[str] = set()
    for fixture in fixtures:
        if fixture.kind != "positive":
            result.append(fixture)
            continue
        if fixture.observation_id is None:
            continue
        if fixture.observation_id in positive_observation_ids:
            continue
        positive_observation_ids.add(fixture.observation_id)
        result.append(fixture)
    return result


def mutate_to_violate_bounds(params_document: ParamsDocument, base_params: dict) -> dict:
    mutated = dict(base_params)
    for field in params_document.fields:
        if field.type in ("integer", "decimal") and field.name in mutated:
            mutated[field.name] = field.minimum - 1
            return mutated
    raise ValueError("no integer/decimal field available to mutate for a negative fixture")


def ensure_negative_fixtures(
    params_document: ParamsDocument, fixtures: list[ProposedFixture]
) -> list[ProposedFixture]:
    if any(fixture.kind == "negative" for fixture in fixtures):
        return fixtures
    base = next(
        (f for f in fixtures if f.kind == "positive" and f.expected_outcome == "accept"), None
    )
    if base is None:
        return fixtures
    mutated_params = mutate_to_violate_bounds(params_document, base.params)
    mutated = ProposedFixture(
        kind="negative", expected_outcome="reject", generation_method="mutated",
        observation_id=None, params=mutated_params,
    )
    return [*fixtures, mutated]


def _referenced_refs(expression, found: list) -> list:
    """Every `field_ref` node an expression reads, not merely its field names.

    The witness search needs the index and item field a predicate actually used:
    mutating an array field means replacing one item's scalar, and a bare name
    cannot say which.
    """
    if expression.node == "field_ref":
        found.append(expression)
    for operand in getattr(expression, "operands", ()):
        _referenced_refs(operand, found)
    return found


def _predicate_refs(predicate) -> list:
    found: list = []
    for expression in predicate_expressions(predicate):
        _referenced_refs(expression, found)
    return found


def _spec_for(ref, specs):
    """The field spec whose bounds bracket the value this ref reads."""
    spec = specs.get(ref.field)
    if spec is None:
        return None
    if getattr(spec, "type", None) != "array":
        return spec if ref.item_field is None else None
    return next(
        (item for item in spec.item_fields if item.name == ref.item_field), None
    )


def _current_value(ref, params: dict):
    try:
        raw = params[ref.field]
        if ref.index is not None:
            raw = raw[ref.index]
        if ref.item_field is not None:
            raw = raw[ref.item_field]
    except (KeyError, IndexError, TypeError):
        return None
    return raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None


def _with_value(ref, params: dict, value):
    """`params` with the single scalar this ref reads replaced.

    An array field keeps its list-of-objects shape, and every other item keeps its
    value: replacing the whole list with a number would make the fixture invalid
    against the params model rather than a witness for the predicate.
    """
    if ref.item_field is None:
        return {**params, ref.field: value}
    items = [dict(item) for item in params[ref.field]]
    items[ref.index] = {**items[ref.index], ref.item_field: value}
    return {**params, ref.field: items}


def _candidate_values(field_spec, siblings: list) -> list:
    """Values worth trying for one reference when hunting a rejecting witness.

    Bound-adjacent values break `range` and `positive` predicates; the odd value
    just inside the minimum breaks `divisible_by`; and a sibling reference's
    current value breaks `equals`/`not_equals`/`ordered`, which no single field's
    own bounds ever suggest.
    """
    candidates = []
    minimum = getattr(field_spec, "minimum", None)
    maximum = getattr(field_spec, "maximum", None)
    if minimum is not None:
        candidates += [minimum - 1, minimum, minimum + 1]
    if maximum is not None:
        candidates += [maximum + 1, maximum]
    candidates += [0, 1, -1, *siblings]
    seen, ordered = set(), []
    for candidate in candidates:
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            continue
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _failing_indexes(compiled, params: dict) -> frozenset:
    try:
        result = compiled.check(params)
    except DslValidationError:
        return frozenset()
    return frozenset(entry.index for entry in result.predicate_results if not entry.passed)


def ensure_guard_predicate_witnesses(
    params_document: ParamsDocument,
    guard_document: GuardDocument,
    fixtures: list[ProposedFixture],
) -> list[ProposedFixture]:
    """Add one rejecting negative fixture per guard predicate lacking a witness.

    Publishing requires every guard predicate to be independently witnessed by a
    fixture that rejects on it (``validation.require_all_fixtures_and_guard_coverage``).
    ``ensure_negative_fixtures`` cannot supply that: it returns the fixtures
    untouched as soon as any negative exists, and ``mutate_to_violate_bounds``
    returns after the first numeric field, so it witnesses at most one predicate
    out of the twenty a guard may declare. Everything else had to come from the
    model, and a model that missed one missed it on every retry -- the failure
    named the uncovered indexes but no attempt could act on them.

    Each witness is found by search rather than by inverting the predicate:
    perturb one field the predicate reads, evaluate the compiled guard, and keep
    the first perturbation that makes that predicate fail. Anything not solved
    this way is left uncovered for validation to report exactly as before.
    """
    # Shapes, not names: a guard reading `scores[0].value` compiles only against a
    # contract that knows `scores` is an array. Built from names, `compile_guard`
    # raised `unexpected_item_field`, the except below swallowed it, and every
    # array-item draft silently got no witnesses.
    try:
        compiled = compile_guard(guard_document, field_contract_for(params_document))
    except DslValidationError:
        return fixtures  # `validate_candidate` reports the real compilation failure.

    base = next(
        (f for f in fixtures if f.kind == "positive" and f.expected_outcome == "accept"), None
    )
    if base is None:
        return fixtures

    covered: set = set()
    for fixture in fixtures:
        if fixture.expected_outcome == "reject":
            covered |= _failing_indexes(compiled, fixture.params)

    specs = {field.name: field for field in params_document.fields}
    added: list[ProposedFixture] = []
    for index, predicate in enumerate(guard_document.predicates):
        if index in covered:
            continue
        witness = _find_witness(compiled, predicate, index, base.params, specs)
        if witness is None:
            continue
        added.append(ProposedFixture(
            kind="negative", expected_outcome="reject", generation_method="mutated",
            observation_id=None, params=witness,
        ))
        covered |= _failing_indexes(compiled, witness)

    return [*fixtures, *added] if added else fixtures


def _find_witness(compiled, predicate, index: int, base_params: dict, specs: dict):
    refs = _predicate_refs(predicate)
    for ref in refs:
        spec = _spec_for(ref, specs)
        if spec is None:
            continue
        siblings = [
            value for other in refs if other is not ref
            for value in [_current_value(other, base_params)] if value is not None
        ]
        for candidate in _candidate_values(spec, siblings):
            try:
                mutated = _with_value(ref, base_params, candidate)
            except (KeyError, IndexError, TypeError):
                continue
            if index in _failing_indexes(compiled, mutated):
                return mutated
    return None
