OPERATION_SYMBOLS = {"add": "+", "subtract": "-", "multiply": "×", "divide": "÷"}


def run_additive_chain(start: int, ops: list[tuple[str, int]]) -> list[int]:
    values = [start]
    running = start
    for operation, amount in ops:
        running = running + amount if operation == "add" else running - amount
        values.append(running)
    return values


def run_multiplicative_chain(start: int, ops: list[tuple[str, int]]) -> list[int]:
    if start <= 0:
        raise ValueError(f"Multiplicative chain must start from a positive value ({start})")

    values = [start]
    running = start
    for operation, factor in ops:
        if operation == "multiply":
            running = running * factor
        else:
            if factor == 0:
                raise ValueError(
                    f"Division by zero: {running} / {factor}"
                )
            # Allow non-exact division; compute_answer will handle Fraction results
            running = running // factor
        if running <= 0:
            raise ValueError(
                f"Multiplicative chain produced a non-positive value ({running})"
            )
        values.append(running)
    return values


def format_operation_caption(a, operation: str, b, result) -> str:
    symbol = OPERATION_SYMBOLS[operation]
    return f"{a} {symbol} {b} = {result}"
