from manim import BLUE, GRAY, GREEN, ORANGE, PURPLE, RED

_STYLE_TABLE = {
    "primary": {"color": BLUE, "stroke_width": 3},
    "secondary": {"color": PURPLE, "stroke_width": 3},
    "accent": {"color": ORANGE, "stroke_width": 3},
    "muted": {"color": GRAY, "stroke_width": 2},
    "success": {"color": GREEN, "stroke_width": 3},
    "warning": {"color": RED, "stroke_width": 3},
}


def resolve_style(token: str) -> dict:
    return dict(_STYLE_TABLE[token])
