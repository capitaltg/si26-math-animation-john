from manim import UP, FadeOut, Group, Scene, Text, Transform, Write


class ChainedScene(Scene):
    params = None
    draw_fn = None
    continues_from = None
    continue_fn = None
    chain_range_fn = None

    def _items_continue(self, previous, current):
        return (
            self.continues_from is not None
            and self.continue_fn is not None
            and self.continues_from(previous, current)
        )

    def construct(self):
        if self.params is None or self.draw_fn is None:
            raise ValueError("ChainedScene requires params and draw_fn before construct() runs")
        items = self.params.items
        item_count = len(items)
        caption = None
        index = 0

        while index < item_count:
            item = items[index]
            continuing = index > 0 and self._items_continue(items[index - 1], item)

            if not continuing:
                if index:
                    # Group (not VGroup) because self.mobjects can include non-VMobject
                    # placeholders left behind by Wait animations (e.g. from scene.wait()
                    # calls inside draw_fn), which VGroup would reject.
                    self.play(FadeOut(Group(*self.mobjects)))

                run_end = index
                while (
                    run_end + 1 < item_count
                    and self._items_continue(items[run_end], items[run_end + 1])
                ):
                    run_end += 1
                value_range = (
                    self.chain_range_fn(items[index : run_end + 1])
                    if run_end > index and self.chain_range_fn is not None
                    else None
                )

                caption = Text(f"Problem {index + 1} of {item_count}").to_edge(UP)
                self.play(Write(caption))
                if self.chain_range_fn is not None:
                    self.draw_fn(self, item, value_range=value_range)
                else:
                    self.draw_fn(self, item)
            else:
                new_caption = Text(f"Problem {index + 1} of {item_count}").to_edge(UP)
                self.play(Transform(caption, new_caption))
                self.continue_fn(self, item)

            continues_to_next = (
                index + 1 < item_count
                and self._items_continue(item, items[index + 1])
            )
            if not continues_to_next:
                self.play(FadeOut(caption))

            self.wait(0.5)
            index += 1
