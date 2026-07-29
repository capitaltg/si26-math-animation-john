# Meta-template Demo Runbook Design

## Goal

Create one durable, canonical guide for demonstrating the dev-only
meta-template workflow without relying on prior chat history.

## Canonical location

The complete guide will live at:

`docs/meta-template-demo.md`

The existing README section will be shortened to a brief overview and a link
to the canonical guide so instructions do not drift between two files.

## Audience

The runbook is for a developer preparing and delivering a local product demo.
It assumes access to the repository, local development dependencies, AWS
credentials for Bedrock, and the reviewer token configured for the demo.

## Guide structure

The guide will contain:

1. A short explanation of what the demonstration proves.
2. A pre-demo checklist covering dependencies, database migrations, feature
   flags, AWS access, and the bundled fixture deck.
3. The single development startup command and the expected backend, frontend,
   and worker signals.
4. A primary demo sequence:
   - upload the bundled four-slide fixture;
   - use slide 1 as the rectangle-perimeter seed;
   - confirm `text_card` is the only compatible fallback;
   - wait for the background worker to generate a draft;
   - review, validate, name, and publish the draft;
   - use slide 2 to show the published dynamic template being reused.
5. Optional follow-on examples using slides 3 and 4 to demonstrate other
   unsupported problem structures.
6. Presenter cues explaining what to say at important transitions.
7. Recovery and troubleshooting instructions for stale state, missing drafts,
   validation failures, Bedrock failures, rendering failures, and browser proxy
   errors.
8. A concise reset procedure for rehearsing the demo again.

## Fixture mapping

The runbook will use:

`eval/fixtures/meta_template_unsupported_shapes_deck.pptx`

- Slide 1: rectangle perimeter, 8 cm by 3 cm; seed answer is `22`.
- Slide 2: rectangle perimeter, 10 cm by 4 cm; reuse answer is `28`.
- Slide 3: median of 3, 5, 6, 8, 9, 12, and 15; answer is `8`.
- Slide 4: convert 2.75 kilometers to meters; answer is `2750`.

Answers are documented for reviewer fixture entry but do not appear on the
slides.

## Scope

This change updates documentation only. It does not alter the worker, backend,
frontend, fixture deck, feature flags, or deployment behavior.

## Verification

- Confirm every command and path exists in the current repository.
- Confirm UI labels match the current frontend.
- Confirm all feature flags match backend configuration.
- Confirm the bundled fixture contains four slides.
- Confirm the README points to the canonical guide and does not retain a second
  full workflow.
