# Meta-template DSL v3 Foundation

**Date:** 2026-07-30  
**Status:** Approved design  
**Scope:** Replace the current generated-animation contract with a two-stage
teaching-plan compiler, an anchored scene graph, a bounded action escape hatch,
and deterministic pedagogical quality gates.

## Problem

The current meta-template animation DSL can produce mathematically correct and
renderable scenes, but it cannot reliably produce good explanations.

The median demo exposed three systemic failures:

1. Seven values were revealed through seven separate one-second fades, turning a
   simple setup into most of a sixteen-second clip.
2. The median value was constructed with accent styling, so it was orange before
   the animation had established or explained why it mattered.
3. The median callout was positioned against temporary geometry. Its parent
   layout subsequently moved the value row and callout independently, leaving
   the callout under the row's center rather than under the `8`.

The perimeter demo showed the same architectural limit in a different form. The
rectangle and dimensions could only be constructed and faded in; the generated
document had no bounded way to trace the boundary, emphasize opposite edge
pairs, or transform that visual reasoning into the perimeter expression.

These are not primarily prompt defects. The current runtime builds mobjects
recursively and then plays a small set of actions against them. It has no stable
post-layout anchor model, no explicit visual states, no teaching-level timeline,
and no quality definition beyond mathematical, schema, render, and fixture
validity.

## Decisions

- v3 uses a **hybrid authoring model**.
- Generated content primarily describes semantic teaching beats.
- A deterministic teaching compiler owns layout, anchoring, timing, style
  transitions, and standard motion.
- A bounded low-level escape hatch supports exceptional motion inside a beat.
- Simple animations target an adaptive **6–12 second** duration.
- Pedagogical quality failures block publication just like mathematical or
  structural failures.
- The visual language uses **controlled variation**: stable semantic meaning with
  concept-specific composition and motion.
- Backward compatibility with v1/v2 is out of scope. The current database is
  disposable for the demo, so v3 can replace the old generated-animation
  contract cleanly.

## Goals

1. Make generated animations explain mathematical structure rather than merely
   display labels.
2. Keep model output bounded, declarative, auditable, and deterministic after
   generation.
3. Resolve all cross-visual relations against final geometry.
4. Treat timing and emphasis as semantic state changes instead of construction
   properties.
5. Ensure every draft visible to a reviewer already passes deterministic math,
   safety, visual-quality, and render gates.
6. Make the median and perimeter demo slides concrete regression contracts for
   the foundation.

## Non-goals

- Generating arbitrary Python or Manim code.
- Preserving or migrating approved v1/v2 generated templates.
- Building a general-purpose motion-graphics editor.
- Adding unbounded coordinates, colors, easing functions, assets, or executable
  expressions to model output.
- Automatically judging whether a teaching strategy is the best possible
  pedagogy. v3 enforces a measurable quality floor; human review still confirms
  mathematical semantics and instructional suitability.

## Architecture

v3 separates generated teaching intent from executable scene mechanics:

```text
Generated TeachingPlan
          |
          v
Deterministic Teaching Compiler
  - validate intent
  - expand beats
  - instantiate semantic visuals
  - solve layout
  - resolve anchors and relations
  - schedule a 6–12 second timeline
  - apply a controlled visual recipe
          |
          v
Executable SceneProgram
  - stable scene graph
  - semantic child anchors
  - explicit visual states
  - timed action track
          |
          v
Deterministic Renderer + Rendered Quality Probes
```

Generated content chooses what to teach and may request bounded custom motion.
It never controls temporary geometry or invokes renderer code directly.

## Draft Documents

A v3 draft proposal retains the existing parameter schema, guard schema, answer
expression, classifier contract, and fixtures. It replaces the generated
`animation_document` with a `teaching_plan_document`.

After successful compilation, the draft also stores the deterministic
`scene_program_document` and `quality_report`. Persisting both makes preview and
publication reproducible and lets reviewers inspect the generated intent
separately from its compiled execution.

Conceptually:

```text
DraftProposalV3
  params_document
  guard_document
  answer_expression
  teaching_plan_document
  classifier_bullet
  fixtures

CompiledDraftV3
  teaching_plan_document
  scene_program_document
  validation_report
  quality_report
  preview_artifact
```

The database schema may use dedicated JSON columns for the teaching plan, scene
program, and quality report. Reusing the v2 `animation_document_json` column for
multiple meanings is explicitly avoided.

## Teaching Plan

The teaching plan is compact and semantic. It contains:

- one learning objective;
- one primary semantic visual;
- optional supporting visuals;
- one explanation strategy selected from a closed vocabulary;
- three to five ordered teaching beats;
- an explicit focus target and conclusion;
- a stable variation seed;
- optional bounded custom actions scoped to a specific beat.

