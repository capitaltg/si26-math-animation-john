from app.templates._shared.chain_math import run_multiplicative_chain

MAX_GRID_AXIS = 12
MAX_GRID_TOTAL = 144


def check_array_grid_compatibility(params) -> None:
    if params.rows <= 0 or params.cols <= 0:
        raise ValueError("Array grid rows and cols must be positive")
    if params.rows > MAX_GRID_AXIS or params.cols > MAX_GRID_AXIS:
        raise ValueError(
            f"Array grid axis too long to fit the frame ({params.rows}x{params.cols}; "
            f"max {MAX_GRID_AXIS} per axis)"
        )
    if params.rows * params.cols > MAX_GRID_TOTAL:
        raise ValueError(
            f"Array grid too large to render clearly ({params.rows}x{params.cols} > "
            f"{MAX_GRID_TOTAL} cells)"
        )

    if not params.steps:
        return

    totals = run_multiplicative_chain(
        params.rows * params.cols, [(step.operation, step.factor) for step in params.steps]
    )

    for total in totals:
        if total % params.cols != 0:
            raise ValueError(
                f"Array grid chain total {total} does not divide evenly into "
                f"{params.cols} fixed columns"
            )
        rows_at_step = total // params.cols
        if rows_at_step > MAX_GRID_AXIS:
            raise ValueError(
                f"Array grid chain requires {rows_at_step} rows at some step; "
                f"max {MAX_GRID_AXIS} per axis"
            )
        if total > MAX_GRID_TOTAL:
            raise ValueError(
                f"Array grid chain total {total} exceeds renderable bound of "
                f"{MAX_GRID_TOTAL} cells"
            )
