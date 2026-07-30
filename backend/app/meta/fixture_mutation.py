from app.meta.dsl.params import ParamsDocument
from app.meta.draft_generation import ProposedFixture


def drop_ungrounded_positive_fixtures(fixtures: list[ProposedFixture]) -> list[ProposedFixture]:
    """Remove ``positive`` fixtures that are not tied to a real observation.

    A positive fixture is the one artifact a reviewer must hand-verify: it must
    carry a ``source_excerpt`` (which only comes from an ``observation_id``) both
    to be grounded against real course content and to count toward the publish
    gate. A proposed positive with ``observation_id is None`` can never do either
    -- it only clutters the reviewer's "fixtures to verify" list with a card that
    does nothing when filled in, and, if its params happen to fail the structural
    check, silently drags the whole draft into ``failed_validation``. Dropping it
    at creation means the reviewer only ever sees fixtures that can actually be
    approved. Negative/boundary fixtures are system-generated guard cases and
    legitimately carry no observation, so they are left untouched.
    """
    return [
        fixture
        for fixture in fixtures
        if not (fixture.kind == "positive" and fixture.observation_id is None)
    ]


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
