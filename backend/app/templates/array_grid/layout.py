from math import isqrt

MAX_GRID_AXIS = 12
MAX_GRID_TOTAL = 144


def grid_dimensions(total: int) -> tuple[int, int]:
    if total <= 0:
        raise ValueError(f"Array grid total must be positive ({total})")
    if total > MAX_GRID_TOTAL:
        raise ValueError(
            f"Array grid total {total} exceeds renderable bound of {MAX_GRID_TOTAL} cells"
        )

    pairs = [
        (rows, total // rows)
        for rows in range(1, min(isqrt(total), MAX_GRID_AXIS) + 1)
        if total % rows == 0 and total // rows <= MAX_GRID_AXIS
    ]
    if not pairs:
        raise ValueError(
            f"Array grid total {total} has no renderable factor pair "
            f"within {MAX_GRID_AXIS}x{MAX_GRID_AXIS}"
        )
    return max(pairs, key=lambda pair: pair[0])
