import pytest


def test_build_fraction_cells_returns_n_cells():
    from app.templates._shared.fraction_cells import build_fraction_cells

    cells = build_fraction_cells(4)

    assert len(cells) == 4


def test_build_fraction_cells_clamps_width_for_large_n():
    from app.templates._shared.fraction_cells import build_fraction_cells

    cells = build_fraction_cells(20)

    assert len(cells) == 20
    assert cells[0].width < 0.6


def test_build_fraction_cells_uses_full_width_for_small_n():
    from app.templates._shared.fraction_cells import build_fraction_cells

    cells = build_fraction_cells(2)

    assert cells[0].width == pytest.approx(0.6)
