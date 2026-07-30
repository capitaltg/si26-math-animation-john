# Meta-template Demo Fixture Deck Design

## Goal

Create a four-slide PowerPoint fixture that reliably presents one concrete K–8
problem per slide, with every problem outside the application's current static
template contracts.

The deck supports both halves of the meta-template demonstration: generating a
new rectangle-perimeter template and reusing it for a second rectangle.

## Communication Job

By the end, a demo audience should understand that the application can detect
multiple legitimate math-problem shapes it cannot yet animate, learn one shape
through guarded human review, and reuse the resulting template.

## Output

`eval/fixtures/meta_template_unsupported_shapes_deck.pptx`

The deck is a test fixture, not a presenter narrative. It has no cover, agenda,
answers, notes, implementation labels, or explanatory footer. Every slide is
independently usable by the document-analysis pipeline.

## Content

### Slide 1 — Rectangle perimeter seed

Category label: `GEOMETRY • GRADE 4`

Problem:

> A rectangle is 8 centimeters long and 3 centimeters wide. What is its perimeter?

Expected answer for the reviewer, not displayed on-slide: `22`.

### Slide 2 — Rectangle perimeter reuse

Category label: `GEOMETRY • GRADE 4`

Problem:

> A rectangle is 10 centimeters long and 4 centimeters wide. What is its perimeter?

Expected answer for the reviewer, not displayed on-slide: `28`.

### Slide 3 — Median

Category label: `DATA • GRADE 6`

Problem:

> What is the median of 3, 5, 6, 8, 9, 12, and 15?

Expected answer for the reviewer, not displayed on-slide: `8`.

### Slide 4 — Metric conversion

Category label: `MEASUREMENT • GRADE 5`

Problem:

> A hiking trail is 2.75 kilometers long. How many meters long is the trail?

Expected answer for the reviewer, not displayed on-slide: `2750`.

## Visual Design

Use the bundled Codex Grid design language:

- 16:9 white canvas;
- black Helvetica Neue/Arial typography;
- light-gray structural regions;
- one restrained blue accent per slide;
- at least 35pt slide titles and substantially larger problem text;
- no decorative images, icons, charts, diagrams, or extra instructional copy.

Adapt sparse stacked-text layouts from the Codex Grid library while keeping the
problem text as the dominant read. Alternate the accent placement subtly across
slides so the deck does not look like four duplicated screenshots, but preserve
consistent margins and hierarchy.

## Extraction Constraints

- Exactly one question per slide.
- The visible text must contain the full problem statement in one text flow.
- Category labels must remain short and cannot resemble additional questions.
- Do not display formulas, worked steps, hints, standards codes, or answers.
- Do not introduce multiple text fragments that could be mistaken for separate
  candidate problems.

## Implementation and QA

Create the deck with `@oai/artifact-tool` in an external temporary workspace.
Only the final `.pptx` is written to the repository fixture directory.

Before delivery:

1. render all four slides to PNG;
2. inspect each slide at full size;
3. inspect a four-slide montage for consistency;
4. run slide overflow/overlap validation;
5. verify extracted text contains exactly the intended label and problem on
   each slide;
6. confirm the final PowerPoint opens and contains four slides.