### Beat vocabulary

The closed initial vocabulary is:

- `orient`: establish the mathematical object or question;
- `reveal`: introduce data or a visual collection;
- `organize`: rearrange, pair, partition, group, or otherwise expose structure;
- `focus`: direct attention to the mathematically relevant target;
- `derive`: map visible structure into a calculation or relationship;
- `conclude`: show the evaluated result and hold it for reading.

Not every plan must use every beat, but `conclude` is last and every plan has at
least one beat that establishes context before answer emphasis.

Each beat declares targets and instructional intent, not individual one-second
animations. For example:

```json
{
  "kind": "focus",
  "targets": [
    {
      "visual_ref": "values",
      "part": "item",
      "index": 3
    }
  ],
  "intent": "identify the middle value after the ordered collection is visible"
}
```

### Explanation strategies

The initial closed strategy vocabulary includes:

- group reveal;
- short meaningful stagger;
- pair elimination or pair comparison;
- boundary trace;
- partition;
- regroup;
- magnitude comparison;
- equation or representation transform.

The plan must choose a strategy compatible with its semantic visual. A
process-oriented concept cannot compile to a collection of static label fades.
If the current visual and strategy libraries cannot express the explanation,
generation fails privately instead of publishing a weak fallback.

## Semantic Visual Library

v3 keeps a bounded visual library but raises its abstraction level. It includes
general visuals and a small set of pedagogical composites.

Initial composites required by the demo are:

- `ordered_values`, exposing values, item identities, pair relationships, and a
  middle-item anchor;
- `rectangle_measurement`, exposing its outline, four directed edges, opposite
  edge pairs, dimension anchors, vertices, and a declared perimeter path.

Existing useful primitives such as number lines, grids, partitions, bars,
labels, and evaluated expressions remain available behind the compiler.

Every composite has:

1. a typed parameter contract;
2. intrinsic measurement;
3. one or more layout representations;
4. a documented set of semantic parts and anchors;
5. supported teaching strategies and actions;
6. renderer-independent tests for its geometry contract.

Generated plans reference semantic parts, never renderer-specific submobject
indices.

## Anchored Scene Graph

The compiler produces a stable scene graph in five phases:

1. **Instantiate:** build semantic visuals and measure intrinsic bounds.
2. **Solve layout:** place the complete visual hierarchy inside the frame.
3. **Resolve relations:** create callouts, braces, arrows, and paths against the
   final bounds of their targets.
4. **Schedule:** lower beats and custom actions into a bounded timeline.
5. **Render:** execute without changing the solved structural layout.

### Anchor references

Anchor references are typed values, not arbitrary coordinate strings. A
reference identifies:

- the owning visual;
- an optional semantic part and index;
- a named anchor such as `center`, `top`, `bottom`, `left`, or `right`.

For the median example, the target is conceptually:

```json
{
  "visual_ref": "values",
  "part": "item",
  "index": 3,
  "anchor": "bottom"
}
```

This resolves from the final glyph bounds of the `8`. It is not the center of
the complete value row and is not a coordinate copied before layout.

A relation retains ownership of its anchor reference throughout compilation.
The compiler rejects a collection-level anchor when a teaching beat identifies
a specific item. This prevents the exact row-center error observed in the demo.

Relations are solved after parent layouts so a parent cannot subsequently move
the target and callout independently.

## Visual States and Controlled Variation

Visuals have explicit semantic states. Initial construction does not determine
their eventual emphasis.

The stable semantic style roles are:

- `neutral`: supporting context;
- `structure`: the primary mathematical representation;
- `focus`: the item currently being discussed;
- `conclusion`: the established result;
- `constraint`: an invalid, excluded, or cautionary element.

The generated plan requests roles. It never supplies raw colors. An `emphasize`
action transitions a visual from its current state to `focus`; this prevents an
answer from appearing orange before the focus beat.

The compiler chooses a deterministic visual recipe using concept family, grade
band, content density, and the plan's stable seed. Variation may affect:

- composition: row, comparison, radial, path, partition, equation flow;
- motion grammar: grouped reveal, short stagger, trace, pair collapse,
  transform;
- density: font scale, spacing, explanatory labels, and pacing;
- one of a small set of accessible palettes.

Typography, semantic role meaning, contrast standards, frame margins, and
readability rules remain consistent. The same plan and seed always compile to
the same scene.

## Bounded Low-level Escape Hatch

A teaching beat may include custom actions only when its standard lowering
cannot express the requested move. The initial action vocabulary is:

