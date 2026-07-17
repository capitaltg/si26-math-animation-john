def check_array_grid_compatibility(params) -> None:
    if params.rows <= 0 or params.cols <= 0:
        raise ValueError("Array grid rows and cols must be positive")
    if params.rows * params.cols > 144:
        raise ValueError(
            f"Array grid too large to render clearly ({params.rows}x{params.cols} > 144 cells)"
        )
