# Meta-template Demo Runbook

## What this demo proves

This local developer demo shows the meta-template loop end to end: the
application observes a concrete, solvable problem for which `text_card` is the
only compatible fallback, queues a fingerprint, asks the worker to generate a
bounded **semantic teaching plan**, compiles that plan into a parameterized
scene program, validates and quality-gates it privately, requires human review,
publishes an immutable version, and offers that version for a similar problem.

What the model produces is a lesson, not animation code: one learning
objective, one primary semantic visual, a closed explanation strategy, and three
to five ordered teaching beats ending in an explicit conclusion. Every preview
and render resolves the compiled program against the current field values, so
layout, semantic anchors and the evaluated answer are recomputed for each new
problem.

Two lessons are published during the demo, both from the bundled deck:

- `rectangle_perimeter` — a `boundary_trace` lesson that traces the rectangle's
  boundary and labels the measured edges, then states `2 × (length + width)`.
- `median_of_seven` — a `pair_elimination` lesson that reveals seven ordered
  values together, pairs them from the outside inward, and calls out the single
  unpaired middle value.

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
META_REQUIRED_FIXTURE_COUNT=1
```

`local-meta-demo` is a disposable reviewer token example. The observation
threshold controls how many times a math pattern must be seen across
lectures before the pipeline auto-drafts a template from it; it's lowered
from its normal value of five to one solely to make the demo fit in one
session. `META_REQUIRED_FIXTURE_COUNT` is a separate setting controlling how
many human-verified real fixtures a reviewer must supply before a draft can
be approved and published; it's lowered from its normal value of five to one
for the same reason.

**Keep `META_REQUIRED_FIXTURE_COUNT` no higher than `FINGERPRINT_OBSERVATION_THRESHOLD`.**
Only a fixture generated from a real observation gets a source excerpt, and
only fixtures with a source excerpt can ever count toward the requirement —
so with the threshold at one, a draft only ever has one real observation
behind it, and only one fixture can ever qualify no matter what a reviewer
fills in. Setting the required count higher than the threshold makes the
gate permanently unsatisfiable. Restart the backend and worker after
changing either value because both processes read `backend/.env`.

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

**Reset the disposable meta database after migrating to the v3 teaching-plan
schema.** Compatibility with the earlier generated-animation-document format is
intentionally unsupported: a draft or published version created before the
cutover carries no teaching plan and no scene program, so it can neither be
reviewed nor rendered by the current runtime, and its stored artifact hash no
longer matches the current compiler and renderer versions (approval rejects it
as stale by design). There is no upgrade path and none is planned — the demo
database is disposable, so replace it.

Also use a clean disposable meta database before each full rehearsal, so a prior
job or published version cannot suppress a new draft for the same fingerprint.

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

Select only the detected candidate from slide 1 and click **Get options.**
Before proceeding, verify that `text_card` is the only compatible fallback.
Choosing it manually instead of an offered structural template does not create
a learning observation.

When `text_card` is the only compatible option, the option list shows a hint —
"No built-in visualization fits this problem yet … it may propose a brand-new
visualization template" — which is the end-user's cue that this selection feeds
the meta-template loop.

Select `text_card`, click **Review storyboard.**, approve the scene, and render
through the normal workflow. The slide 1 rectangle perimeter is 22.

### 3. Watch the worker create a draft

Return to the launch terminal. The observation threshold of one should enqueue
generation, and the worker should report a generated draft ID after Bedrock
proposes the bounded teaching plan, the compiler lowers it to a scene program,
and the static and rendered quality gates pass. The worker checks for queued
work on a two-second polling interval, so allow at least one poll before
troubleshooting.

Every gate runs *before* the draft is persisted, so a candidate that fails math,
fixture, safety, static-quality, render or rendered-quality checks never becomes
a draft at all. There is no failed-validation draft to walk through: the review
list only ever contains candidates that already passed everything. If generation
cannot produce a passing candidate within its internal retries, the worker marks
the job as needing manual authoring and logs a single structured reason — it does
not surface a broken draft, retry counts, or a validator stack trace.

### 4. Review and publish the perimeter lesson

Open `http://localhost:5173/?meta-review`, enter reviewer token
`local-meta-demo`, and click **Load drafts**. Open the new pending draft and:

1. Read the **Teaching plan** panel. It shows the learning objective, the ordered
   teaching beats as `Kind · intent` lines, and the total compiled duration. For
   the perimeter lesson expect four beats — reveal the rectangle, trace the
   boundary and name the measured edges, pair the edges into
   `2 × (length + width)`, then state the perimeter — and a duration inside the
   6–12 second budget (this lesson compiles to 6.5 seconds).
2. Confirm the green quality lines **"Pacing passed"** and **"Anchor alignment
   passed"** are present. These are pass-only summaries; raw check codes, paths
   and internal details are never shown, because a draft that failed a check
   never reaches review.
