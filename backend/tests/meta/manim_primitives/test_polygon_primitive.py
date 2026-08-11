"""M22 polygon + rotate primitives."""

import math

import pytest


def test_build_polygon_returns_a_manim_polygon_with_matching_vertices():
    from manim import Polygon
    from app.meta.manim_primitives.visuals import build_polygon

    verts = [(0.0, 0.0), (2.0, 0.0), (1.0, 1.5)]
    mobject = build_polygon(
        verts,
        stroke_color="#000000", fill_color="#000000",
        fill_opacity=0.1, stroke_width=2.0,
    )
    assert isinstance(mobject, Polygon)
    # Manim stores 3D points; z is 0 for our 2D polygon.
    points = [tuple(round(c, 6) for c in mobject.get_vertices()[i]) for i in range(3)]
    assert points == [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.5, 0.0)]


def test_rotate_polygon_returns_a_rotate_animation():
    from manim import Polygon, Rotate
    from app.meta.manim_primitives.motions import rotate_polygon
    from app.meta.manim_primitives.visuals import build_polygon

    tri = build_polygon(
        [(0.0, 0.0), (2.0, 0.0), (1.0, 1.5)],
        stroke_color="#000", fill_color="#000",
        fill_opacity=0.0, stroke_width=1.0,
    )
    anim = rotate_polygon(
        tri, angle_rad=math.radians(90),
        about_scene_point=(0.0, 0.0, 0.0), run_time=0.8,
    )
    assert isinstance(anim, Rotate)
    assert anim.run_time == pytest.approx(0.8)
