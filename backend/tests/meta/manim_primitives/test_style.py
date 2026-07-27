import pytest

from app.meta.dsl.animation import StyleToken
from app.meta.manim_primitives.style import resolve_style


def test_every_style_token_resolves():
    for token in ("primary", "secondary", "accent", "muted", "success", "warning"):
        style = resolve_style(token)
        assert "color" in style
        assert "stroke_width" in style


def test_style_tokens_are_visually_distinct():
    colors = {resolve_style(token)["color"] for token in
               ("primary", "secondary", "accent", "muted", "success", "warning")}
    assert len(colors) == 6
