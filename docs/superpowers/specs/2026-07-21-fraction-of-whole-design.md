# Fraction-of-Whole Template Design

**Status:** Approved in conversation on 2026-07-21.

## Goal

Add a `fraction_of_whole` template: a static single-fraction visual (shaded
part of one whole, no operations). This closes the largest template gap found
against the eval set — `g1 fractions.pptx` is built entirely on "what fraction
is shaded" / "color 1/2 blue" content with zero arithmetic, which no existing
template (`number_line`, `array_grid`, `text_card`, `fraction_bar`,
`balance_scale`) structurally covers. `fraction_bar` requires 2-3 sequential
add/subtract steps; this template has no steps at all.

## Scope (v1)

- One whole per scene. `numerator` + `denominator` only.
- Proper fractions or an exact whole: `numerator <= denominator`. Improper
  fractions (e.g. `5/3`) are out of scope — they belong to a future
  fraction-number-line template, not this one.
- No repeat-count / multiple-wholes param. Deck slides that show several
  identical wholes to shade (e.g. g1's independent-practice pages) fall back
  to `text_card` for now; only a single fraction per scene is in scope.
- No comparison/multiple-choice rendering (e.g. g1's exit-ticket "point to the
  answer" slide) — out of scope, one static fraction per scene.

## Architecture

New standalone template (own `TemplateName`, params, guard, scene) plus a
shared rendering helper extracted from `fraction_bar`, so the two templates'
visuals stay pixel-consistent without duplicating the cell-drawing code.

```
backend/app/templates/fraction_of_whole/
  __init__.py
  params.py   # FractionOfWholeParams
  guard.py    # check_fraction_of_whole_compatibility
  scene.py    # FractionOfWholeScene(Scene)

backend/app/templates/_shared/
  fraction_cells.py   # new — extracted from fraction_bar/scene.py
```

Rejected alternatives:

- **Extend `fraction_bar` to accept 0 steps.** Least new code, but
  `fraction_bar`'s classification contract and guard are both written around
  a multi-step *process*; a static case bolted onto that contract muddies the
  classifier's reasoning and mixes two structural shapes under one template
  name.
- **New template, duplicate the cell-drawing code instead of sharing it.**
  Same isolation as the chosen approach, but the two visuals can silently
  drift apart over time since there's no shared source of truth for the
  rendering primitive.

## Shared rendering helper

`_shared/fraction_cells.py` extracts the cell-arranging logic currently
inlined in `fraction_bar/scene.py` (lines 18-24):

```python
from manim import VGroup, Rectangle, WHITE, RIGHT, ORIGIN

def build_fraction_cells(n_cells: int) -> VGroup:
    cell_width = min(0.6, 12.0 / n_cells)
    cells = VGroup()
    for _ in range(n_cells):
        cells.add(Rectangle(width=cell_width, height=0.8, stroke_color=WHITE))
    cells.arrange(RIGHT, buff=0).move_to(ORIGIN)
    return cells
```

`fraction_bar/scene.py` is refactored to call this instead of inlining it —
a pure extraction; its step-transition logic (running total, `Transform`
animations between values) is unchanged.

## Params and guard

```python
# params.py
class FractionOfWholeParams(BaseModel):
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=1, le=12)

    @model_validator(mode="after")
    def _check_guard(self):
        check_fraction_of_whole_compatibility(self)
        return self
```

```python
# guard.py
def check_fraction_of_whole_compatibility(params) -> None:
    if params.numerator > params.denominator:
        raise ValueError(
            f"Fraction {params.numerator}/{params.denominator} is improper — "
            "fraction_of_whole only renders proper fractions or a full whole"
        )
```

`denominator <= 12` matches `array_grid`'s per-axis cap and keeps cell width
sane — it mirrors `fraction_bar`'s existing `cell_width = min(0.6,
12.0/n_cells)` clamp, enforced up front instead of silently squishing.
`denominator <= 1` (0, 1, negative) is already rejected by the `Field(gt=1)`
constraint before the guard runs, so it can never reach the guard.

`numerator <= denominator` allows exact-whole shading (`4/4`) since some
decks (e.g. g1's "quarters" slide) discuss a whole in terms of its own
denominator. There is no `steps` field, no running total, no negative-value
check — nothing sequential exists to validate.

## Scene rendering

```python
# fraction_of_whole/scene.py
from manim import Scene, Create, Write, Text
from app.templates._shared.fraction_cells import build_fraction_cells

class FractionOfWholeScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("FractionOfWholeScene.params must be set before construct() runs")

        numerator = self.params.numerator
        denominator = self.params.denominator

        cells = build_fraction_cells(denominator)
        self.play(Create(cells))

        label = Text(f"{numerator}/{denominator}").scale(0.6).next_to(cells, UP)
        self.play(Write(label))

        self.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(numerator)])
        self.wait(1)
```

## Registry, enum, and classification wiring

```python
# models/scene.py
class TemplateName(str, Enum):
    NUMBER_LINE = "number_line"
    ARRAY_GRID = "array_grid"
    TEXT_CARD = "text_card"
    FRACTION_BAR = "fraction_bar"
    BALANCE_SCALE = "balance_scale"
    FRACTION_OF_WHOLE = "fraction_of_whole"   # new
```

```python
# templates/registry.py
from app.templates.fraction_of_whole.params import FractionOfWholeParams
from app.templates.fraction_of_whole.scene import FractionOfWholeScene
...
_REGISTRY = {
    ...,
    TemplateName.FRACTION_OF_WHOLE: (FractionOfWholeScene, FractionOfWholeParams),
}
```

`classification.py`'s `_TEMPLATE_CONTRACTS` (classification.py:8) gains a new
entry, and the existing `fraction_bar` entry is tightened so the two don't
overlap in the classifier's reasoning:

```
- fraction_of_whole: a single static fraction shown as a shaded part of one whole
  (e.g. "what fraction is shaded", "color 1/2 blue"). No operation, no sequence —
  just naming or representing one fraction.
- fraction_bar: 2 to 3 sequential add/subtract steps on fractions sharing one
  denominator (e.g. repeated-addition word problems like "swims 1/4 mile a day,
  how far in 3 days"). Requires an actual operation across steps — a single
  static fraction belongs to fraction_of_whole instead.
```

`extraction.py` needs no changes — `extract_params` already works generically
off `params_cls.model_json_schema()`, so `FractionOfWholeParams`'s schema
(`numerator`, `denominator`) flows through automatically once `registry.py`
wires it in.

## Testing

Mirror the existing per-template test pattern in `backend/tests/templates/`:

- `test_fraction_of_whole_params.py`:
  - valid proper fraction passes (`1/2`, `3/4`)
  - `numerator == denominator` passes (full whole, `4/4`)
  - `numerator > denominator` raises
  - `denominator <= 1` raises (Pydantic-level, not guard)
  - `denominator > 12` raises
- Regression test that extracting `build_fraction_cells` out of
  `fraction_bar/scene.py` didn't change its rendered cell count/width for an
  existing case.
- Manual check: re-run `eval/run_eval.py` against `g1 fractions.pptx`
  post-implementation and confirm candidates that previously fell to
  `text_card` (e.g. slide 8, "Color 1/2 blue") now classify as
  `fraction_of_whole` and pass the guard.

## Non-goals

- Multiple wholes per scene (repeat-count param).
- Circle/pie rendering (bar only for v1; shape param is a documented
  fast-follow, not part of this design).
- Improper fractions and fraction-number-line placement (separate future
  template).
- Multiple-choice / comparison rendering.