- `reveal`: together or short stagger;
- `emphasize`: transition to a semantic focus role;
- `dim` or `restore`: change contextual salience;
- `draw`: reveal a declared outline;
- `trace`: traverse a declared path;
- `transform`: morph between compatible declared visuals;
- `move`: move a target along a declared path;
- `callout`: attach text to a typed anchor.

Custom actions:

- reference only declared visual IDs, semantic parts, anchors, and paths;
- use semantic style roles rather than raw color values;
- last between 0.15 and 2 seconds;
- consume the same total timeline budget as standard beat actions;
- cannot bypass answer-order, readability, collision, or salience gates;
- cannot contain coordinates, Python, Manim code, imports, paths, URLs, custom
  easing functions, or arbitrary renderer properties.

The compiler remains free to reject or normalize an otherwise valid custom
action when it conflicts with the teaching beat or total pacing.

## Adaptive Timeline

The timeline target is 6–12 seconds. Duration is allocated by teaching beat,
not by visual-object count.

Rules include:

- simple collections reveal together or with at most a 0.15-second item stagger;
- repeated homogeneous appearances are grouped unless sequential arrival carries
  mathematical meaning;
- every beat produces an observable state change;
- unexplained idle time is forbidden;
- a candidate value may receive focus during `focus` or `derive`, but the final
  evaluated-answer visual is introduced only during `conclude`;
- the conclusion is last and remains readable for at least 1.5 seconds;
- low-level actions remain inside their owning beat's allocation.

If a valid plan cannot fit the twelve-second ceiling without compromising the
minimum conclusion hold or action durations, it fails quality validation and
returns for private repair.

## Compiler Components

The teaching compiler is divided into independently testable units:

1. **Plan validator**  
   Validates document shape, references, beat order, strategy compatibility,
   answer timing, and custom-action limits.

2. **Beat expander**  
   Converts each teaching beat into semantic scene operations using the selected
   visual's supported strategies.

3. **Visual registry**  
   Instantiates semantic visuals and exposes their measurement, parts, anchors,
   paths, and supported operations.

4. **Layout solver**  
   Chooses a bounded composition and computes final visual geometry.

5. **Relation resolver**  
   Resolves typed item, edge, cell, vertex, and other semantic anchors after
   layout; checks callout placement and collisions.

6. **Timeline scheduler**  
   Allocates the adaptive duration, batches related actions, and guarantees
   temporal invariants.

7. **Style recipe resolver**  
   Applies a reproducible, accessible visual recipe while preserving semantic
   role meaning.

8. **Scene-program validator**  
   Enforces resource, security, layout, timing, salience, and concept-affordance
   rules on the compiled program.

9. **Renderer adapter**  
   Converts the scene program into Manim objects and animations without
   interpreting generated code.

10. **Rendered-quality probe**  
    Samples frames at beat boundaries and verifies the properties that require
    actual pixels or final renderer geometry.

No component needs to know how the model produced the plan. The renderer
receives only a validated scene program.

## Quality Gates

Quality failures block draft persistence for review.

### Pacing

- Duration is between 6 and 12 seconds.
- Simple repeated reveals are grouped.
- The conclusion hold is at least 1.5 seconds.
- There is no unexplained idle interval.

### Temporal semantics

- The answer is not initially styled as focus or conclusion.
- A candidate value receives answer-related focus only after context is
  established, and the evaluated-answer visual is introduced only in
  `conclude`.
- The conclusion is the last teaching beat.
- Every beat creates an observable visual change.

### Layout and anchors

- All final bounds fit within the safe frame.
- Text meets minimum readable size.
- Relations resolve to valid final semantic anchors.
- Item-specific callouts use item-specific anchors.
- Callouts do not collide with target content or unrelated visuals.
- Rendered anchor alignment remains within a centrally defined,
  resolution-normalized tolerance.

### Concept affordance

- A process-oriented plan uses at least one visible strategy compatible with its
  semantic visual.
- A perimeter explanation traces or emphasizes edges before deriving the
  formula.
- An ordered-values median explanation visibly organizes or focuses the middle
  item after presenting the collection.

### Salience

- Only intended targets own the `focus` role at a given time.
- Context remains legible without competing with the focus.
- Decorative motion cannot obscure or outrank mathematical content.

### Rendered evidence

Frame probes at beat boundaries verify:

- expected visuals are visible;
- frames are non-blank;
- style roles occur in the intended order;
- anchor relations remain aligned;
- collisions and clipping are absent;
- the evaluated final answer persists through the conclusion hold.

Stable failure codes include:

- `serial_simple_reveal`;
- `premature_answer_emphasis`;
- `collection_anchor_for_item`;
- `static_process_visual`;
- `conclusion_hold_too_short`;
- `callout_collision`;
- `timeline_over_budget`.

## Generation and Review Flow

