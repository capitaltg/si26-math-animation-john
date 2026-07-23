from manim import UP, FadeOut, Group, Scene, Text, Write


class ChainedScene(Scene):
    params = None
    draw_fn = None

    def construct(self):
        if self.params is None or self.draw_fn is None:
            raise ValueError("ChainedScene requires params and draw_fn before construct() runs")
        items = self.params.items
        for index, item in enumerate(items):
            if index:
                # Group (not VGroup) because self.mobjects can include non-VMobject
                # placeholders left behind by Wait animations (e.g. from scene.wait()
                # calls inside draw_fn), which VGroup would reject.
                self.play(FadeOut(Group(*self.mobjects)))
            caption = Text(f"Problem {index + 1} of {len(items)}").to_edge(UP)
            self.play(Write(caption))
            self.draw_fn(self, item)
            self.play(FadeOut(caption))
            self.wait(0.5)
