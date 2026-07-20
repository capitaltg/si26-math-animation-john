# Eval-Set Timing Report Design

**Status:** Approved in conversation on 2026-07-20.

## Goal

Create a standalone Markdown report that records how long each of the six real
evaluation PPTX decks takes to process through the current live AWS Bedrock
candidate-discovery pipeline.

## Measurement

- Run the six files from `eval set/` sequentially in sorted filename order.
- Measure each complete `run_fixture(path)` call with `time.perf_counter()`.
- Record the candidate count and elapsed wall time for each deck.
- Measure and report the complete six-deck wall time independently rather than
  deriving it from rounded per-deck values.
- Use the configured Bedrock model and current `main` implementation without
  mocks or concurrency.

## Report

Write `docs/eval-set-timing-2026-07-20.md` with:

- execution date, model, and sequential measurement method;
- a table of deck name, candidate count, and elapsed seconds;
- total duration and arithmetic mean per deck;
- a note that Bedrock output and latency vary between live runs; and
- a reproducible timing command that does not expose credentials.

Times will be rounded to two decimal places for readability. The raw measured
values from the successful command will be used for totals and averages.

## Safety and Scope

The user explicitly approved sending extracted slide contents from these six
local PPTX files to AWS Bedrock. The run will not print credentials or modify
the source decks. No reusable benchmark script or production behavior change
is included in this task.
