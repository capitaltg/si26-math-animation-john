# Array-grid chain input and layout design

## Goal

Fix two contract mismatches in multiplicative array-grid chains:

1. Generic chains such as `24 ÷ 3 × 2` must be extractable without asking the
   language model to invent a grounded `rows × cols` factorization.
2. Exact transitions such as a `2 × 3` grid divided by `3` must be allowed to
   change from `2 × 3` to `1 × 2` instead of retaining a fixed column count.

Existing static `{rows, cols}` inputs must remain valid. Existing chain inputs
that use `{rows, cols, steps}` must also continue to work.

## Parameter contract

`ArrayGridParams` will support two preferred input modes and one legacy mode:

- Static grid: `rows` and `cols`, with no `steps`.
- Multiplicative chain: `start` and one to three `steps`, with no required
  display dimensions.
- Legacy multiplicative chain: `rows`, `cols`, and `steps`; its canonical start
  is `rows * cols`.

Validation will reject partial dimensions, an input with neither a usable
static grid nor a chain start, and conflicting inputs that provide both
`start` and display dimensions. Field descriptions will tell the extraction
model to use `start` for chains and reserve `rows`/`cols` for source-stated
static arrays.

The model will expose a canonical starting-total method so guards, scenes, and
grounding do not each reinterpret the input shape.

## Grounding

New chain inputs ground only the source-provided `start` and step factors.
Display dimensions are derived locally and never appear in the extracted
parameters.

Legacy chain inputs retain the current default grounding behavior for their
source-provided `rows`, `cols`, and factors. No grounding exemption will allow
the language model to invent dimensions.

## Deterministic grid layout

A shared array-grid helper will map each positive total to a renderable
`(rows, cols)` pair:

1. Enumerate factor pairs whose axes are both at most `MAX_GRID_AXIS`.
2. Choose the pair with the smallest difference between its axes.
3. Use a stable orientation, with `rows <= cols`, to make tests and renders
   deterministic.
4. Reject a total when no factor pair satisfies the axis bound, even if the
   total is below `MAX_GRID_TOTAL`.

For example:

- `24` becomes `4 × 6`.
- `8` becomes `2 × 4`.
- `16` becomes `4 × 4`.
- `13` is rejected because its only grid is `1 × 13`, which exceeds the
  12-cell axis bound.

The compatibility guard will evaluate the complete multiplicative sequence
and require every total to have a renderable factor pair. It will no longer
require a fixed column count.

## Rendering

The array-grid scene will:

1. Resolve the canonical starting total.
2. Compute all totals through the shared multiplicative evaluator.
3. Derive a fresh grid layout for every total.
4. transition the dots and running-total label with `ReplacementTransform`.
5. Preserve deterministic operation captions such as `24 ÷ 3 = 8`.

Static grids retain their current label and rendering behavior.

## Classification and extraction

The classifier contract will continue to advertise exact positive whole-number
multiplicative chains. Its wording will clarify that every state must fit a
renderable array grid.

The extraction schema descriptions will explicitly distinguish a chain's
source-stated `start` from a static array's source-stated `rows` and `cols`.
Python remains the only component that computes totals and presentation
factorizations.

## Error handling

Pydantic validation will surface:

- partial `rows`/`cols`;
- missing static dimensions;
- missing chain start;
- conflicting `start` and `rows`/`cols`;
- non-positive inputs;
- non-exact division;
- non-positive intermediate totals;
- totals above the cell bound; and
- totals with no factor pair inside the axis bound.

These errors continue through the existing template-mismatch fallback path.

## Tests

Regression coverage will be added before production changes:

- `{start: 24, steps: [÷3, ×2]}` validates and grounds against source text
  containing only `24`, `3`, and `2`.
- Legacy `{rows: 2, cols: 3, steps: [÷3]}` remains accepted.
- The layouts for `6 → 2` change from `2 × 3` to `1 × 2`.
- Each state in `24 → 8 → 16` receives its deterministic factor pair.
- A total such as `13` fails with a renderability error.
- Static `{rows, cols}` behavior and labels remain unchanged.
- Existing caption, ghost-mobject, render-smoke, extraction, and grounding
  tests continue to pass.