The end-to-end flow is:

1. Generate a v3 teaching plan with params, guard, answer, classifier, and
   fixtures.
2. Validate plan intent and mathematical references.
3. Compile the plan into a scene program.
4. Run static math, security, resource, pacing, layout, salience, and
   affordance gates.
5. Render a preview and sampled beat-boundary frames.
6. Run rendered-quality gates.
7. Persist a reviewer-visible draft only when every gate passes.

When validation fails, the system creates a structured private repair report
containing:

- stable failure code;
- document or scene-program path;
- expected invariant;
- observed value or geometry;
- concise correction hint.

The prior teaching plan and complete structured report return to generation for
up to five private candidate attempts. Invalid candidates are not stored as
review drafts. If all attempts fail, the job records developer diagnostics and
moves to manual attention.

Reviewers see:

- the teaching objective and ordered beats;
- the compiled timeline;
- the preview;
- real fixtures;
- the quality report and passing evidence;
- the existing mathematical-semantics confirmation and template-name controls.

There is no reviewer workflow for copying automatic validation errors into
rejection feedback. Any draft accessible through the review list has already
passed automatic validation and can proceed to human approval once its real
fixtures and human confirmation are complete.

## Error Handling

- Schema and compiler failures use typed, stable error codes rather than raw
  Pydantic or Manim traces in generation feedback.
- Internal traces remain in developer logs and job diagnostics.
- A render exception fails the private candidate; it does not create a degraded
  static fallback.
- A quality failure never silently removes the offending beat or action if that
  would change the plan's instructional meaning.
- Exhausted retries do not produce an inaccessible or unapprovable draft.
- Reviewer APIs never return failed private candidates.

## Testing Strategy

### Schema and security tests

- Closed discriminated unions for plans, beats, visuals, anchors, and actions.
- Limits on depth, node count, actions, beats, strings, arrays, and durations.
- Rejection of code, imports, arbitrary coordinates, raw colors, URLs, file
  paths, and unknown fields.

### Compiler golden tests

Hand-checked teaching plans compile to literal scene graphs and timelines for
each beat, semantic visual, and supported strategy. Expected values are authored
independently rather than constructed with compiler helpers.

### Geometry property tests

Tests cover:

- uneven glyph widths such as `3 5 6 8 9 12 15`;
- item anchors versus collection centers;
- extreme but valid rectangle dimensions;
- edge, vertex, cell, partition, and marker anchors;
- callout alignment and collision;
- frame fitting across supported aspect ratios.

### Timeline and quality mutation tests

Each quality invariant has a mutation that must fail:

- split a grouped reveal into seven one-second fades;
- apply focus styling to the answer initially;
- target the value-row center instead of `item[3]`;
- remove perimeter tracing or edge emphasis;
- shorten the conclusion hold;
- insert unexplained waits;
- exceed the twelve-second ceiling.

### Real render probes

Real Manim renders are sampled at beat boundaries. Tests verify visibility,
semantic style roles, alignment, clipping, state order, and final-answer
persistence using rendered output rather than mocks.

### Demo end-to-end tests

The actual demo slides exercise generation, validation, review, publication,
reuse, and final MP4 rendering for median and perimeter. Bedrock may be mocked
with fixed v3 teaching plans in deterministic CI, but layout, compilation,
preview, rendered probes, and final video rendering remain real.

## Demo Acceptance Contracts

### Median

- Total duration is 6–12 seconds.
- All values reveal together or with no more than a 0.15-second stagger.
- Every value begins neutral.
- The `8` transitions to `focus` only after the full ordered collection is
  visible.
- The median callout targets `values.item[3].bottom`, derived from the final
  glyph bounds rather than the value-row center.
- Rendered alignment is within the central anchor tolerance.
- The conclusion appears last and remains readable for at least 1.5 seconds.

### Perimeter

- Total duration is 6–12 seconds.
- A visible beat traces the boundary or emphasizes opposite length and width
  edge pairs.
- Length and width labels remain attached to their corresponding edge anchors.
- The visible edge reasoning maps into `2 × (length + width)`.
- The evaluated answer appears last and remains readable for at least 1.5
  seconds.

## Rollout

Because compatibility is not required, rollout is a clean v3 cutover:

1. Introduce v3 plan and scene-program schemas.
2. Build the compiler and renderer behind tests.
3. Switch meta-template generation to emit only v3 teaching plans.
4. Replace draft persistence and review output with the v3 documents and quality
   report.
5. Increment compiler and renderer versions.
6. Reset the disposable demo database and generated artifacts.
7. Run the complete demo flow for median and perimeter.

The feature flags remain dev-only until the v3 demo contracts and broader
evaluation set pass consistently.
