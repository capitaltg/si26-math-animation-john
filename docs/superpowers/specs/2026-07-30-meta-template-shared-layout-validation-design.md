# Meta-template shared-layout validation

## Problem

Dynamic meta-templates can compile and pass preview validation while rendering
several labels and visuals at the center of the frame. A `sequence` controls
time but does not position its producing children. Each independently built
visual therefore retains Manim's default origin, and successive `appear`
actions leave the earlier visuals on screen. The final preview is nonblank, so
the existing pixel-presence check accepts an illegible pile of objects.

The observed `rectangle_perimeter` revision demonstrates this exact pattern:
its root sequence independently builds and reveals a title, grids, headings,
and formula labels without placing them in a shared row or column.

## Goal

Reject a dynamic animation document at compile time when it persistently
reveals multiple independent visual trees without an explicit shared spatial
layout.

The validation error must be specific enough for draft generation or refinement
to correct the animation rather than merely reporting a generic compile
failure.

## Non-goals

- Automatically arranging generated visuals at render time.
- General pixel-level collision detection.
- Rejecting intentional overlays.
- Adding disappearance or replacement animation primitives.
- Repairing drafts already stored in the database.

## Design

### Shared-layout rule

The animation compiler will track the producing reference targeted by every
`appear` node. For documents with zero or one distinct appeared visual, no new
restriction applies.

When two or more distinct visual references are appeared, each appeared visual
must belong to the same explicit spatial-layout tree. A spatial-layout tree is
rooted at a `row`, `column`, `overlay`, `align`, or `padding` node and includes
that node and all producing descendants nested beneath it.

The rule succeeds when one layout tree contains every appeared visual. This
allows templates to:

- Build one column containing a title, diagram, and formula, then appear the
  parent column.
- Build that column and progressively appear its already-positioned descendant
  references.
- Use nested rows, columns, padding, alignment, or intentional overlays within
  the shared tree.

The rule rejects a sequence that independently creates and appears a title,
grid, and formula even if an unrelated layout node exists elsewhere.

On failure, compilation raises `DslValidationError` with code
`missing_shared_layout` and a detail message that identifies the appeared
references requiring a common row/column/layout ancestor.

### Generator guidance

The draft-generation system prompt will explicitly distinguish temporal
sequencing from spatial layout. It will require multiple persistent visuals to
be constructed under one shared layout tree before they are appeared, and warn
that independent sequence children overlap at the frame origin.

The prompt will continue to require `appear` and `wait`; this change clarifies
how those actions interact with arranged mobjects.

### Validation flow

No database or API changes are required. `compile_animation_document` already
runs before fixture and preview rendering. The new typed compile error will
flow through the existing validation report as `compile_error`, set the draft
to `failed_validation`, and prevent it from reaching human review or approval.

## Testing

Compiler regression tests will prove:

1. The observed pattern—multiple independently produced and appeared labels or
   grids in a sequence—fails with `missing_shared_layout`.
2. The equivalent visuals nested under one column compile successfully when
   their positioned descendant refs are progressively appeared.
3. Appearing a single independent visual remains valid.
4. Nested layouts retain one shared spatial root and remain valid.
5. Two separate layout trees whose descendants are both appeared are rejected.

A draft-generation unit test will assert that the tool-call system prompt
contains the shared-layout requirement and explains that a sequence does not
position visuals.

Targeted compiler and draft-generation tests will run first, followed by the
complete backend test suite.

## Risks and mitigations

The structural rule does not guarantee perfect aesthetics inside a valid
layout, but it deterministically prevents the demonstrated origin-stacking
failure. Pixel collision analysis remains out of scope because legitimate
overlays and renderer-dependent glyph bounds make it unsuitable as the first
gate.

Progressively appearing descendants of a layout group is supported because
Manim's layout operation mutates the descendant positions before any `appear`
action runs. The compiler therefore evaluates common layout ancestry rather
than requiring only the parent group itself to be appeared.