3. Inspect the preview. It must show a proportional rectangle whose boundary is
   traced as one closed loop, with the two dimension callouts **`length`**
   attached beneath the bottom edge and **`width`** attached at the left edge —
   each anchored to the edge it measures, not floating near the shape's centre.
   The evaluated answer appears only in the conclusion band at the bottom, and
   resolves to `22`.
4. Inspect the fixture results and predicate coverage. The panel separates the
   one real example you must verify ("Fixtures to verify") from the
   system-generated, read-only "Guard cases" — you only fill in the former.
   Positive examples that are not tied to a real observation are no longer
   generated, so every fixture shown under "Fixtures to verify" can actually be
   approved.
5. For the positive fixture tied to slide 1, leave the params as generated
   (`length` 8, `width` 3), enter the expected result `{"answer": 22}`, and click
   **Save fixture**. Confirming the answer for **unchanged** params records your
   verification and keeps the existing validation, quality and preview evidence.
   **Changing a fixture's params instead discards that evidence** (the stored
   report no longer describes the artifact you are approving), which clears the
   preview and blocks approval until a new candidate is generated — so do not
   edit the params during the demo.
6. Enter the unique lowercase template name `rectangle_perimeter`.
7. Confirm that the mathematical semantics and preview are correct, then click
   **Approve and publish**.

Approval remains disabled until validation passes, every guard predicate has a
negative witness, the required real fixtures are confirmed, the quality report
still matches the artifact being approved, the template name is valid, and the
reviewer explicitly confirms the mathematics.

Once approved, the draft leaves the reviewer's world: the review list no longer
lists it, and opening its detail URL returns 404. Capture anything you want to
talk about while the draft is still pending.

### 5. Reuse the template with slide 2

Return to `http://localhost:5173` and upload the same fixture again. Select only
slide 2 and click **Get options.** The problem has the same rectangle-perimeter
structure with a correct answer of `28`; the published
`rectangle_perimeter` template should now appear in the point-in-time option
list.

If it is offered, select it, build and approve the storyboard scene, then
render the MP4 through the normal flow. Confirm that the reused template
re-resolves for the new numbers: the rectangle is drawn to the 10-by-4 ratio,
both dimension callouts stay attached to their edges at the new geometry, and
the conclusion resolves to `28`. Nothing about the second render reuses slide 1's
coordinates — layout and anchors are recomputed from the stored program.

If it is not offered, explain that classification is probabilistic, request
options again from a fresh upload, or use the troubleshooting guidance below.

### 6. Publish the median lesson with slide 3

Slide 3 ("What is the median of 3, 5, 6, 8, 9, 12, and 15?", answer `8`) has a
different fingerprint, so it seeds its own learning loop. Select only slide 3,
verify `text_card` is the only compatible fallback, and repeat the seed and
worker steps. Do not imply that `rectangle_perimeter` should match it.

Review the resulting draft the same way, checking the checkpoints specific to a
median lesson:

1. Four teaching beats — reveal the ordered values, pair them from the outside
   inward, focus the unpaired middle value, state the median — and a compiled
   duration inside the 6–12 second budget (this lesson compiles to 6.25
   seconds).
2. In the preview, the seven values appear **together as one group**, not one at
   a time, and all seven start in the same neutral style. No value is
   pre-emphasized before the lesson gets to it, and the answer is not visible
   yet.
3. The `median` callout is anchored to the middle value itself — the arrow lands
   under the `8`, not under the centre of the whole row. An item-specific
   instruction pointing at the collection as a whole is a quality failure and
   would have kept the draft out of review.
4. Verify the positive fixture with `{"answer": 8}` (params unchanged), name the
   template `median_of_seven`, confirm the mathematics, and publish.

### 7. Optional slide 4

If time permits, slide 4 asks for a unit conversion and has answer `2750`. Begin
from a clean rehearsal state or use a fingerprint that has not already produced a
job, and repeat the seed, worker, review, and publish sequence.

## Presenter talk track

- “The system learns only from an honest fallback: `text_card` must be the only
  compatible option.”
- “The worker is separate from the request path and polls the durable queue
  every two seconds.”
- “The model proposes a lesson, not code: an objective, one semantic visual, a
  strategy, and three to five teaching beats. It never emits Python, Manim,
  coordinates, colors, or durations.”
- “A deterministic compiler turns that lesson into a parameterized scene
  program, and every render re-resolves it: measure, lay out, resolve anchors,
  bind the timeline, render.”
- “Quality gates run before the draft exists. Everything in this review list has
  already passed pacing, anchor-alignment and real rendered-frame checks — so
  there is no broken draft to show you.”
- “The reviewer confirms the known result, checks the beats, predicate coverage
  and preview, and explicitly confirms the mathematics.”
