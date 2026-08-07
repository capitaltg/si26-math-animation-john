from app.templates._shared.chain_math import run_multiplicative_chain
from app.templates.array_grid.layout import grid_dimensions


def check_array_grid_compatibility(params) -> None:
    if not params.steps:
        grid_dimensions(params.starting_total())
        return

    totals = run_multiplicative_chain(
        params.starting_total(),
        [(step.operation, step.factor) for step in params.steps],
    )
    for total in totals:
        grid_dimensions(total)
