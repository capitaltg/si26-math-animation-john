from manim import (
    Arrow,
    Brace,
    Dot,
    Line,
    NumberLine,
    Sector,
    Square,
    Text,
    VGroup,
    DOWN,
    UP,
)

from app.meta.manim_primitives.style import resolve_style
from app.templates._shared.fit_to_frame import fit_width


def build_number_line(minimum: float, maximum: float, marker_value: float, style: str = "primary") -> VGroup:
    if not (minimum <= marker_value <= maximum):
        raise ValueError(f"marker_value {marker_value} outside [{minimum}, {maximum}]")
    line = NumberLine(x_range=[minimum, maximum, 1], include_numbers=True)
    fit_width(line)
    marker = Dot(line.number_to_point(marker_value), **resolve_style(style))
    return VGroup(line, marker)


def build_grid(rows: int, cols: int, style: str = "primary") -> VGroup:
    if rows <= 0 or cols <= 0:
        raise ValueError(f"grid requires positive rows/cols, got {rows}x{cols}")
    cells = [Square(side_length=0.6, **resolve_style(style)) for _ in range(rows * cols)]
    group = VGroup(*cells).arrange_in_grid(rows=rows, cols=cols, buff=0.1)
    fit_width(group)
    return group


def build_bar(filled: int, total: int, style: str = "primary") -> VGroup:
    if total <= 0 or filled < 0 or filled > total:
        raise ValueError(f"bar requires 0 <= filled <= total, got filled={filled} total={total}")
    style_kwargs = resolve_style(style)
    cells = []
    for index in range(total):
        cell = Square(side_length=0.6)
        if index < filled:
            cell.set_fill(style_kwargs["color"], opacity=1)
        cell.set_stroke(style_kwargs["color"], width=style_kwargs["stroke_width"])
        cells.append(cell)
    group = VGroup(*cells).arrange(buff=0.05)
    fit_width(group)
    return group


def build_object_set(count: int, style: str = "primary") -> VGroup:
    if count <= 0:
        raise ValueError(f"object_set requires a positive count, got {count}")
    dots = [Dot(**resolve_style(style)) for _ in range(count)]
    group = VGroup(*dots).arrange_in_grid(cols=min(5, count), buff=0.3)
    fit_width(group)
    return group


def build_shape_partition(parts: int, shaded: int, style: str = "primary") -> VGroup:
    if parts <= 0 or shaded < 0 or shaded > parts:
        raise ValueError(f"shape_partition requires 0 <= shaded <= parts, got shaded={shaded} parts={parts}")
    style_kwargs = resolve_style(style)
    angle = 6.283185307179586 / parts
    wedges = []
    for index in range(parts):
        wedge = Sector(radius=1.2, angle=angle, start_angle=index * angle)
        if index < shaded:
            wedge.set_fill(style_kwargs["color"], opacity=1)
        wedge.set_stroke(style_kwargs["color"], width=style_kwargs["stroke_width"])
        wedges.append(wedge)
    return VGroup(*wedges)


def build_arrow(start_mobject, end_mobject, style: str = "accent") -> Arrow:
    style_kwargs = resolve_style(style)
    return Arrow(
        start_mobject.get_center(),
        end_mobject.get_center(),
        buff=0,
        color=style_kwargs["color"],
        stroke_width=style_kwargs["stroke_width"],
    )


def build_brace(target_mobject, text: str, style: str = "muted") -> VGroup:
    style_kwargs = resolve_style(style)
    brace = Brace(target_mobject, direction=DOWN, color=style_kwargs["color"])
    label = Text(text)
    fit_width(label)
    label.next_to(brace, DOWN)
    return VGroup(brace, label)


def build_tally_marks(count: int, style: str = "primary") -> VGroup:
    if count <= 0:
        raise ValueError(f"tally_marks requires a positive count, got {count}")
    style_kwargs = resolve_style(style)
    lines = []
    remaining = count
    group_x_offset = 0.0
    group_spacing = 0.15 * 4 + 0.3
    while remaining > 0:
        in_group = min(5, remaining)
        for i in range(min(in_group, 4)):
            lines.append(
                Line(UP * 0.3, DOWN * 0.3, color=style_kwargs["color"]).shift(
                    [group_x_offset + i * 0.15, 0, 0]
                )
            )
        if in_group == 5:
            lines.append(
                Line(
                    [-0.05, -0.35, 0], [0.5, 0.35, 0], color=style_kwargs["color"]
                ).shift([group_x_offset, 0, 0])
            )
        group_x_offset += group_spacing
        remaining -= in_group
    result = VGroup(*lines)
    fit_width(result)
    return result


def build_label(text: str, style: str = "primary") -> Text:
    label = Text(text, color=resolve_style(style)["color"])
    fit_width(label)
    return label
