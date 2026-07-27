from manim import DOWN, LEFT, ORIGIN, RIGHT, UP, VGroup

from app.templates._shared.fit_to_frame import fit_to_frame, fit_width

_EDGE_VECTORS = {"left": LEFT, "right": RIGHT, "top": UP, "bottom": DOWN}


def build_row(children: list, gap: float = 0.25) -> VGroup:
    group = VGroup(*children).arrange(RIGHT, buff=gap)
    fit_width(group)
    return group


def build_column(children: list, gap: float = 0.25) -> VGroup:
    group = VGroup(*children).arrange(DOWN, buff=gap)
    fit_to_frame(group)
    return group


def build_overlay(children: list) -> VGroup:
    group = VGroup(*children)
    anchor = children[0].get_center()
    for child in children[1:]:
        child.move_to(anchor)
    return group


def build_align(child, edge: str):
    if edge == "center":
        child.move_to(ORIGIN)
        return child
    child.to_edge(_EDGE_VECTORS[edge])
    return child


def build_padding(child, amount: float = 0.25):
    child.scale(1 / (1 + amount))
    return child


def build_sequence(scene, steps: list, step_duration: float) -> None:
    for step in steps:
        step()
        scene.wait(step_duration)


def build_parallel(scene, steps: list) -> None:
    animations = [result for step in steps if (result := step()) is not None]
    if animations:
        scene.play(*animations)
