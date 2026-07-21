from manim import ORIGIN, RIGHT, WHITE, Rectangle, VGroup


def build_fraction_cells(n_cells: int) -> VGroup:
    cell_width = min(0.6, 12.0 / n_cells)
    cells = VGroup()
    for _ in range(n_cells):
        cells.add(Rectangle(width=cell_width, height=0.8, stroke_color=WHITE))
    cells.arrange(RIGHT, buff=0).move_to(ORIGIN)
    return cells
