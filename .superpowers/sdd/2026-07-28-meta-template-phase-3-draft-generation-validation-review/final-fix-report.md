# Phase 3 final fix report

## Changes

- Rejected Bedrock proposals whose non-null fixture `observation_id` is not one
  of the supplied observations.
- Kept `run_generation_job()` inert until both `meta_templates_enabled` and
  `meta_codegen_enabled` are enabled. The early return occurs before a job
  claim or a Bedrock call.
- Made reject-and-refine recovery durable: if proposal generation or an
  unexpected validation/persistence step raises after a rejection is recorded,
  the original draft is restored to `pending_review`. The rejection review and
  feedback remain durable, and the API returns HTTP 409 with a retry message
  rather than an unhandled 500.
- Updated worker-path test fixtures to explicitly enable both rollout flags.

## Tests

Focused red/green regression command:

```text
cd backend && .venv/bin/pytest \
  tests/meta/test_draft_generation.py::test_propose_template_draft_rejects_fixture_for_unknown_observation \
  tests/meta/test_generation_pipeline.py::test_run_generation_job_leaves_job_queued_when_generation_is_disabled \
  tests/meta/test_review_api.py::test_reject_draft_restores_pending_review_when_refinement_fails -q
```

Result: `4 passed in 1.18s`.

Focused affected-area suite:

```text
cd backend && .venv/bin/pytest \
  tests/meta/test_draft_generation.py \
  tests/meta/test_validation_pipeline.py \
  tests/meta/test_generation_pipeline.py \
  tests/meta/test_review_actions.py \
  tests/meta/test_review_api.py -q
```

Result: `24 passed in 7.43s`.

Proportional Phase 1-3 integration/regression suite:

```text
cd backend && .venv/bin/pytest tests/meta tests/render -q
```

Result: `254 passed, 6 warnings in 15.93s`. The warnings are existing Alembic
`path_separator` deprecation warnings in migration tests.

## Files changed

- `backend/app/meta/draft_generation.py`
- `backend/app/meta/generation_pipeline.py`
- `backend/app/meta/review_actions.py`
- `backend/app/meta/review_api.py`
- `backend/tests/meta/test_draft_generation.py`
- `backend/tests/meta/test_generation_pipeline.py`
- `backend/tests/meta/test_review_actions.py`
- `backend/tests/meta/test_review_api.py`
- `backend/tests/meta/test_generation_e2e.py`

## Self-review

- The generation gate checks both rollout flags before opening a DB session, so
  disabled execution cannot claim, lease, fail, or call Bedrock for a job.
- Observation grounding is checked only after the Bedrock response has passed
  the closed Pydantic DSL schema, as required.
- Expected validation failures already produce a `failed_validation` revision,
  which is refinable. The recovery path targets unexpected exceptions that
  would otherwise leave the only draft `rejected` and unreachable from the
  review queue.
- Concurrent rejection handling was considered but not changed: the requested
  fixes do not require it, and the existing state check plus review audit trail
  remains unchanged.
