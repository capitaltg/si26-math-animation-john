from manim import BLUE, GRAY, GREEN, ORANGE, PURPLE, RED, TEAL

_STYLE_TABLE = {
    "primary": {"color": BLUE, "stroke_width": 3},
    "secondary": {"color": PURPLE, "stroke_width": 3},
    "accent": {"color": ORANGE, "stroke_width": 3},
    "muted": {"color": GRAY, "stroke_width": 2},
    "success": {"color": GREEN, "stroke_width": 3},
    "warning": {"color": RED, "stroke_width": 3},
}


SEMANTIC_PALETTES = {
    "ocean": {
        "neutral": GRAY,
        "structure": BLUE,
        "focus": ORANGE,
        "conclusion": GREEN,
        "constraint": RED,
    },
    "violet": {
        "neutral": GRAY,
        "structure": PURPLE,
        "focus": ORANGE,
        "conclusion": GREEN,
        "constraint": RED,
    },
    "teal": {
        "neutral": GRAY,
        "structure": TEAL,
        "focus": ORANGE,
        "conclusion": GREEN,
        "constraint": RED,
    },
}


def resolve_style(token: str) -> dict:
    return dict(_STYLE_TABLE[token])


def resolve_semantic_style(palette: str, role: str) -> dict:
    return {"color": SEMANTIC_PALETTES[palette][role], "stroke_width": 3}
