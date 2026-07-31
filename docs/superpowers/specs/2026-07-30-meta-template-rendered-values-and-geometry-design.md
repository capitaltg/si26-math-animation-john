# Meta-template Rendered Values and Geometry

## Problem

The approved `rectangle_perimeter` demo template renders parameter placeholders
literally and never displays its computed numeric answer. Its animation document
contains static labels such as `{length} cm`, `{width} cm`, and
`{2*(length+width)} cm`, while the renderer passes label text directly to
Manim's `Text` constructor. The separately stored `answer_expression` is
compiled for mathematical validity but has no required connection to any
visible animation node.

The same template represents the rectangle's dimensions with tally marks. The
closed animation DSL does not contain a rectangle primitive, so the generator
can only approximate the geometry with generic primitives such as grids,
objects, or tallies. The draft-generation prompt describes syntax and layout
requirements but provides no semantic rule favoring geometric visuals for
geometry problems.

The end-to-end demo test verifies that a nonblank MP4 renders and that the
answer expression independently evaluates to the expected number. It does not
verify that parameter values or the answer appear in the rendered scene, which
allowed this defective draft to pass validation and approval.

## Goal

Make future generated meta-templates safely display evaluated parameter values
and answers, provide a proportional rectangle visual with evaluated dimension
annotations, and deterministically reject drafts that contain literal
placeholder syntax or omit their answer from the animation.

## Non-goals

- Mutating an already approved template version or its immutable artifact.
- General-purpose Python-style string interpolation.
- Supporting arbitrary mathematical markup or LaTeX supplied by the generator.
- Inferring the best visual with computer vision or pixel-level semantic checks.
- Guaranteeing that every generated geometry animation is aesthetically ideal.
- Adding disappear, replacement, or scene-transition primitives.

## Design

### Animation document version

The corrected contract will use `animation_version: 2`. The parser and renderer
continue to accept version 1 documents so already published versions remain
loadable. Version 2 enables the new visual nodes and activates the visible
answer and static-placeholder invariants.

Draft generation will request version 2 for every new proposal. Version 1 is a
legacy read path only and will not satisfy the publication contract for a newly
generated or refined draft.

### Evaluated expression labels

Add an `expression_label` animation node with these bounded fields:

- `ref`: the existing optional producing-reference field.
- `expression`: an existing numeric `ExpressionNode`.
- `prefix`: static text with the existing label-length bound.
- `suffix`: static text with the existing label-length bound.
- `role`: either `working` or `answer`.
- `style`: an existing style token.

The animation compiler will compile the node's expression against the known
parameter fields. At render time it will evaluate the expression with the
existing bounded evaluator, format an integer as digits and a non-whole
fraction as `numerator/denominator`, concatenate the static prefix and suffix,
and build an ordinary Manim label. The node remains compatible with existing
row, column, overlay, alignment, appearance, and shared-layout rules because it
is a producing visual.

This node deliberately accepts one expression rather than parsing expressions
from strings. A generated template can display `8 cm`, `3 cm`, or
`= 22 cm` without introducing an executable or ambiguous interpolation
language.

### Visible-answer invariant

`compile_draft_documents` will require at least one `expression_label` whose
role is `answer` and whose expression is structurally equal to the draft's
top-level `answer_expression`. If no matching node exists, compilation raises
`DslValidationError` with code `answer_not_displayed`.

The check binds the already validated mathematical answer to visible scene
content. A working-expression label containing a parameter value does not
satisfy the invariant, and an answer-role label containing a different
expression is rejected.

### Static-placeholder rejection

In version 2 documents, static `label` text and the static `prefix` and `suffix`
portions of an `expression_label` will reject brace-delimited placeholder-like
fragments such as `{length}` or `{2*(length+width)}`. Compilation raises
`DslValidationError` with code `unsupported_text_placeholder` and directs the
author to use `expression_label`.

The check is limited to brace-delimited fragments rather than banning braces
entirely, preserving ordinary text that may legitimately mention braces. No
runtime interpolation fallback will be added.

### Rectangle visual

Add a `rectangle` animation node with:

- `length`: an existing numeric `ExpressionNode`.
- `width`: an existing numeric `ExpressionNode`.
- `unit`: bounded static text, defaulting to an empty string.
- `style`: an existing style token.
- `ref`: the existing optional producing-reference field.

The renderer evaluates both dimensions and requires positive values. The visual
builder creates one Manim `Rectangle`, scales its aspect ratio proportionally
within fixed maximum width and height bounds, and adds horizontal and vertical
braces labeled with the evaluated dimensions and unit. Extreme ratios are
clamped only for display legibility; annotation values always retain the true
mathematical dimensions. The returned `VGroup` participates in the existing
fit-to-frame and shared-layout behavior.

The node represents geometric dimensions directly. A `grid` remains available
for arrays and area models, while `tally_marks` remains available for counting;
neither is removed.

### Generator guidance

The draft-generation prompt will state:

- Static labels do not interpolate braces.
- Dynamic parameter values and computed results use `expression_label`.
- Every draft must include an answer-role `expression_label` matching
  `answer_expression`.
- Geometry problems should use the most semantically matching geometry
  primitive; rectangle length/width problems should use `rectangle`, not tally
  marks or object sets.

The deterministic compiler rules remain authoritative. Prompt guidance improves
first-pass generation but is not the only protection.

### Rendering and compatibility

The dynamic renderer already receives field values and evaluates expressions
for visual nodes, so `expression_label` and `rectangle` use the same execution
path without introducing a new data channel.

Existing version 1 animation documents still deserialize and render through the
legacy path. Existing published versions therefore remain immutable and
loadable, including the defective demo version; they are not silently rewritten.
New and refined drafts use version 2 and must satisfy the corrected publication
contract. The disposable demo database must be reset, or the template must be
refined and republished, to observe the fix.

## Testing

Focused tests will prove:

1. Version 1 documents remain loadable without the version 2 invariants.
2. An expression label renders integer and fractional values from real
   expression evaluation.
3. Expression labels compile only when all referenced fields exist.
4. Placeholder-like static label text is rejected in version 2.
5. A version 2 draft without an answer-role expression label fails with
   `answer_not_displayed`.
6. A draft whose answer-role expression differs from `answer_expression` fails.
7. A matching visible-answer expression compiles.
8. The rectangle builder produces one rectangle with dimension annotations and
   preserves the intended aspect ratio within display bounds.
9. Non-positive rectangle dimensions fail deterministically.
10. The generated perimeter proposal used by the end-to-end demo contains a
   rectangle, evaluated length and width labels, and an answer-role expression
   label matching the answer expression.
11. The complete demo still validates, publishes, reuses, and renders an MP4
    whose final frame is nonblank.

Targeted DSL, renderer, primitive, validation, and generation tests run first.
The complete backend suite runs after those pass.

## Risks and mitigations

Structural equality is intentionally strict. Two algebraically equivalent but
structurally different answer expressions will not match; the generator can
reuse the exact answer-expression JSON, and strict matching avoids adding a
symbolic algebra system.

Very large dimensions cannot be drawn at literal scale. Fixed display bounds
and aspect-ratio clamping keep the diagram legible while explicit annotations
preserve the true values.

The prompt may still make poor aesthetic choices elsewhere. The new compiler
invariants guarantee the demonstrated values and answer are real, while the
rectangle primitive gives the generator a semantically correct option for this
demo.
