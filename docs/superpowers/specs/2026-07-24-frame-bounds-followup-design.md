# Frame Bounds Follow-up Design

## Goal

Ensure every mobject introduced by the number-line and text-card templates
remains inside Manim's safe frame area for all valid template parameters.

## Root Cause

The current `fit_width` helper constrains only an object's dimensions along the
x-axis. Text-card body content can therefore exceed the frame height, and the
number-line labels created separately from the fitted `NumberLine` can exceed
the frame horizontally.

## Design

Extend the shared frame-fitting utility with a uniform-scaling operation that
accepts optional maximum width and height. It will compute the limiting scale
factor and shrink only when necessary, preserving each mobject's aspect ratio.

For text cards, place the headline first, calculate the safe vertical space
remaining below it, fit the body group to both the safe frame width and that
height, and then position the body beneath the headline.

For number lines, keep fitting the `NumberLine` itself and also fit each
start/result label to the safe frame width before placing it above its marker.
The template will continue accepting the same parameter values.

## Testing

Add regression coverage that:

- Builds a text card with enough short lines to overflow vertically and asserts
  all four body bounds are inside the frame.
- Builds a number line with a valid large start value and asserts the initial
  and transformed labels stay inside the frame.
- Retains the existing horizontal-overflow coverage.

Run the focused template tests followed by the full backend test suite before
committing the implementation.

## Non-goals

- Wrapping or paginating text.
- Changing template parameter validation.
- Redesigning the scene layouts or animation timing.
