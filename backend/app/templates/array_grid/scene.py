from manim import *


def draw_array_grid(scene, params):
    dots = VGroup()
    for r in range(params.rows):
        for c in range(params.cols):
            dot = Dot(radius=0.15, color=BLUE)
            dot.move_to([c * 0.6, -r * 0.6, 0])
            dots.add(dot)
    dots.move_to(ORIGIN)

    label = Text(f"{params.rows} x {params.cols}").to_edge(UP)

    scene.play(Write(label))
    scene.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))
    scene.wait(1)


class ArrayGridScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("ArrayGridScene.params must be set before construct() runs")
        draw_array_grid(self, self.params)


from app.templates._shared.chained_scene import ChainedScene


class ChainedArrayGridScene(ChainedScene):
    draw_fn = staticmethod(draw_array_grid)
