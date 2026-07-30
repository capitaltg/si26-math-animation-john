from app.meta.v3.ordered_values import measure_ordered_values


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        widths = {"3": 10, "5": 10, "6": 10, "8": 10, "9": 10, "12": 22, "15": 22}
        return widths[text], 20


def test_median_item_anchor_uses_eight_bounds_not_row_center():
    visual = measure_ordered_values(
        ref="values",
        values=["3", "5", "6", "8", "9", "12", "15"],
        measurer=LiteralTextMeasurer(),
        gap=8,
    )
    item_bottom = visual.anchor(part="item", index=3, name="bottom")
    row_bottom = visual.anchor(part=None, index=None, name="bottom")
    assert item_bottom.x != row_bottom.x
    assert item_bottom.x == visual.parts[("item", 3)].bounds.center.x
