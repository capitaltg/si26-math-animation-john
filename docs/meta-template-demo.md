# Meta-template Demo Runbook

## What this demo proves

This local developer demo shows the meta-template loop end to end: the
application observes a concrete, solvable problem for which `text_card` is the
only compatible fallback, queues a fingerprint, asks the worker to generate a
bounded declarative template draft, validates that draft, requires human
review, publishes an immutable version, and offers that version for a similar
problem.

Classification is probabilistic. A published template may not be offered on
every run, even for closely worded problems. The meta-template flags and this
workflow are not production-ready; keep every flag disabled outside a
disposable local development environment.

## Before the demo

### Install and migrate

The commands below require a virtual environment at the repository-root path
`.venv`. From the repository root, create it first if it does not already
exist:

```bash
python3 -m venv .venv
```

Then install the current backend and development dependencies and bring the
demo database schema up to date:

```bash
cd backend
../.venv/bin/pip install -e ".[dev]"
../.venv/bin/alembic upgrade head
cd ..
```

### Configure the dev-only flags

Add the following values to `backend/.env`:

```dotenv
META_TEMPLATES_ENABLED=true
META_CODEGEN_ENABLED=true
META_APPROVAL_ENABLED=true
META_DYNAMIC_CLASSIFIER_ENABLED=true
META_REVIEWER_TOKEN=local-meta-demo
FINGERPRINT_OBSERVATION_THRESHOLD=1
```

`local-meta-demo` is a disposable reviewer token example. The observation
threshold is lowered from its normal value of five to one solely to make the
demo fit in one session. Restart the backend and worker after changing these
values because both processes read `backend/.env`.

### Confirm external dependencies

- Confirm the AWS credential chain, `us-east-1` region (unless overridden), and
  access to the configured Amazon Bedrock model are available to both the
  backend and worker shells.
- Confirm Manim, Cairo, Pango, ffmpeg, LaTeX, and `dvisvgm` are installed. The
  launch scripts add `/Library/TeX/texbin` and `/opt/homebrew/bin` to `PATH`.
- Confirm the canonical fixture exists at
  `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`.

## Start the application

From the repository root, launch FastAPI, Vite, and the meta-template worker
together:

```bash
./scripts/run-dev.sh
```

Open the main application at `http://localhost:5173`. Keep the terminal visible:
the worker polls its durable queue every two seconds and logs the generated
draft ID. Press Ctrl-C when the demo is over to stop all three processes.

If process-level troubleshooting is needed, run
`./scripts/run-backend.sh`, `./scripts/run-frontend.sh`, and
`./scripts/run-meta-worker.sh` in separate terminals.

## Rehearsal reset

Use a clean disposable meta database before each full rehearsal so a prior job
or published version cannot suppress a new draft for the same fingerprint.
Stop the application, preserve any local data that matters, replace
`backend/var/meta.db` with a fresh demo database, and rerun:

```bash
cd backend
../.venv/bin/alembic upgrade head
cd ..
```

Also remove any rehearsal-only generated artifacts from
`backend/var/meta_artifacts` if they are no longer needed. Do not perform this
reset against a shared or production database. Restart `./scripts/run-dev.sh`
after the reset and confirm all six dev-only values remain in `backend/.env`.

## Live demo sequence

### 1. Introduce the fixture

At `http://localhost:5173`, upload
`eval/fixtures/meta_template_unsupported_shapes_deck.pptx`. Explain that its
four slides deliberately contain solvable shapes not covered by the built-in
structural templates:

1. Rectangle perimeter: 8 centimeters by 3 centimeters; answer `22`.
2. Rectangle perimeter: 10 centimeters by 4 centimeters; answer `28`.
3. Median of 3, 5, 6, 8, 9, 12, and 15; answer `8`.
4. Convert 2.75 kilometers to meters; answer `2750`.

### 2. Seed a new template with slide 1

Select only the detected candidate from slide 1 and click **Get options**.
Before proceeding, verify that `text_card` is the only compatible fallback.
Choosing it manually instead of an offered structural template does not create
a learning observation.

Select `text_card`, click **Review storyboard**, approve the scene, and render
through the normal workflow. The slide 1 rectangle perimeter is 22.

### 3. Watch the worker create a draft

Return to the launch terminal. The observation threshold of one should enqueue
generation, and the worker should report a generated draft ID after Bedrock
proposes the bounded DSL documents and deterministic validation and preview
rendering complete. The worker checks for queued work on a two-second polling
interval, so allow at least one poll before troubleshooting.

### 4. Review and publish

Open `http://localhost:5173/?meta-review`, enter reviewer token
`local-meta-demo`, and click **Load drafts**. Open the new pending draft and:

1. Inspect the classifier description, preview, fixture results, and predicate
   coverage.
