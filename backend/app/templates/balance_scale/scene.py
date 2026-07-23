from manim import *


def draw_balance_scale(scene, params):
    left_a, left_b = params.left_terms
    right = params.right_total

    beam = Rectangle(width=6, height=0.2, fill_opacity=1.0, color=GRAY).move_to(UP * 0.5)
    fulcrum = Triangle(color=GRAY).scale(0.5).next_to(beam, DOWN, buff=0)
    left_pan = Circle(radius=0.5, color=BLUE).move_to(beam.get_left() + DOWN * 1.2)
    right_pan = Circle(radius=0.5, color=BLUE).move_to(beam.get_right() + DOWN * 1.2)

    left_label = Text(f"{left_a} + {left_b}").scale(0.6).move_to(left_pan)
    right_label = Text(f"{right}").scale(0.6).move_to(right_pan)

    scene.play(Create(beam), Create(fulcrum))
    scene.play(Create(left_pan), Create(right_pan))
    scene.play(Write(left_label), Write(right_label))

    equation = Text(f"{left_a} + {left_b} = {right}").scale(0.8).to_edge(DOWN)
    scene.play(Write(equation))
    scene.wait(1)


class BalanceScaleScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("BalanceScaleScene.params must be set before construct() runs")
        draw_balance_scale(self, self.params)
