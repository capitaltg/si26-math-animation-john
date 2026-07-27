from app.templates._shared.chain_math import run_additive_chain

MAX_FRACTION_UNITS = 4  # renderable upper bound, in whole units


def check_fraction_bar_compatibility(params) -> None:
    limit = params.denominator * MAX_FRACTION_UNITS

    values = run_additive_chain(
        params.start_numerator, [(step.operation, step.numerator) for step in params.steps]
    )

    for value in values:
        if value < 0:
            raise ValueError(
                f"Fraction running total went negative ({value}/{params.denominator})"
            )
        if value > limit:
            raise ValueError(
                f"Fraction total {value}/{params.denominator} exceeds renderable bound "
                f"of {MAX_FRACTION_UNITS} whole units"
            )
