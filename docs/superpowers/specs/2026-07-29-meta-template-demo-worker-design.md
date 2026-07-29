# Meta-template Demo Worker Design

## Goal

Make the existing dev-only meta-template pipeline demonstrable end to end from
the browser by finishing its standalone queue worker, wiring the review API
through Vite, and documenting the local feature flags.

This is a demo-readiness change, not production worker infrastructure.

## Existing Context

The application already records unsupported-shape observations, fingerprints
them, enqueues leased generation jobs, generates and validates one draft via
`run_generation_job(owner=...)`, exposes authenticated review/approval APIs,
and can classify and render approved dynamic templates.

Two seams prevent a smooth browser demo:

1. `backend/scripts/meta_worker.py` still raises `NotImplementedError` when
   code generation is enabled.
2. The Vite dev server does not proxy `/meta`, although the review panel uses
   relative `/meta/...` URLs.

The original meta-template design requires a separate leased worker. Running
generation as a FastAPI background task would couple slow Bedrock/Manim work to
the web process and behave poorly under Uvicorn reload or multiple web workers.

## Chosen Approach

### Standalone polling process

`python -m scripts.meta_worker` will remain a separate process. Its loop will:

- exit successfully without polling when either the overall meta-template
  feature or code generation is disabled;
- generate a stable owner label from the hostname and process ID;
- call the existing `run_generation_job(owner=...)` once per iteration;
- immediately check for another job after producing a draft;
- wait for a short fixed interval after an idle or failed iteration so an empty
  queue or a failed external call cannot create a busy loop;
- log startup, successful draft creation, unexpected iteration failures, and
  clean shutdown;
- stop cleanly on `KeyboardInterrupt`.

The generation pipeline remains responsible for claiming leases, marking
expected generation failures, applying retry cooldowns, validating drafts, and
completing jobs. The worker will not duplicate those state transitions.

The polling function will accept injected `process_one` and `wait` callables,
an owner, and a poll interval. These narrow dependencies make loop behavior
deterministic in unit tests without accessing SQLite, Bedrock, Manim, signals,
or wall-clock time.

### Frontend proxy

Vite will proxy `/meta` to `http://localhost:8000`, matching the existing
relative URLs used by `MetaReviewPanel`. No review-panel fetch code changes.

### Local configuration documentation

`backend/.env.example` will list every flag required for a local demo, using
disabled or blank safe defaults. The real `.env` remains user-owned and will
not be changed.

The README will describe three local processes—backend, frontend, worker—and
the browser flow from unsupported fallback through review, publication, and a
second matching problem.

## Alternatives Considered

1. **FastAPI startup background task:** fewer terminals, but Uvicorn reload can
   create duplicate workers and slow generation becomes coupled to web-server
   lifecycle. Rejected.
2. **Shell loop around a one-shot Python command:** quickest throwaway option,
   but has weak logging and shutdown behavior and leaves the checked-in worker
   unfinished. Rejected.
3. **External queue system or process supervisor:** appropriate for production,
   but unnecessary for tomorrow's single-machine demo. Deferred.

## Error Handling

`run_generation_job` already converts expected proposal/validation pipeline
exceptions into durable failed-job state and returns `None`. The polling worker
will therefore treat `None` as an idle-or-handled-failure result and wait before
retrying.

Unexpected exceptions escaping the pipeline will be logged with a traceback,
followed by the same wait. They will not terminate the demo worker.

Ctrl-C will terminate the loop with exit code zero and a shutdown log message.

## Tests

Backend unit tests will prove:

- disabled settings cause `main()` to exit without entering the loop;
- a produced draft causes an immediate next iteration;
- an idle iteration waits before polling again;
- an unexpected exception is contained and waits before retrying;
- `KeyboardInterrupt` exits cleanly.

The frontend build will verify the Vite configuration remains valid. The full
backend and frontend suites will run before completion.

## Demo Success Criteria

With the documented flags enabled and all three processes running:

1. A solvable problem unsupported by static templates records an observation
   and enqueues a job.
2. The worker automatically creates a reviewable draft.
3. `http://localhost:5173/?meta-review` loads the draft using a reviewer token.
4. A reviewer can inspect, refine, and approve the draft.
5. A later matching problem can be offered the approved dynamic template and
   rendered through the normal storyboard interface.
