# Week 1 Review Remediation Design

**Status:** Approved through the 2026-07-20 final review and the request to address its findings.

## Goal

Close the five final-review findings without expanding the Week 1 product scope: ground candidate discovery in the uploaded slides, make storyboard and template models reject unsafe states, preserve successful render artifacts when rerenders fail, and complete the required latency/evaluation tooling.

## Design

### Candidate grounding

Treat every Bedrock field as untrusted. A discovered item is retained only when its `slide_index` belongs to the chunk sent to Bedrock and its `source_excerpt`, after whitespace normalization and case folding, occurs in that exact slide. Invalid items are dropped independently so one hallucinated candidate does not discard valid candidates from the same response.

### Scene invariants

Represent kindergarten as grade `0`, making the supported range `0..8`. Every scene has exactly one durable source: a discovered `candidate_id` or `manual_source_text`. Fallback scenes require a nonblank `fallback_reason`; non-fallback scenes may not carry one. These rules live in the Pydantic model so API, LLM, and teacher-edit paths cannot drift.

### Number-line renderability

The number-line guard rejects a negative starting value, any negative running total, and any value span over 20 units. Twenty unit intervals remain legible with the current `NumberLine(..., include_numbers=True)` implementation and prevent arbitrary inputs from creating extremely large tick/label collections.

### Atomic rerenders

Do not delete the destination before invoking Manim. The worker renders entirely inside its unique scratch directory and replaces the destination only after the new artifact exists, preserving the previous successful artifact on timeout or failure.

### Week 1 acceptance tooling

Add the planned three-scene latency benchmark, programmatic zero-candidate/distractor/ambiguous PPTX fixture generator, and discovery eval runner. Generated PPTX files and benchmark videos remain ignored. Result documents record actual live output when Bedrock credentials are available; otherwise they state the exact external blocker rather than inventing measurements.

## Verification

- Focused red/green tests for every correctness invariant.
- Full backend `pytest` suite, including real Manim MP4 and PNG rendering.
- Python compilation and dependency consistency checks.
- Fixture generation plus live benchmark/eval runs when AWS credentials and model access are available.
