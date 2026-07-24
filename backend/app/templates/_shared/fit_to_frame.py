from manim import config

FRAME_MARGIN = 0.5


def fit_to_box(mobject, *, max_width=None, max_height=None):
    if max_width is not None and max_width <= 0:
        raise ValueError("max_width must be positive")
    if max_height is not None and max_height <= 0:
        raise ValueError("max_height must be positive")

    scale_factor = 1
    if max_width is not None and mobject.width > max_width:
        scale_factor = min(scale_factor, max_width / mobject.width)
    if max_height is not None and mobject.height > max_height:
        scale_factor = min(scale_factor, max_height / mobject.height)
    if scale_factor < 1:
        mobject.scale(scale_factor)
    return mobject


def safe_width():
    return config.frame_width - 2 * FRAME_MARGIN


def safe_height():
    return config.frame_height - 2 * FRAME_MARGIN


def fit_width(mobject, max_width=None):
    max_width = safe_width() if max_width is None else max_width
    return fit_to_box(mobject, max_width=max_width)


def fit_to_frame(mobject, *, max_width=None, max_height=None):
    max_width = safe_width() if max_width is None else max_width
    max_height = safe_height() if max_height is None else max_height
    return fit_to_box(mobject, max_width=max_width, max_height=max_height)