- “Publishing creates an immutable dynamic template version; it does not
  overwrite a built-in template.”
- “The second rectangle’s answer is `28`, and its layout and anchors are
  recomputed — but classification is probabilistic, so a live match is evidence
  of reuse rather than a production reliability guarantee.”
- “These flags are not production-ready and remain disabled by default.”

## Expected checkpoints

1. The upload finds candidates on all four fixture slides.
2. Slide 1 offers only the compatible fallback `text_card`.
3. The worker logs a generated draft ID after the observation is recorded, and
   the review list contains only that pending draft. No failed-validation draft
   ever appears — invalid candidates stay private, so there is no
   failed-draft workflow to demonstrate.
4. `http://localhost:5173/?meta-review` loads the draft with `local-meta-demo`
   and shows its ordered teaching beats, its total compiled duration, and green
   “Pacing passed” / “Anchor alignment passed” quality lines.
5. The perimeter draft compiles to 6.5 seconds and the median draft to 6.25
   seconds — both inside the 6–12 second budget.
6. The perimeter preview traces the boundary as one closed loop over all four
   edges, with `length` attached beneath the bottom edge and `width` attached at
   the left edge; both labels stay attached at slide 2's different geometry.
7. The median preview reveals all seven values **together**, all in the same
   neutral style, with no value emphasized and no answer visible yet.
8. The median callout arrow lands under the `8` itself, not under the centre of
   the row.
9. Each lesson's evaluated answer appears only in the conclusion band, only at
   the end, and holds there for at least a second and a half: `22` for
   perimeter, `8` for median.
10. Saving the known answer for **unchanged** params keeps the draft approvable;
    **Approve and publish** then becomes available once every approval gate
    passes.
11. After approval the draft disappears from the review list and its detail URL
    returns 404.
12. Slide 2 can offer `rectangle_perimeter`, and its rendered mathematics
    resolves to `28` at re-resolved geometry.

## Troubleshooting

- **No worker draft appears:** Confirm the backend and worker were restarted
  after enabling the flags. Confirm slide 1 offered only `text_card`; a manual
  text-card choice in place of a compatible structural template is not learned.
- **The worker stays idle:** Confirm
  `FINGERPRINT_OBSERVATION_THRESHOLD=1`. A job or version for the same
  fingerprint may already exist in `backend/var/meta.db`; use the rehearsal
  reset only for disposable local data. An older approved version must be
  replaced by that reset before a rehearsal.
- **The worker exits immediately:** Confirm both
  `META_TEMPLATES_ENABLED=true` and `META_CODEGEN_ENABLED=true` are visible in
  `backend/.env`, then restart it.
- **No draft appears and the job needs manual authoring:** Automatic generation
  exhausted its internal retries without producing a candidate that passed every
  gate, so nothing was persisted — by design, an invalid candidate is never shown
  to a reviewer. Check the worker log for the single structured reason, then
  either rehearse with a different slide or author the template by hand. Retry
  counts and validator internals are deliberately not exposed through the review
  API or UI.
- **A draft you were reviewing 404s:** It is no longer `pending_review` —
  approving, rejecting or superseding a draft removes it from the reviewer's
  world, and the review list shows pending drafts only. This is expected after
  **Approve and publish**.
- **Approval stays disabled or returns 422:** Confirm the draft is pending
  review, its validation and quality reports passed, negative witnesses cover
  every guard predicate, enough real fixtures are confirmed, the template name is
  valid and unique, and the mathematical-semantics checkbox is selected. If you
  changed a fixture's **params**, the stored evidence was discarded on purpose
  and this draft can no longer be approved — generate a new candidate.
- **Bedrock fails:** Verify credentials, region, configured model access, and
  network access in the worker shell as well as the backend shell.
- **Preview or render fails:** Verify Manim, Cairo, Pango, ffmpeg, LaTeX, and
  `dvisvgm` are installed and on `PATH`.
- **A draft or version from before the v3 cutover:** v1/v2 artifacts are
  intentionally unsupported and cannot be reviewed, approved or rendered. Perform
  the disposable database reset above; do not try to migrate them.
- **The review API fails in the browser:** Restart Vite so it loads the `/meta`
  proxy, re-enter `local-meta-demo`, and click **Load drafts**.
- **Slide 2 does not offer the published template:** Request options from a
  fresh upload and keep the wording close to slide 1. Classification is
  probabilistic, so do not present a miss as a deterministic failure.

## After the demo

Stop the application with Ctrl-C. Remove the seven meta-template values from
`backend/.env`, or set the six feature and threshold controls back to their
normal disabled/default values; remove the disposable reviewer token. Preserve
or delete the disposable database and generated artifacts according to local
project needs. Never carry this demo configuration, its token, or its lowered
observation threshold and fixture count into production.
