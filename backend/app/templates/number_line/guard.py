from app.templates._shared.chain_math import run_additive_chain

MAX_NUMBER_LINE_SPAN = 20


def check_number_line_compatibility(params) -> None:
    if params.start < 0:
        raise ValueError("Number line start must be nonnegative")

    values = run_additive_chain(
        params.start, [(step.operation, step.amount) for step in params.steps]
    )

    for value in values:
        if value < 0:
            raise ValueError(
                f"Number line running total went negative ({value}) — not valid for this template"
            )

    span = max(values) - min(values)
    if span > MAX_NUMBER_LINE_SPAN:
        raise ValueError(
            f"Number line span is too large to render clearly "
            f"({span} > {MAX_NUMBER_LINE_SPAN})"
        )
