MAX_NUMBER_LINE_SPAN = 20


def check_number_line_compatibility(params) -> None:
    if params.start < 0:
        raise ValueError("Number line start must be nonnegative")

    total = params.start
    values = [total]
    for step in params.steps:
        total = total + step.amount if step.operation == "add" else total - step.amount
        if total < 0:
            raise ValueError(
                f"Number line running total went negative ({total}) — not valid for this template"
            )
        values.append(total)

    span = max(values) - min(values)
    if span > MAX_NUMBER_LINE_SPAN:
        raise ValueError(
            f"Number line span is too large to render clearly "
            f"({span} > {MAX_NUMBER_LINE_SPAN})"
        )
