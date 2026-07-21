import pytest
from pydantic import ValidationError


def test_balanced_equation_passes():
    from app.templates.balance_scale.params import BalanceScaleParams

    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)
    assert params.right_total == 7


def test_unbalanced_equation_is_rejected():
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[3, 4], right_total=8)


def test_non_positive_term_is_rejected():
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[0, 4], right_total=4)


def test_total_over_renderable_bound_is_rejected():
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[15, 15], right_total=30)


@pytest.mark.parametrize("term_count", [1, 3])
def test_left_terms_must_be_exactly_two(term_count):
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[1] * term_count, right_total=term_count)
