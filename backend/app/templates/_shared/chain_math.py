from fractions import Fraction

OPERATION_SYMBOLS = {"add": "+", "subtract": "-", "multiply": "×", "divide": "÷"}


def run_additive_chain(start: int, ops: list[tuple[str, int]]) -> list[int]:
    values = [start]
    running = start
    for operation, amount in ops:
        running = running + amount if operation == "add" else running - amount
        values.append(running)
    return values


def run_multiplicative_chain(start: int, ops: list[tuple[str, int]]) -> list[Fraction]:
    if start <= 0:
        raise ValueError(f"Multiplicative chain must start from a positive value ({start})")

    values: list[Fraction] = [Fraction(start)]
    running = Fraction(start)
    for operation, factor in ops:
        if operation == "multiply":
            running = running * factor
        else:
            if factor == 0:
                raise ValueError(
                    f"Division by zero: {running} / {factor}"
                )
            # Allow non-exact division; Fraction will handle exact representation
            running = running / factor
        if running <= 0:
            raise ValueError(
                f"Multiplicative chain produced a non-positive value ({running})"
            )
        values.append(running)
    return values


def format_operation_caption(a, operation: str, b, result) -> str:
    symbol = OPERATION_SYMBOLS[operation]
    # Convert Fractions to string representation (int if whole number, "n/d" otherwise)
    a_str = str(int(a)) if isinstance(a, Fraction) and a.denominator == 1 else str(a)
    b_str = str(int(b)) if isinstance(b, Fraction) and b.denominator == 1 else str(b)
    result_str = str(int(result)) if isinstance(result, Fraction) and result.denominator == 1 else str(result)
    return f"{a_str} {symbol} {b_str} = {result_str}"
