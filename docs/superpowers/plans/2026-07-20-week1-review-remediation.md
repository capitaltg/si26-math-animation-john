# Week 1 Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each correctness change. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every finding from the final Week 1 code review and complete the missing Week 1 acceptance tooling.

**Architecture:** Put trust and state validation at existing model boundaries, retain subprocess render isolation while making final replacement atomic, and add standalone scripts for the manual Bedrock acceptance checks. No Week 2 routes, classification, or frontend work is included.

**Tech Stack:** Python 3.11+, Pydantic v2, python-pptx, Manim, boto3/Bedrock, pytest.

## Global Constraints

- Bedrock output is untrusted and may not invent document provenance.
- Arithmetic and running totals remain local Python computations.
- Every behavior change starts with a failing automated test.
- Generated binary fixtures and benchmark videos remain untracked.

---

### Task 1: Ground candidate discovery

**Files:**
- Modify: `backend/tests/pipeline/test_discovery.py`
- Modify: `backend/app/pipeline/discovery.py`

- [x] Add tests proving out-of-chunk indexes and fabricated excerpts are dropped while valid normalized excerpts remain.
- [x] Run the focused tests and confirm they fail for the grounding assertions.
- [x] Add chunk-range and normalized-substring validation before constructing each `Candidate`.
- [x] Run the focused tests and confirm they pass.

### Task 2: Enforce scene and number-line invariants

**Files:**
- Modify: `backend/tests/models/test_models.py`
- Modify: `backend/app/models/scene.py`
- Modify: `backend/tests/templates/test_number_line_guard.py`
- Modify: `backend/app/templates/number_line/guard.py`

- [x] Add failing tests for grades outside `0..8`, missing/duplicate sources, invalid fallback reasons, negative starts, and spans over 20.
- [x] Add Pydantic fields/model validators and guard checks that express those invariants.
- [x] Run both focused test modules and confirm they pass.

### Task 3: Preserve successful artifacts on render failure

**Files:**
- Modify: `backend/tests/render/test_full_render.py`
- Modify: `backend/app/render/full_render.py`

- [x] Add a failing test that mocks a failed subprocess while a valid destination already exists.
- [x] Remove the pre-render unlink; continue relying on scratch isolation and the worker's final replacement.
- [x] Run the render tests and confirm both failure preservation and real renders pass.

### Task 4: Complete acceptance tooling

**Files:**
- Create: `backend/scripts/benchmark_latency.py`
- Create: `eval/generate_fixtures.py`
- Create: `eval/run_eval.py`
- Create: `docs/latency-benchmark-week1.md`
- Create: `docs/eval-results-week1.md`

- [x] Add the three-scene end-to-end benchmark from the Week 1 plan.
- [x] Add deterministic PPTX fixture generation and the JSON discovery report runner.
- [x] Generate all fixtures and verify the scripts compile.
- [x] Run live Bedrock evaluation and benchmark when credentials permit, recording actual output or the exact blocker.

### Task 5: Final verification

- [x] Run the entire backend test suite.
- [x] Run `compileall` and `pip check`.
- [x] Review `git diff` for unrelated changes and scan for placeholders.
