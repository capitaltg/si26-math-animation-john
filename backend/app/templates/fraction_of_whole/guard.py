def check_fraction_of_whole_compatibility(params) -> None:
    if params.numerator > params.denominator:
        raise ValueError(
            f"Fraction {params.numerator}/{params.denominator} is improper — "
            "fraction_of_whole only renders proper fractions or a full whole"
        )
