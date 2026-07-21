MAX_BALANCE_VALUE = 20


def check_balance_scale_compatibility(params) -> None:
    if any(term <= 0 for term in params.left_terms):
        raise ValueError("Balance scale terms must be positive")
    if sum(params.left_terms) != params.right_total:
        left = " + ".join(str(term) for term in params.left_terms)
        raise ValueError(
            f"Balance scale does not balance: {left} != {params.right_total}"
        )
    if params.right_total > MAX_BALANCE_VALUE:
        raise ValueError(
            f"Balance scale total {params.right_total} exceeds renderable bound "
            f"{MAX_BALANCE_VALUE}"
        )