2. For the positive fixture tied to slide 1, enter the expected result
   `{"answer": 22}` and click **Save fixture**. Saving reruns validation and
   preview generation.
3. If validation fails, enter specific feedback and click
   **Reject and request refinement**, then review the new revision.
4. Enter the unique lowercase template name `rectangle_perimeter`.
5. Confirm that the mathematical semantics and preview are correct, then click
   **Approve and publish**.

Approval remains disabled until validation passes, every guard predicate has a
negative witness, the required real fixtures are confirmed, the template name
is valid, and the reviewer explicitly confirms the mathematics.

### 5. Reuse the template with slide 2

Return to `http://localhost:5173` and upload the same fixture again. Select only
slide 2 and click **Get options**. The problem has the same rectangle-perimeter
structure with a correct answer of `28`; the published
`rectangle_perimeter` template should now appear in the point-in-time option
list.

If it is offered, select it, build and approve the storyboard scene, then
render the MP4 through the normal flow. If it is not offered, explain that
classification is probabilistic, request options again from a fresh upload, or
use the troubleshooting guidance below.

### 6. Optional slides 3 and 4

If time permits, show that the remaining unsupported shapes can seed distinct
learning loops:

- Slide 3 asks for a median and has answer `8`.
- Slide 4 asks for a unit conversion and has answer `2750`.

For each slide, begin from a clean rehearsal state or use a fingerprint that
has not already produced a job. Select only that slide, verify `text_card` is
the only compatible fallback, and repeat the seed, worker, review, and publish
sequence. Do not imply that `rectangle_perimeter` should match either problem.

## Presenter talk track

- “The system learns only from an honest fallback: `text_card` must be the only
  compatible option.”
- “The worker is separate from the request path and polls the durable queue
  every two seconds.”
- “Generation is constrained to a bounded DSL, then deterministically
  validated and previewed before a reviewer can publish anything.”
- “The reviewer supplies the known result `{"answer": 22}`, checks predicate
  coverage and the preview, and explicitly confirms the mathematics.”
- “Publishing creates an immutable dynamic template version named
  `rectangle_perimeter`; it does not overwrite a built-in template.”
- “The second rectangle’s answer is `28`, but classification is probabilistic,
  so a live match is evidence of reuse rather than a production reliability
  guarantee.”
- “These flags are not production-ready and remain disabled by default.”

## Expected checkpoints

1. The upload finds candidates on all four fixture slides.
2. Slide 1 offers only the compatible fallback `text_card`.
3. The worker logs a generated draft ID after the observation is recorded.
4. `http://localhost:5173/?meta-review` loads the draft with
   `local-meta-demo`.
5. Saving `{"answer": 22}` reruns fixture validation and preview generation.
6. **Approve and publish** becomes available only after all approval gates pass.
7. Slide 2 can offer `rectangle_perimeter`, and its rendered mathematics
   resolves to `28`.

## Troubleshooting

- **No worker draft appears:** Confirm the backend and worker were restarted
  after enabling the flags. Confirm slide 1 offered only `text_card`; a manual
  text-card choice in place of a compatible structural template is not learned.
- **The worker stays idle:** Confirm
  `FINGERPRINT_OBSERVATION_THRESHOLD=1`. A job or version for the same
  fingerprint may already exist in `backend/var/meta.db`; use the rehearsal
  reset only for disposable local data.
- **The worker exits immediately:** Confirm both
  `META_TEMPLATES_ENABLED=true` and `META_CODEGEN_ENABLED=true` are visible in
  `backend/.env`, then restart it.
- **The draft reports `failed_validation`:** Inspect the fixture details and
  predicate coverage, then use **Reject and request refinement** with targeted
  feedback.
- **Approval stays disabled:** Confirm the draft is pending review, its
  validation passed, negative witnesses cover every guard predicate, enough
  real fixtures qualify, `rectangle_perimeter` is valid and unique, and the
  mathematical-semantics checkbox is selected.
- **Bedrock fails:** Verify credentials, region, configured model access, and
  network access in the worker shell as well as the backend shell.
- **Preview or render fails:** Verify Manim, Cairo, Pango, ffmpeg, LaTeX, and
  `dvisvgm` are installed and on `PATH`.
- **The review API fails in the browser:** Restart Vite so it loads the `/meta`
  proxy, re-enter `local-meta-demo`, and click **Load drafts**.
- **Slide 2 does not offer the published template:** Request options from a
  fresh upload and keep the wording close to slide 1. Classification is
  probabilistic, so do not present a miss as a deterministic failure.

## After the demo

Stop the application with Ctrl-C. Remove the six meta-template values from
`backend/.env`, or set the five feature and threshold controls back to their
normal disabled/default values; remove the disposable reviewer token. Preserve
or delete the disposable database and generated artifacts according to local
project needs. Never carry this demo configuration, its token, or its lowered
observation threshold into production.
