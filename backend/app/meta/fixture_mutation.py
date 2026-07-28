from app.meta.dsl.params import ParamsDocument
from app.meta.draft_generation import ProposedFixture


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
