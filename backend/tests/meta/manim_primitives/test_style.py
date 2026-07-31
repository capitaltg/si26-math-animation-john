import pytest

from app.meta.dsl.animation import StyleToken
from app.meta.manim_primitives.style import resolve_semantic_style, resolve_style


def test_every_style_token_resolves():
    for token in ("primary", "secondary", "accent", "muted", "success", "warning"):
        style = resolve_style(token)
        assert "color" in style
        assert "stroke_width" in style


def test_style_tokens_are_visually_distinct():
    colors = {resolve_style(token)["color"] for token in
               ("primary", "secondary", "accent", "muted", "success", "warning")}
    assert len(colors) == 6


def test_semantic_palette_resolves_every_stable_role():
    for palette in ("ocean", "violet", "teal"):
        for role in ("neutral", "structure", "focus", "conclusion", "constraint"):
            style = resolve_semantic_style(palette, role)
            assert "color" in style
            assert style["stroke_width"] == 3
