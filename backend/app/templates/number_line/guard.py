def check_number_line_compatibility(params) -> None:
    total = params.start
    for step in params.steps:
        total = total + step.amount if step.operation == "add" else total - step.amount
        if total < 0:
            raise ValueError(
                f"Number line running total went negative ({total}) — not valid for this template"
            )
