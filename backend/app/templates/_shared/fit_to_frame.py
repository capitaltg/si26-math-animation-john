from manim import config


def fit_width(mobject, max_width=None):
    max_width = config.frame_width - 1 if max_width is None else max_width
    if mobject.width > max_width:
        mobject.width = max_width
    return mobject
